"""Idle load balancer detection.

AWS Trusted Advisor "Idle Load Balancers": no healthy backend instances, or fewer than 100 requests per
day over the last 7 days. A load balancer with no request datapoints served zero requests.

"No healthy targets" alone is not proof of idleness: redirect-only or fixed-response listeners and Lambda
targets (health checks off by default) serve traffic without a healthy target. So when request metrics
exist they always win: a load balancer at or above the request threshold is never flagged.
"""

from __future__ import annotations

from cloud_cost_janitor import pricing
from cloud_cost_janitor.pricing import STATIC, PriceBook
from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import Confidence, Finding, FindingStatus, LoadBalancer, TeardownAction, UtilisationMetrics
from cloud_cost_janitor.rules.protection import protection_reason

IDLE_MAX_REQUESTS_PER_DAY = 100  # Trusted Advisor
HIGH_CONFIDENCE_MIN_DAYS = 7
MEDIUM_CONFIDENCE_MIN_HOURS = 24.0


def _confidence(m: UtilisationMetrics | None) -> Confidence:
    if m is None:  # no request metrics (network / gateway load balancers): target health is all we have
        return Confidence.HIGH
    if m.observed_days >= HIGH_CONFIDENCE_MIN_DAYS:
        return Confidence.HIGH
    if m.observed_hours >= MEDIUM_CONFIDENCE_MIN_HOURS:
        return Confidence.MEDIUM
    return Confidence.LOW


def evaluate_load_balancer(lb: LoadBalancer, settings: Settings, prices: PriceBook = STATIC) -> Finding | None:
    prot = protection_reason(lb.tags, settings.protected_tags)
    m = lb.metrics
    requests = [d.request_count or 0 for d in m.days] if m else []
    per_day = round(sum(requests) / len(requests), 1) if requests else 0.0
    has_traffic_data = m is not None and m.observed_days > 0

    if has_traffic_data and per_day >= IDLE_MAX_REQUESTS_PER_DAY:
        return None  # serving traffic, whatever the target health says

    if lb.healthy_targets == 0:
        reason = "No healthy targets" + (
            f" ({lb.registered_targets} registered, none healthy)" if lb.registered_targets else " (none registered)"
        )
        if has_traffic_data:
            reason += f"; {per_day:g} requests/day over {m.observed_days} observed day(s)"
        confidence = _confidence(m)
    elif has_traffic_data:
        reason = f"{per_day:g} requests/day over {m.observed_days} observed day(s), below {IDLE_MAX_REQUESTS_PER_DAY}/day"
        confidence = _confidence(m)
    else:
        return None

    return Finding(
        resource_id=lb.id,
        resource_type=lb.resource_type,
        provider=lb.provider,
        region=lb.region,
        name=lb.name,
        status=FindingStatus.UNUSED,
        reason=reason,
        evidence={
            "lb_type": lb.lb_type,
            "registered_targets": lb.registered_targets,
            "healthy_targets": lb.healthy_targets,
            "requests_per_day": per_day,
            "observed_days": m.observed_days if m else 0,
            "observed_hours": round(m.observed_hours, 1) if m else 0.0,
        },
        confidence=confidence,
        monthly_cost_usd=pricing.load_balancer_monthly_cost(prices, lb.region, lb.lb_type),
        cost_note=pricing.cost_note(prices, lb.region, extra="hourly charge only, LCU excluded"),
        protected=prot is not None,
        protection_reason=prot,
        teardown_action=TeardownAction.DELETE_LOAD_BALANCER,
        reversible_first_step=None,  # nothing stateful to preserve
    )
