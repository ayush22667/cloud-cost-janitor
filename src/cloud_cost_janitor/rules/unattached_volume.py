"""Orphaned volume detection: a volume in state ``available`` is attached to nothing and still billed.

Matches AWS Trusted Advisor "Underutilized Amazon EBS Volumes" (unattached case). The
low-IOPS-while-attached case is intentionally not implemented: deleting an attached volume is never safe
to automate.
"""

from __future__ import annotations

from cloud_cost_janitor import pricing
from cloud_cost_janitor.pricing import STATIC, PriceBook
from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import Confidence, Finding, FindingStatus, TeardownAction, Volume
from cloud_cost_janitor.rules.protection import protection_reason

UNATTACHED_STATE = "available"


def evaluate_volume(vol: Volume, settings: Settings, prices: PriceBook = STATIC) -> Finding | None:
    if vol.state != UNATTACHED_STATE or vol.attached_instance_id:
        return None
    prot = protection_reason(vol.tags, settings.protected_tags)
    return Finding(
        resource_id=vol.id,
        resource_type=vol.resource_type,
        provider=vol.provider,
        region=vol.region,
        name=vol.name,
        status=FindingStatus.ORPHANED,
        reason="Volume is not attached to any instance",
        evidence={"state": vol.state, "volume_type": vol.volume_type, "size_gb": vol.size_gb},
        confidence=Confidence.HIGH,
        monthly_cost_usd=pricing.volume_monthly_cost(prices, vol.region, vol.volume_type, vol.size_gb),
        cost_note=pricing.cost_note(prices, vol.region, extra="storage only"),
        protected=prot is not None,
        protection_reason=prot,
        teardown_action=TeardownAction.DELETE_VOLUME,
        reversible_first_step="snapshot",
    )
