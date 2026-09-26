from datetime import datetime, timedelta, timezone

from cloud_cost_janitor.providers.aws.metrics import BOOT_EXCLUSION, window


def test_window_is_clipped_to_resource_age_plus_boot_exclusion():
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    launched = now - timedelta(hours=5)
    start, end = window(now, launched, lookback_days=14)
    assert start == launched + BOOT_EXCLUSION and end == now


def test_window_uses_full_lookback_for_old_resources():
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    start, _ = window(now, now - timedelta(days=90), lookback_days=14)
    assert start == now - timedelta(days=14)


def test_window_without_creation_time():
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    start, _ = window(now, None, lookback_days=7)
    assert start == now - timedelta(days=7)


from cloud_cost_janitor.providers.aws.metrics import MAX_DATAPOINTS, clamp_lookback, period_for


def test_period_keeps_datapoints_under_the_limit():
    assert period_for(14) == 3600 and period_for(60) == 3600
    assert period_for(61) == 7200 and period_for(120) == 7200 and period_for(365) == 3600 * 7
    for days in (1, 14, 60, 61, 120, 365):
        assert days * 24 * 3600 / period_for(days) <= MAX_DATAPOINTS


def test_lookback_bounds():
    assert clamp_lookback(1) == 1 and clamp_lookback(365) == 365
    import pytest
    for bad in (0, -1, 366, "14"):
        with pytest.raises(ValueError):
            clamp_lookback(bad)  # type: ignore[arg-type]
