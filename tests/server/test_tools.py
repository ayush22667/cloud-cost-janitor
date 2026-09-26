import json

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
    "get_actual_spend": (True, False),
}


async def test_actual_spend_tool(client, fake):
    res = (await client.call_tool("get_actual_spend", {"days": 30})).data
    assert res["total_usd"] == 44.6 and res["rows"][0]["key"].startswith("Amazon Elastic")
    fake.fail_with = "Cost Explorer is not enabled for this identity."
    with pytest.raises(ToolError, match="not enabled"):
        await client.call_tool("get_actual_spend", {})


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
    assert res["deleted"] is True and res["action"] == "delete_volume" and res["snapshot_ids"] == ["snap-vol-a-1"] and res["monthly_saving_usd"] == 0.8
    assert res["snapshots"][0]["state"] == "pending"
    assert fake.deleted == ["vol-a"]
    assert fake.snapshots[0][1]["janitor:source"] == "vol-a" and fake.snapshots[0][1]["janitor:plan-id"] == pid

    inst = (await client.call_tool("delete_resource", {"resource_type": "instance", "resource_id": "i-idle", "region": REGION, "plan_id": pid})).data
    assert inst["deleted"] and inst["snapshot_ids"] == ["snap-vol-root-2"]

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

    un = (await client.call_tool("unmark_teardown", {"resource_ids": ["vol-a", "vol-zzz"], "region": REGION, "plan_id": pid})).data
    assert un["unmarked"] == ["vol-a"] and un["skipped_not_in_plan"] == ["vol-zzz"]
    assert "janitor:teardown-after" not in fake.volumes["vol-a"].tags
    with pytest.raises(ToolError, match="expired"):
        await client.call_tool("unmark_teardown", {"resource_ids": ["vol-a"], "region": REGION, "plan_id": "stale"})
    for bad in (0, -3, 91):
        with pytest.raises(ToolError, match="grace_days"):
            await client.call_tool("mark_for_teardown", {"resource_ids": ["vol-a"], "region": REGION, "plan_id": pid, "grace_days": bad})


async def test_snapshot_reused_on_retry_and_ids_survive_delete_failure(client, fake, audit):
    pid = await _plan_id(client)
    fake.fail_delete_once = True
    first = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid})).data
    assert first["deleted"] is False and "RequestLimitExceeded" in first["error"]
    assert first["snapshots"][0]["snapshot_id"] == "snap-vol-a-1"  # restore point reported despite the failure
    assert "vol-a" in fake.volumes
    second = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid})).data
    assert second["deleted"] is True and second["snapshot_ids"] == ["snap-vol-a-1"]  # reused, not duplicated
    assert len(fake.snapshots) == 1
    events = [e["event"] for e in audit.entries]
    assert events.count("delete.requested") == 2 and "delete.failed" in events and "delete.done" in events


async def test_snapshot_inherits_resource_tags(client, fake):
    pid = await _plan_id(client)
    await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid})
    tags = fake.snapshots[0][1]
    assert tags["janitor-demo"] == "true" and tags["janitor:source"] == "vol-a" and tags["janitor:plan-id"] == pid


async def test_wait_for_snapshot_blocks_until_completed(client, fake, monkeypatch):
    pid = await _plan_id(client)
    import cloud_cost_janitor.server.tools.teardown_tools as tt

    monkeypatch.setattr(tt, "SNAPSHOT_POLL_SECONDS", 0)
    polls = {"n": 0}
    real_state = fake.snapshot_state

    def state(region, sid):
        polls["n"] += 1
        if polls["n"] >= 3:
            fake.snapshot_states[sid] = "completed"
        return real_state(region, sid)

    monkeypatch.setattr(fake, "snapshot_state", state)
    res = (await client.call_tool("delete_resource", {"resource_type": "volume", "resource_id": "vol-a", "region": REGION, "plan_id": pid, "wait_for_snapshot": True})).data
    assert res["deleted"] is True and res["snapshots"][0]["state"] == "completed"


async def test_lookback_out_of_range_is_rejected(client):
    with pytest.raises(ToolError, match="lookback_days"):
        await client.call_tool("generate_cost_report", {"instance_lookback_days": 400})


async def test_plan_created_is_audited(client, audit):
    pid = await _plan_id(client)
    created = [e for e in audit.entries if e["event"] == "plan.created"]
    assert created and created[0]["plan_id"] == pid and "i-idle" in created[0]["findings"]
    assert not any(k in json.dumps(audit.entries, default=str) for k in ("AKIA", "arn:aws:iam", "account_id"))
