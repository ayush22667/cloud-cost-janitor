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
