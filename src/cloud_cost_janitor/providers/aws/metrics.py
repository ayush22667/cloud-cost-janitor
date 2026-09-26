"""CloudWatch helpers: hourly datapoints folded into daily stats.

``period=3600`` keeps a 14-day window at 336 datapoints, well under GetMetricStatistics' 1440 limit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from cloud_cost_janitor.models import DailyStat, UtilisationMetrics

PERIOD_SECONDS = 3600
BOOT_EXCLUSION = timedelta(hours=1)  # ignore the launch-time CPU spike


def window(now: datetime, created_at: datetime | None, lookback_days: int) -> tuple[datetime, datetime]:
    """Query window: the last ``lookback_days``, but never before the resource existed (+ boot exclusion)."""
    start = now - timedelta(days=lookback_days)
    if created_at is not None:
        start = max(start, created_at + BOOT_EXCLUSION)
    return start, now


def _stats(cw, namespace: str, metric: str, dims: list[dict], start: datetime, end: datetime, statistics: list[str]):
    if end <= start:
        return []
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=dims,
        StartTime=start,
        EndTime=end,
        Period=PERIOD_SECONDS,
        Statistics=statistics,
    )
    return sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"])


def instance_metrics(cw, instance_id: str, *, now: datetime, launched_at: datetime | None, lookback_days: int) -> UtilisationMetrics:
    start, end = window(now, launched_at, lookback_days)
    dims = [{"Name": "InstanceId", "Value": instance_id}]
    cpu = _stats(cw, "AWS/EC2", "CPUUtilization", dims, start, end, ["Average", "Maximum"])
    net_in = _stats(cw, "AWS/EC2", "NetworkIn", dims, start, end, ["Sum"])
    net_out = _stats(cw, "AWS/EC2", "NetworkOut", dims, start, end, ["Sum"])

    by_day: dict[date, dict] = defaultdict(lambda: {"avg": [], "max": [], "net": 0, "has_net": False})
    for p in cpu:
        d = by_day[p["Timestamp"].date()]
        d["avg"].append(p["Average"])
        d["max"].append(p["Maximum"])
    for p in net_in + net_out:
        d = by_day[p["Timestamp"].date()]
        d["net"] += int(p["Sum"])
        d["has_net"] = True

    days = [
        DailyStat(
            day=day,
            cpu_avg_percent=round(sum(v["avg"]) / len(v["avg"]), 3) if v["avg"] else None,
            cpu_max_percent=round(max(v["max"]), 3) if v["max"] else None,
            network_bytes=v["net"] if v["has_net"] else None,
        )
        for day, v in sorted(by_day.items())
        if v["avg"]  # a day counts only if we have CPU data for it
    ]
    return UtilisationMetrics(lookback_days=lookback_days, observed_hours=float(len(cpu)), days=days)


def load_balancer_metrics(cw, lb_dimension: str, *, now: datetime, created_at: datetime | None, lookback_days: int) -> UtilisationMetrics:
    """Daily RequestCount for an Application Load Balancer (namespace AWS/ApplicationELB)."""
    start, end = window(now, created_at, lookback_days)
    dims = [{"Name": "LoadBalancer", "Value": lb_dimension}]
    points = _stats(cw, "AWS/ApplicationELB", "RequestCount", dims, start, end, ["Sum"])

    by_day: dict[date, int] = defaultdict(int)
    for p in points:
        by_day[p["Timestamp"].date()] += int(p["Sum"])

    # Days with no datapoints served zero requests; enumerate the window so they count.
    days: list[DailyStat] = []
    cursor = start.date()
    while cursor <= end.date():
        days.append(DailyStat(day=cursor, request_count=by_day.get(cursor, 0)))
        cursor += timedelta(days=1)
    observed_hours = max((end - start).total_seconds() / 3600, 0.0)
    return UtilisationMetrics(lookback_days=lookback_days, observed_hours=round(observed_hours, 2), days=days)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
