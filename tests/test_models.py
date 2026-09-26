from datetime import date, datetime, timezone

from cloud_cost_janitor.models import (
    Confidence,
    DailyStat,
    Finding,
    FindingStatus,
    Instance,
    LoadBalancer,
    ResourceType,
    TeardownAction,
    UtilisationMetrics,
    Volume,
)


def test_resource_types():
    assert Instance(id="i-1", name="a", provider="aws", region="us-east-1").resource_type == ResourceType.INSTANCE
    assert Volume(id="vol-1", name="b", provider="aws", region="us-east-1").resource_type == ResourceType.VOLUME
    assert (
        LoadBalancer(id="arn:lb", name="c", provider="aws", region="us-east-1").resource_type
        == ResourceType.LOAD_BALANCER
    )


def test_to_dict_is_plain_json():
    metrics = UtilisationMetrics(
        lookback_days=14,
        observed_hours=48.0,
        days=[DailyStat(day=date(2026, 9, 25), cpu_avg_percent=1.5, cpu_max_percent=9.0, network_bytes=1024)],
    )
    inst = Instance(
        id="i-1",
        name="idle-box",
        provider="aws",
        region="us-east-1",
        tags={"janitor-demo": "true"},
        created_at=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        instance_type="t3.micro",
        metrics=metrics,
    )
    d = inst.to_dict()
    assert d["created_at"] == "2026-09-24T12:00:00+00:00"
    assert d["metrics"]["days"][0]["day"] == "2026-09-25"
    assert d["tags"] == {"janitor-demo": "true"}
    assert metrics.observed_days == 1


def test_finding_serialises_enums_as_strings():
    f = Finding(
        resource_id="vol-1",
        resource_type=ResourceType.VOLUME,
        provider="aws",
        region="us-east-1",
        name="vol-1",
        status=FindingStatus.ORPHANED,
        reason="not attached",
        evidence={"state": "available"},
        confidence=Confidence.HIGH,
        monthly_cost_usd=0.8,
        cost_note="list price",
        protected=False,
        protection_reason=None,
        teardown_action=TeardownAction.DELETE_VOLUME,
        reversible_first_step="snapshot",
    )
    d = f.to_dict()
    assert d["status"] == "orphaned"
    assert d["teardown_action"] == "delete_volume"
    assert d["resource_type"] == "volume"
