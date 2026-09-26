from datetime import date, datetime, timedelta, timezone

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import (
    Confidence,
    Finding,
    FindingStatus,
    Instance,
    LoadBalancer,
    ResourceType,
    TeardownAction,
    Volume,
)
from cloud_cost_janitor.planner import PlanRegistry, build_plan, find_in_plan, refusal_reason, teardown_after

S = Settings(token="t", plan_ttl_seconds=60)
NOW = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def finding(rid, rtype, action, cost, *, protected=False, snapshot=True, status=FindingStatus.IDLE, evidence=None) -> Finding:
    return Finding(
        resource_id=rid,
        resource_type=rtype,
        provider="aws",
        region="us-east-1",
        name=rid,
        status=status,
        reason="test",
        evidence=evidence or {},
        confidence=Confidence.HIGH,
        monthly_cost_usd=cost,
        cost_note="",
        protected=protected,
        protection_reason="tag env=prod" if protected else None,
        teardown_action=action,
        reversible_first_step="snapshot" if snapshot else None,
    )


def sample_findings():
    return [
        finding("vol-cheap", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 0.8),
        finding("i-idle", ResourceType.INSTANCE, TeardownAction.TERMINATE_INSTANCE, 7.59),
        finding("arn:lb", ResourceType.LOAD_BALANCER, TeardownAction.DELETE_LOAD_BALANCER, 16.43, snapshot=False),
        finding("vol-big", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 8.0),
        finding("i-prod", ResourceType.INSTANCE, TeardownAction.TERMINATE_INSTANCE, 70.08, protected=True),
        finding("vol-nopr", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, None),
    ]


def test_plan_orders_instances_then_lbs_then_volumes_by_cost():
    plan = build_plan(sample_findings(), regions=["us-east-1"], settings=S, now=NOW)
    ids = [f.resource_id for f in plan.findings]
    assert ids == ["i-prod", "i-idle", "arn:lb", "vol-big", "vol-cheap", "vol-nopr"]


def test_snapshot_step_precedes_every_stateful_delete_and_protected_is_excluded():
    plan = build_plan(sample_findings(), regions=["us-east-1"], settings=S, now=NOW)
    actions = [(s.resource_id, s.action, s.reversible) for s in plan.steps]
    assert actions == [
        ("i-idle", "snapshot", True),
        ("i-idle", "terminate_instance", False),
        ("arn:lb", "delete_load_balancer", False),
        ("vol-big", "snapshot", True),
        ("vol-big", "delete_volume", False),
        ("vol-cheap", "snapshot", True),
        ("vol-cheap", "delete_volume", False),
        ("vol-nopr", "snapshot", True),
        ("vol-nopr", "delete_volume", False),
    ]
    assert [s.order for s in plan.steps] == list(range(1, 10))
    assert "i-prod" not in {s.resource_id for s in plan.steps}


def test_plan_totals():
    plan = build_plan(sample_findings(), regions=["us-east-1"], settings=S, now=NOW)
    assert plan.total_monthly_waste_usd == round(0.8 + 7.59 + 16.43 + 8.0 + 70.08, 2)
    assert plan.planned_saving_usd == round(0.8 + 7.59 + 16.43 + 8.0, 2)
    assert plan.protected_count == 1 and plan.unpriced_count == 1
    assert plan.expires_at == NOW + timedelta(seconds=60)
    assert len(plan.plan_id) == 12


def test_registry_expires_plans():
    reg = PlanRegistry()
    plan = build_plan(sample_findings(), regions=["us-east-1"], settings=S, now=NOW)
    reg.add(plan)
    assert reg.get(plan.plan_id, now=NOW + timedelta(seconds=59)) is plan
    assert reg.get(plan.plan_id, now=NOW + timedelta(seconds=61)) is None
    assert reg.get("nope", now=NOW) is None


def test_find_in_plan_matches_id_and_region():
    plan = build_plan(sample_findings(), regions=["us-east-1"], settings=S, now=NOW)
    assert find_in_plan(plan, "vol-big", "us-east-1").resource_id == "vol-big"
    assert find_in_plan(plan, "vol-big", "eu-west-1") is None


def test_teardown_after_date():
    assert teardown_after(NOW, 7) == "2026-10-03"


# --- refusal_reason ---------------------------------------------------------------------------

TAG = {"janitor-demo": "true"}
TODAY = date(2026, 9, 26)


def vol(**kw) -> Volume:
    base = dict(id="vol-1", name="v", provider="aws", region="us-east-1", tags=dict(TAG), volume_type="gp3", size_gb=1, state="available")
    base.update(kw)
    return Volume(**base)


def test_refuses_when_gone_protected_or_untagged():
    f = finding("vol-1", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 0.8)
    assert refusal_reason(f, None, S, today=TODAY) == "resource no longer exists"
    assert "protected" in refusal_reason(f, vol(tags={"janitor-demo": "true", "env": "prod"}), S, today=TODAY)
    assert "DELETE_ONLY_TAGGED" in refusal_reason(f, vol(tags={}), S, today=TODAY)


def test_guard_can_be_disabled():
    f = finding("vol-1", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 0.8)
    assert refusal_reason(f, vol(tags={}), Settings(token="t", delete_only_tag=None), today=TODAY) is None


def test_refuses_volume_that_got_attached():
    f = finding("vol-1", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 0.8)
    assert "attached to i-9" in refusal_reason(f, vol(state="in-use", attached_instance_id="i-9"), S, today=TODAY)
    assert refusal_reason(f, vol(), S, today=TODAY) is None


def test_grace_period_blocks_until_date():
    f = finding("vol-1", ResourceType.VOLUME, TeardownAction.DELETE_VOLUME, 0.8)
    future = vol(tags={**TAG, "janitor:teardown-after": "2026-10-03"})
    past = vol(tags={**TAG, "janitor:teardown-after": "2026-09-20"})
    bad = vol(tags={**TAG, "janitor:teardown-after": "soon"})
    assert "grace period" in refusal_reason(f, future, S, today=TODAY)
    assert refusal_reason(f, past, S, today=TODAY) is None
    assert "unreadable" in refusal_reason(f, bad, S, today=TODAY)


def test_instance_and_lb_reverification():
    fi = finding("i-1", ResourceType.INSTANCE, TeardownAction.TERMINATE_INSTANCE, 7.59, status=FindingStatus.STOPPED)
    running = Instance(id="i-1", name="i", provider="aws", region="us-east-1", tags=dict(TAG), state="running")
    stopped = Instance(id="i-1", name="i", provider="aws", region="us-east-1", tags=dict(TAG), state="stopped")
    assert "running now" in refusal_reason(fi, running, S, today=TODAY)
    assert refusal_reason(fi, stopped, S, today=TODAY) is None

    fl = finding("arn:lb", ResourceType.LOAD_BALANCER, TeardownAction.DELETE_LOAD_BALANCER, 16.43, snapshot=False, evidence={"healthy_targets": 0})
    busy = LoadBalancer(id="arn:lb", name="lb", provider="aws", region="us-east-1", tags=dict(TAG), healthy_targets=2)
    idle = LoadBalancer(id="arn:lb", name="lb", provider="aws", region="us-east-1", tags=dict(TAG), healthy_targets=0)
    assert "healthy target" in refusal_reason(fl, busy, S, today=TODAY)
    assert refusal_reason(fl, idle, S, today=TODAY) is None
