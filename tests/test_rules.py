from datetime import date, timedelta

import pytest

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import (
    AttachedVolume,
    Confidence,
    DailyStat,
    FindingStatus,
    Instance,
    LoadBalancer,
    UtilisationMetrics,
    Volume,
)
from cloud_cost_janitor.rules import evaluate, evaluate_all
from cloud_cost_janitor.rules.idle_instance import evaluate_instance
from cloud_cost_janitor.rules.idle_load_balancer import evaluate_load_balancer
from cloud_cost_janitor.rules.unattached_volume import evaluate_volume

SETTINGS = Settings(token="t")
D0 = date(2026, 9, 20)


def days(n: int, cpu: float = 1.0, net: int = 1000, cpu_max: float = 5.0) -> list[DailyStat]:
    return [
        DailyStat(day=D0 + timedelta(days=i), cpu_avg_percent=cpu, cpu_max_percent=cpu_max, network_bytes=net)
        for i in range(n)
    ]


def instance(**kw) -> Instance:
    base = dict(id="i-1", name="box", provider="aws", region="us-east-1", instance_type="t3.micro", state="running")
    base.update(kw)
    return Instance(**base)


# --- instances -------------------------------------------------------------------------------


def test_idle_instance_high_confidence_after_four_days():
    inst = instance(metrics=UtilisationMetrics(lookback_days=14, observed_hours=96, days=days(4)))
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.status == FindingStatus.IDLE and f.confidence == Confidence.HIGH
    assert f.monthly_cost_usd == 7.59
    assert f.evidence["observed_days"] == 4


def test_idle_instance_low_confidence_when_seeded_today():
    inst = instance(metrics=UtilisationMetrics(lookback_days=14, observed_hours=3.0, days=days(1)))
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.confidence == Confidence.LOW


def test_busy_instance_is_not_flagged():
    inst = instance(metrics=UtilisationMetrics(lookback_days=14, observed_hours=96, days=days(4, cpu=35.0)))
    assert evaluate_instance(inst, SETTINGS) is None


def test_one_busy_day_disqualifies():
    m = days(4)
    m[2].network_bytes = 50 * 1024 * 1024  # 50 MB
    inst = instance(metrics=UtilisationMetrics(lookback_days=14, observed_hours=96, days=m))
    assert evaluate_instance(inst, SETTINGS) is None


def test_no_metrics_means_no_finding():
    assert evaluate_instance(instance(metrics=None), SETTINGS) is None
    assert evaluate_instance(instance(metrics=UtilisationMetrics(14, 0.0, [])), SETTINGS) is None


def test_idle_cost_includes_attached_volumes():
    inst = instance(
        attached_volumes=[AttachedVolume("vol-r", "gp3", 20, is_root=True)],
        metrics=UtilisationMetrics(lookback_days=14, observed_hours=96, days=days(4)),
    )
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.monthly_cost_usd == round(7.59 + 1.6, 2) and f.reversible_first_step == "snapshot"


def test_stopped_instance_costs_only_ebs():
    inst = instance(state="stopped", attached_volumes=[AttachedVolume("vol-r", "gp3", 30, is_root=True)])
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.status == FindingStatus.STOPPED and f.monthly_cost_usd == 2.4 and f.confidence == Confidence.HIGH


def test_unknown_instance_type_has_no_price_but_is_still_reported():
    inst = instance(instance_type="z9.mega", metrics=UtilisationMetrics(14, 96, days(4)))
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.monthly_cost_usd is None


def test_protected_tag_is_reported_not_hidden():
    inst = instance(tags={"env": "prod"}, metrics=UtilisationMetrics(14, 96, days(4)))
    f = evaluate_instance(inst, SETTINGS)
    assert f and f.protected and f.protection_reason == "tag env=prod"


# --- volumes ---------------------------------------------------------------------------------


def test_unattached_volume_is_orphaned():
    v = Volume(id="vol-1", name="vol-1", provider="aws", region="us-east-1", volume_type="gp3", size_gb=10, state="available")
    f = evaluate_volume(v, SETTINGS)
    assert f and f.status == FindingStatus.ORPHANED and f.monthly_cost_usd == 0.8 and f.reversible_first_step == "snapshot"


def test_attached_volume_is_not_flagged():
    v = Volume(id="vol-1", name="vol-1", provider="aws", region="us-east-1", volume_type="gp3", size_gb=10, state="in-use", attached_instance_id="i-1")
    assert evaluate_volume(v, SETTINGS) is None


# --- load balancers --------------------------------------------------------------------------


def lb(**kw) -> LoadBalancer:
    base = dict(id="arn:lb/1", name="lb-1", provider="aws", region="us-east-1", lb_type="application")
    base.update(kw)
    return LoadBalancer(**base)


def test_lb_with_no_healthy_targets_is_unused():
    f = evaluate_load_balancer(lb(registered_targets=0, healthy_targets=0), SETTINGS)
    assert f and f.status == FindingStatus.UNUSED and f.confidence == Confidence.HIGH and f.monthly_cost_usd == 16.43
    assert f.reversible_first_step is None


def test_lb_with_low_traffic_is_unused_with_confidence_by_days():
    m = UtilisationMetrics(7, 48.0, [DailyStat(D0 + timedelta(days=i), request_count=10) for i in range(2)])
    f = evaluate_load_balancer(lb(registered_targets=2, healthy_targets=2, metrics=m), SETTINGS)
    assert f and f.confidence == Confidence.MEDIUM and f.evidence["requests_per_day"] == 10


def test_lb_with_traffic_is_fine():
    m = UtilisationMetrics(7, 168.0, [DailyStat(D0 + timedelta(days=i), request_count=5000) for i in range(7)])
    assert evaluate_load_balancer(lb(registered_targets=2, healthy_targets=2, metrics=m), SETTINGS) is None


def test_lb_with_healthy_targets_and_no_metrics_is_not_flagged():
    assert evaluate_load_balancer(lb(registered_targets=2, healthy_targets=2, metrics=None), SETTINGS) is None


# --- dispatcher ------------------------------------------------------------------------------


def test_evaluate_all_dispatches_and_filters():
    resources = [
        instance(metrics=UtilisationMetrics(14, 96, days(4))),
        Volume(id="vol-1", name="v", provider="aws", region="us-east-1", volume_type="gp3", size_gb=10, state="in-use"),
        lb(healthy_targets=0),
    ]
    findings = evaluate_all(resources, SETTINGS)
    assert [f.resource_id for f in findings] == ["i-1", "arn:lb/1"]


def test_evaluate_rejects_unknown_type():
    with pytest.raises(TypeError):
        evaluate(object(), SETTINGS)  # type: ignore[arg-type]


def test_protection_is_case_insensitive():
    for tags in ({"Environment": "production"}, {"ENV": "PROD"}, {"janitor:KEEP": "True"}):
        f = evaluate_instance(instance(tags=tags, metrics=UtilisationMetrics(14, 96, days(4))), SETTINGS)
        assert f and f.protected, tags
