"""Idle / stopped instance detection.

Thresholds follow AWS Trusted Advisor "Low Utilization Amazon EC2 Instances":
daily CPU <= 10 % and daily network I/O <= 5 MB, on at least 4 of the last 14 days.
(https://github.com/aws/Trusted-Advisor-Tools/blob/master/LowUtilizationEC2Instances/README.md)

We require *every observed day* to be under both thresholds and report how much data existed, so a
resource launched hours ago is still flagged, but with low confidence.
"""

from __future__ import annotations

from cloud_cost_janitor import pricing
from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import Confidence, Finding, FindingStatus, Instance, TeardownAction
from cloud_cost_janitor.rules.protection import protection_reason

IDLE_CPU_MAX_DAILY_AVG_PERCENT = 10.0  # Trusted Advisor
IDLE_NETWORK_MAX_DAILY_BYTES = 5 * 1024 * 1024  # 5 MB, Trusted Advisor
HIGH_CONFIDENCE_MIN_DAYS = 4  # Trusted Advisor: >= 4 of last 14 days
MEDIUM_CONFIDENCE_MIN_HOURS = 24.0


def _attached_volume_cost(inst: Instance) -> tuple[float, bool]:
    """Sum of attached EBS cost; second value is True if any volume type was unpriced."""
    total, unpriced = 0.0, False
    for vol in inst.attached_volumes:
        cost = pricing.volume_monthly_cost(vol.volume_type, vol.size_gb)
        if cost is None:
            unpriced = True
        else:
            total += cost
    return round(total, 2), unpriced


def _confidence(observed_days: int, observed_hours: float) -> Confidence:
    if observed_days >= HIGH_CONFIDENCE_MIN_DAYS:
        return Confidence.HIGH
    if observed_hours >= MEDIUM_CONFIDENCE_MIN_HOURS:
        return Confidence.MEDIUM
    return Confidence.LOW


def evaluate_instance(inst: Instance, settings: Settings) -> Finding | None:
    """Return a Finding for a stopped or idle instance, else None."""
    prot = protection_reason(inst.tags, settings.protected_tags)
    ebs_cost, ebs_unpriced = _attached_volume_cost(inst)

    if inst.state == "stopped":
        return Finding(
            resource_id=inst.id,
            resource_type=inst.resource_type,
            provider=inst.provider,
            region=inst.region,
            name=inst.name,
            status=FindingStatus.STOPPED,
            reason="Instance is stopped; its attached volumes are still billed",
            evidence={
                "state": inst.state,
                "instance_type": inst.instance_type,
                "attached_volumes": [v.to_dict() for v in inst.attached_volumes],
            },
            confidence=Confidence.HIGH,
            monthly_cost_usd=None if ebs_unpriced and ebs_cost == 0 else ebs_cost,
            cost_note=pricing.cost_note(inst.region, extra="stopped: EBS storage only"),
            protected=prot is not None,
            protection_reason=prot,
            teardown_action=TeardownAction.TERMINATE_INSTANCE,
            reversible_first_step="snapshot" if inst.attached_volumes else None,
        )

    if inst.state != "running":
        return None

    m = inst.metrics
    if m is None or m.observed_days == 0:
        return None  # no evidence either way

    over = []
    for day in m.days:
        cpu_ok = day.cpu_avg_percent is not None and day.cpu_avg_percent <= IDLE_CPU_MAX_DAILY_AVG_PERCENT
        net_ok = day.network_bytes is None or day.network_bytes <= IDLE_NETWORK_MAX_DAILY_BYTES
        if not (cpu_ok and net_ok):
            over.append(day.day.isoformat())
    if over:
        return None

    cpu_avgs = [d.cpu_avg_percent for d in m.days if d.cpu_avg_percent is not None]
    cpu_maxes = [d.cpu_max_percent for d in m.days if d.cpu_max_percent is not None]
    net = [d.network_bytes for d in m.days if d.network_bytes is not None]
    compute_cost = pricing.instance_monthly_cost(inst.instance_type)
    total_cost = None if compute_cost is None else round(compute_cost + ebs_cost, 2)

    return Finding(
        resource_id=inst.id,
        resource_type=inst.resource_type,
        provider=inst.provider,
        region=inst.region,
        name=inst.name,
        status=FindingStatus.IDLE,
        reason=(
            f"CPU avg <= {IDLE_CPU_MAX_DAILY_AVG_PERCENT:g}% and network <= 5 MB/day on all "
            f"{m.observed_days} observed day(s) of a {m.lookback_days}-day window"
        ),
        evidence={
            "instance_type": inst.instance_type,
            "lookback_days": m.lookback_days,
            "observed_days": m.observed_days,
            "observed_hours": round(m.observed_hours, 1),
            "cpu_avg_percent": round(sum(cpu_avgs) / len(cpu_avgs), 2) if cpu_avgs else None,
            "cpu_max_percent": round(max(cpu_maxes), 2) if cpu_maxes else None,
            "network_bytes_per_day": round(sum(net) / len(net)) if net else None,
            "attached_volumes": [v.to_dict() for v in inst.attached_volumes],
        },
        confidence=_confidence(m.observed_days, m.observed_hours),
        monthly_cost_usd=total_cost,
        cost_note=pricing.cost_note(inst.region, extra="compute + attached EBS"),
        protected=prot is not None,
        protection_reason=prot,
        teardown_action=TeardownAction.TERMINATE_INSTANCE,
        reversible_first_step="snapshot" if inst.attached_volumes else None,
    )
