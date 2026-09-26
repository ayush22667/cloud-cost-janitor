from cloud_cost_janitor import pricing


def test_instance_cost_uses_730_hours():
    assert pricing.instance_monthly_cost("t3.micro") == round(0.0104 * 730, 2)  # 7.59


def test_unknown_instance_type_is_none_not_zero():
    assert pricing.instance_monthly_cost("z9.mega") is None


def test_volume_cost_scales_with_size():
    assert pricing.volume_monthly_cost("gp3", 10) == 0.8
    assert pricing.volume_monthly_cost("gp3", 100) == 8.0


def test_unknown_volume_type_is_none():
    assert pricing.volume_monthly_cost("magnetic-x", 10) is None


def test_load_balancer_cost():
    assert pricing.load_balancer_monthly_cost("application") == round(0.0225 * 730, 2)  # 16.43
    assert pricing.load_balancer_monthly_cost("nope") is None


def test_cost_note_mentions_region_difference_only_when_needed():
    assert "differ" not in pricing.cost_note("us-east-1")
    assert "eu-west-1 prices differ" in pricing.cost_note("eu-west-1")
    assert pricing.cost_note("us-east-1", extra="LCU excluded").endswith("LCU excluded")
