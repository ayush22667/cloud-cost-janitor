from cloud_cost_janitor import pricing
from cloud_cost_janitor.pricing import STATIC

R = "us-east-1"


def test_instance_cost_uses_730_hours():
    assert pricing.instance_monthly_cost(STATIC, R, "t3.micro") == round(0.0104 * 730, 2)  # 7.59


def test_unknown_instance_type_is_none_not_zero():
    assert pricing.instance_monthly_cost(STATIC, R, "z9.mega") is None


def test_volume_cost_scales_with_size():
    assert pricing.volume_monthly_cost(STATIC, R, "gp3", 10) == 0.8
    assert pricing.volume_monthly_cost(STATIC, R, "gp3", 100) == 8.0


def test_unknown_volume_type_is_none():
    assert pricing.volume_monthly_cost(STATIC, R, "magnetic-x", 10) is None


def test_load_balancer_cost():
    assert pricing.load_balancer_monthly_cost(STATIC, R, "application") == round(0.0225 * 730, 2)  # 16.43
    assert pricing.load_balancer_monthly_cost(STATIC, R, "nope") is None


def test_static_source_note_flags_other_regions():
    assert "differ" not in STATIC.source(R)
    assert "eu-west-1" in STATIC.source("eu-west-1") and "differ" in STATIC.source("eu-west-1")
    assert pricing.cost_note(STATIC, R, extra="LCU excluded").endswith("LCU excluded")
    assert "730 h/month" in pricing.cost_note(STATIC, R)
