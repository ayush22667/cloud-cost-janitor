import pytest
from fastmcp.exceptions import ToolError

from tests.server.fake_provider import REGION

EXPECTED_TOOLS = {
    "list_regions": (True, False),
    "find_idle_instances": (True, False),
    "find_orphaned_volumes": (True, False),
    "find_idle_load_balancers": (True, False),
    "generate_cost_report": (True, False),
    "get_plan": (True, False),
    "mark_for_teardown": (False, False),
    "unmark_teardown": (False, False),
    "delete_resource": (False, True),
}


async def test_tools_and_annotations(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == set(EXPECTED_TOOLS)
    for name, (read_only, destructive) in EXPECTED_TOOLS.items():
        ann = tools[name].annotations
        assert ann is not None, name
        assert ann.readOnlyHint is read_only and ann.destructiveHint is destructive, name
        assert tools[name].title, name


async def test_scan_tools_return_findings(client):
    inst = (await client.call_tool("find_idle_instances", {"region": REGION})).data
    assert inst["scanned"] == {"instances": 2} and inst["finding_count"] == 2
    prod = next(f for f in inst["findings"] if f["resource_id"] == "i-prod")
    assert prod["protected"] is True and prod["protection_reason"] == "tag env=prod"

    vols = (await client.call_tool("find_orphaned_volumes", {"region": REGION})).data
    assert vols["finding_count"] == 3 and all(f["status"] == "orphaned" for f in vols["findings"])

    lbs = (await client.call_tool("find_idle_load_balancers", {"region": REGION})).data
    assert lbs["finding_count"] == 1 and lbs["findings"][0]["monthly_cost_usd"] == 16.43


async def test_provider_error_becomes_tool_error(client, fake):
    fake.fail_with = "AWS UnauthorizedOperation: not allowed"
    with pytest.raises(ToolError, match="UnauthorizedOperation"):
        await client.call_tool("find_idle_instances", {"region": REGION})


async def test_generate_cost_report_builds_plan(client):
    report = (await client.call_tool("generate_cost_report", {})).data
    plan = report["plan"]
    assert plan["regions"] == [REGION] and len(plan["plan_id"]) == 12
    assert len(plan["findings"]) == 6 and plan["protected_count"] == 1
    ids = [f["resource_id"] for f in plan["findings"]]
    assert ids[:2] == ["i-prod", "i-idle"] and ids[2] == "arn:lb/empty"
    assert plan["steps"][0]["action"] == "snapshot" and plan["steps"][0]["resource_id"] == "i-idle"
    assert "recoverable" in report["summary"]
    fetched = (await client.call_tool("get_plan", {"plan_id": plan["plan_id"]})).data
    assert fetched["plan"]["plan_id"] == plan["plan_id"]
    with pytest.raises(ToolError, match="expired"):
        await client.call_tool("get_plan", {"plan_id": "nope"})


async def _plan_id(client) -> str:
    return (await client.call_tool("generate_cost_report", {})).data["plan"]["plan_id"]


async def test_delete_refusals(client, fake):
    pid = await _plan_id(client)
    call = lambda **kw: client.call_tool("delete_resource", {"region": REGION, "plan_id": pid, **kw})

    bad_plan = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": "stale"})).data
    assert bad_plan["refused"] and "expired" in bad_plan["reason"]

    not_in_plan = (await call(resource_type="volume", resource_id="vol-zzz")).data
    assert not_in_plan["refused"] and "not part of this plan" in not_in_plan["reason"]

    protected = (await call(resource_type="instance", resource_id="i-prod")).data
    assert protected["refused"] and "protected" in protected["reason"]

    wrong_type = (await call(resource_type="instance", resource_id="vol-a")).data
    assert wrong_type["refused"]

    with pytest.raises(ToolError, match="resource_type"):
        await call(resource_type="bucket", resource_id="vol-a")

    fake.volumes["vol-b"].state, fake.volumes["vol-b"].attached_instance_id = "in-use", "i-idle"
    attached = (await call(resource_type="volume", resource_id="vol-b")).data
    assert attached["refused"] and "attached to i-idle" in attached["reason"]
    assert fake.deleted == [] and fake.snapshots == []


async def test_delete_snapshots_then_deletes(client, fake):
    pid = await _plan_id(client)
    res = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid})).data
    assert res == {"resource_id": "vol-a", "deleted": True, "action": "delete_volume", "snapshot_ids": ["snap-vol-a"], "monthly_saving_usd": 0.8}
    assert fake.deleted == ["vol-a"]
    assert fake.snapshots[0][1]["janitor:source"] == "vol-a" and fake.snapshots[0][1]["janitor:plan-id"] == pid

    inst = (await client.call_tool("delete_resource", {"resource_type": "instance", "resource_id": "i-idle", "region": REGION, "plan_id": pid})).data
    assert inst["deleted"] and inst["snapshot_ids"] == ["snap-vol-root"]

    lb = (await client.call_tool("delete_resource", {"resource_type": "load_balancer", "resource_id": "arn:lb/empty", "region": REGION, "plan_id": pid})).data
    assert lb["deleted"] and lb["snapshot_ids"] == []
    assert fake.deleted == ["vol-a", "i-idle", "arn:lb/empty"]


async def test_untagged_volume_is_deletable_by_the_server(client, fake):
    """Restricting *which* resources may be deleted is IAM's job (iam/), not a server-side allowlist."""
    pid = await _plan_id(client)
    res = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-untagged", "region": REGION, "plan_id": pid})).data
    assert res["deleted"] is True and fake.deleted == ["vol-untagged"]


async def test_mark_and_unmark(client, fake):
    pid = await _plan_id(client)
    res = (await client.call_tool("mark_for_teardown", {"resource_ids": ["vol-a", "vol-zzz"], "region": REGION, "plan_id": pid, "grace_days": 7})).data
    assert res["marked"] == ["vol-a"] and res["skipped_not_in_plan"] == ["vol-zzz"]
    assert fake.volumes["vol-a"].tags["janitor:teardown-after"] == res["teardown_after"]

    blocked = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid})).data
    assert blocked["refused"] and "grace period" in blocked["reason"]

    await client.call_tool("unmark_teardown", {"resource_ids": ["vol-a"], "region": REGION})
    assert "janitor:teardown-after" not in fake.volumes["vol-a"].tags
