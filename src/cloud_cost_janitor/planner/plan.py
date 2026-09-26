"""Turn findings into an ordered, reversible-first teardown plan, and re-verify before acting.

Design (see PLAN.md): explicit dependency order rather than retry-until-it-works; a snapshot step is
inserted before every stateful delete; protected findings stay in the report but never become steps;
plans expire so a stale report cannot authorise a deletion hours later.
"""

from __future__ import annotations

import secrets
import threading
from datetime import date, datetime, timedelta, timezone

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import (
    Finding,
    Instance,
    LoadBalancer,
    Resource,
    ResourceType,
    TeardownPlan,
    TeardownStep,
    Volume,
)
from cloud_cost_janitor.rules.protection import protection_reason

# Instances first (they may hold volumes), then load balancers, then volumes.
_ORDER = {ResourceType.INSTANCE: 0, ResourceType.LOAD_BALANCER: 1, ResourceType.VOLUME: 2}

TEARDOWN_AFTER_TAG = "janitor:teardown-after"  # two-phase (mark-then-delete) grace period marker
PLAN_TAG = "janitor:plan-id"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_plan(findings: list[Finding], *, regions: list[str], settings: Settings, now: datetime | None = None) -> TeardownPlan:
    now = now or _utcnow()
    ordered = sorted(findings, key=lambda f: (_ORDER[f.resource_type], -(f.monthly_cost_usd or 0.0), f.resource_id))

    steps: list[TeardownStep] = []
    n = 0
    planned = 0.0
    for f in ordered:
        if f.protected:
            continue
        if f.reversible_first_step == "snapshot":
            n += 1
            steps.append(
                TeardownStep(
                    order=n,
                    resource_id=f.resource_id,
                    resource_type=f.resource_type,
                    region=f.region,
                    action="snapshot",
                    reversible=True,
                    description=f"Snapshot {f.resource_id} ({f.name}) before removal so it can be restored",
                    monthly_saving_usd=None,
                )
            )
        n += 1
        steps.append(
            TeardownStep(
                order=n,
                resource_id=f.resource_id,
                resource_type=f.resource_type,
                region=f.region,
                action=str(f.teardown_action),
                reversible=False,
                description=f"{f.teardown_action.replace('_', ' ').capitalize()} {f.resource_id} ({f.name}): {f.reason}",
                monthly_saving_usd=f.monthly_cost_usd,
            )
        )
        planned += f.monthly_cost_usd or 0.0

    return TeardownPlan(
        plan_id=secrets.token_hex(6),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.plan_ttl_seconds),
        regions=list(regions),
        findings=ordered,
        steps=steps,
        total_monthly_waste_usd=round(sum(f.monthly_cost_usd or 0.0 for f in ordered), 2),
        planned_saving_usd=round(planned, 2),
        protected_count=sum(1 for f in ordered if f.protected),
        unpriced_count=sum(1 for f in ordered if f.monthly_cost_usd is None),
    )


class PlanRegistry:
    """In-memory store of live plans. A server restart forgets them by design."""

    def __init__(self) -> None:
        self._plans: dict[str, TeardownPlan] = {}
        self._lock = threading.Lock()

    def add(self, plan: TeardownPlan) -> None:
        with self._lock:
            self._purge(_utcnow())
            self._plans[plan.plan_id] = plan

    def get(self, plan_id: str, *, now: datetime | None = None) -> TeardownPlan | None:
        now = now or _utcnow()
        with self._lock:
            self._purge(now)
            return self._plans.get(plan_id)

    def _purge(self, now: datetime) -> None:
        for pid in [pid for pid, p in self._plans.items() if p.expires_at <= now]:
            del self._plans[pid]


def find_in_plan(plan: TeardownPlan, resource_id: str, region: str) -> Finding | None:
    return next((f for f in plan.findings if f.resource_id == resource_id and f.region == region), None)


def teardown_after(now: datetime, grace_days: int) -> str:
    """ISO date after which a marked resource may be deleted."""
    return (now + timedelta(days=grace_days)).date().isoformat()


def refusal_reason(finding: Finding, fresh: Resource | None, settings: Settings, *, today: date | None = None) -> str | None:
    """Why a deletion must NOT proceed right now, or None if it may.

    Called immediately before acting, with a freshly described resource, so that anything that changed
    since the plan was built (attachment, traffic, a protect tag, a grace period) blocks the delete.
    """
    today = today or _utcnow().date()
    if fresh is None:
        return "resource no longer exists"

    prot = protection_reason(fresh.tags, settings.protected_tags)
    if prot:
        return f"protected by {prot}"

    if settings.delete_only_tag:
        key, value = settings.delete_only_tag
        if fresh.tags.get(key) != value:
            return f"DELETE_ONLY_TAGGED guard: resource lacks tag {key}={value}"

    marked = fresh.tags.get(TEARDOWN_AFTER_TAG)
    if marked:
        try:
            if date.fromisoformat(marked) > today:
                return f"grace period: marked for teardown after {marked}"
        except ValueError:
            return f"grace period tag {TEARDOWN_AFTER_TAG} has an unreadable date ({marked!r}); fix or remove it first"

    if isinstance(fresh, Volume):
        if fresh.state != "available" or fresh.attached_instance_id:
            return f"volume is now {fresh.state}" + (f", attached to {fresh.attached_instance_id}" if fresh.attached_instance_id else "")
    elif isinstance(fresh, Instance):
        if fresh.state not in {"running", "stopped"}:
            return f"instance is now {fresh.state}"
        if finding.status == "stopped" and fresh.state != "stopped":
            return "instance was stopped when planned but is running now; re-run the audit"
    elif isinstance(fresh, LoadBalancer):
        planned_healthy = int(finding.evidence.get("healthy_targets", 0))
        if fresh.healthy_targets > planned_healthy:
            return f"load balancer now has {fresh.healthy_targets} healthy target(s)"
    return None


__all__ = ["PLAN_TAG", "TEARDOWN_AFTER_TAG", "PlanRegistry", "build_plan", "find_in_plan", "refusal_reason", "teardown_after"]
