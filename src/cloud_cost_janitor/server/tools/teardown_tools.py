"""Write tools. ``mark_for_teardown``/``unmark_teardown`` are reversible; ``delete_resource`` is destructive.

``delete_resource`` never trusts the plan alone: it re-describes the resource and runs every check in
``planner.refusal_reason`` first, then snapshots anything stateful, then deletes. Snapshots are
idempotent per (volume, plan): a retry reuses the one already taken. If the delete fails after a
snapshot, the result still carries the snapshot ids. Human approval happens in TrueForge before any
of these calls reach the server; which resources the identity may touch at all is enforced by IAM.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cloud_cost_janitor.models import Finding, Instance, ResourceType, Volume
from cloud_cost_janitor.planner import PLAN_TAG, TEARDOWN_AFTER_TAG, find_in_plan, refusal_reason, teardown_after
from cloud_cost_janitor.providers.base import ProviderError
from cloud_cost_janitor.server.context import ServerContext

WRITE_REVERSIBLE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}

GRACE_DAYS_MIN, GRACE_DAYS_MAX = 1, 90
SNAPSHOT_WAIT_MAX_SECONDS = 600
SNAPSHOT_POLL_SECONDS = 5
SOURCE_TAG = "janitor:source"


def _refused(resource_id: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"resource_id": resource_id, "deleted": False, "refused": True, "reason": reason, **extra}


def _fresh(ctx: ServerContext, rtype: ResourceType, region: str, rid: str):
    if rtype == ResourceType.VOLUME:
        return ctx.provider.get_volume(region, rid)
    if rtype == ResourceType.INSTANCE:
        return ctx.provider.get_instance(region, rid)
    return ctx.provider.get_load_balancer(region, rid)


def _snapshot_targets(finding: Finding, fresh) -> list[str]:
    """Volume ids that must be snapshotted before this deletion."""
    if finding.reversible_first_step != "snapshot":
        return []
    if isinstance(fresh, Volume):
        return [fresh.id]
    if isinstance(fresh, Instance):
        return [v.volume_id for v in fresh.attached_volumes]
    return []


def _live_plan(ctx: ServerContext, plan_id: str):
    plan = ctx.plans.get(plan_id)
    if plan is None:
        raise ToolError(f"plan {plan_id!r} not found or expired; run generate_cost_report again")
    return plan


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool(title="Mark for teardown", annotations=WRITE_REVERSIBLE)
    def mark_for_teardown(resource_ids: list[str], region: str, plan_id: str, grace_days: int = 7) -> dict[str, Any]:
        """Two-phase mode: tag resources from a plan with janitor:teardown-after=<date> so delete_resource refuses
        them until the grace period (1-90 days) ends, giving owners time to object. Reversible via unmark_teardown,
        which needs the same plan_id and is also approval-gated. Only resources present in the plan are tagged."""
        if not isinstance(grace_days, int) or not GRACE_DAYS_MIN <= grace_days <= GRACE_DAYS_MAX:
            raise ToolError(f"grace_days must be between {GRACE_DAYS_MIN} and {GRACE_DAYS_MAX}")
        plan = _live_plan(ctx, plan_id)
        in_plan = [rid for rid in resource_ids if find_in_plan(plan, rid, region)]
        skipped = [rid for rid in resource_ids if rid not in in_plan]
        after = teardown_after(datetime.now(timezone.utc), grace_days)
        if in_plan:
            try:
                ctx.provider.tag_resources(region, in_plan, {TEARDOWN_AFTER_TAG: after, PLAN_TAG: plan_id})
            except ProviderError as e:
                raise ToolError(str(e)) from e
        ctx.audit.record("mark", plan_id=plan_id, region=region, marked=in_plan, skipped=skipped, teardown_after=after)
        return {"marked": in_plan, "skipped_not_in_plan": skipped, "teardown_after": after}

    @mcp.tool(title="Unmark teardown", annotations=WRITE_REVERSIBLE)
    def unmark_teardown(resource_ids: list[str], region: str, plan_id: str) -> dict[str, Any]:
        """Remove the janitor:teardown-after marker from resources that are in the given plan (cancels a pending
        two-phase teardown, which makes them deletable again once approved). Requires a live plan_id."""
        plan = _live_plan(ctx, plan_id)
        in_plan = [rid for rid in resource_ids if find_in_plan(plan, rid, region)]
        skipped = [rid for rid in resource_ids if rid not in in_plan]
        if in_plan:
            try:
                ctx.provider.untag_resources(region, in_plan, [TEARDOWN_AFTER_TAG, PLAN_TAG])
            except ProviderError as e:
                raise ToolError(str(e)) from e
        ctx.audit.record("unmark", plan_id=plan_id, region=region, unmarked=in_plan, skipped=skipped)
        return {"unmarked": in_plan, "skipped_not_in_plan": skipped}

    @mcp.tool(title="Delete resource", annotations=DESTRUCTIVE)
    def delete_resource(
        resource_type: str, resource_id: str, region: str, plan_id: str, wait_for_snapshot: bool = False
    ) -> dict[str, Any]:
        """DESTRUCTIVE and irreversible: terminate an instance, delete a volume, or delete a load balancer.
        resource_type is one of "instance", "volume", "load_balancer". The resource must be in the plan identified
        by plan_id (from generate_cost_report, valid one hour). Before acting, the resource is re-described and the
        call is REFUSED if it is protected, inside a grace period, or its state changed (e.g. a volume got attached).
        Stateful resources are snapshotted first (a retry reuses the snapshot already taken); snapshot ids and states
        are returned. AWS completes an in-progress snapshot even after the volume is deleted; pass
        wait_for_snapshot=true to block (up to 10 minutes) until it is completed before deleting. If the delete fails
        after snapshotting, the result still lists the snapshot ids. Call once per resource; never from a script."""
        try:
            rtype = ResourceType(resource_type)
        except ValueError:
            raise ToolError('resource_type must be "instance", "volume" or "load_balancer"') from None

        ctx.audit.record("delete.requested", resource_type=str(rtype), resource_id=resource_id, region=region, plan_id=plan_id)

        def refuse(reason: str) -> dict[str, Any]:
            ctx.audit.record("delete.refused", resource_id=resource_id, region=region, plan_id=plan_id, reason=reason)
            return _refused(resource_id, reason)

        plan = ctx.plans.get(plan_id)
        if plan is None:
            return refuse(f"plan {plan_id!r} not found or expired; run generate_cost_report again")
        finding = find_in_plan(plan, resource_id, region)
        if finding is None or finding.resource_type != rtype:
            return refuse("resource is not part of this plan; run generate_cost_report again")
        if finding.protected:
            return refuse(f"protected by {finding.protection_reason}")

        snapshots: list[dict[str, str]] = []
        try:
            fresh = _fresh(ctx, rtype, region, resource_id)
            reason = refusal_reason(finding, fresh, ctx.settings)
            if reason:
                return refuse(reason)

            inherited = {k: v for k, v in fresh.tags.items() if not k.startswith("aws:")}
            for vid in _snapshot_targets(finding, fresh):
                sid = ctx.provider.find_snapshot(region, vid, plan_id)
                if sid is None:
                    sid = ctx.provider.snapshot_volume(
                        region,
                        vid,
                        description=f"cloud-cost-janitor pre-delete of {resource_id} (plan {plan_id})",
                        tags={**inherited, SOURCE_TAG: vid, PLAN_TAG: plan_id},
                    )
                snapshots.append({"snapshot_id": sid, "volume_id": vid, "state": ctx.provider.snapshot_state(region, sid) or "unknown"})

            if wait_for_snapshot:
                deadline = time.monotonic() + SNAPSHOT_WAIT_MAX_SECONDS
                for snap in snapshots:
                    while snap["state"] != "completed":
                        if snap["state"] == "error":
                            raise ProviderError(f"snapshot {snap['snapshot_id']} failed; not deleting {resource_id}")
                        if time.monotonic() > deadline:
                            raise ProviderError(f"snapshot {snap['snapshot_id']} still {snap['state']} after {SNAPSHOT_WAIT_MAX_SECONDS}s; not deleting {resource_id}")
                        time.sleep(SNAPSHOT_POLL_SECONDS)
                        snap["state"] = ctx.provider.snapshot_state(region, snap["snapshot_id"]) or "unknown"

            if rtype == ResourceType.VOLUME:
                ctx.provider.delete_volume(region, resource_id)
            elif rtype == ResourceType.INSTANCE:
                ctx.provider.terminate_instance(region, resource_id)
            else:
                ctx.provider.delete_load_balancer(region, resource_id)
        except ProviderError as e:
            ctx.audit.record("delete.failed", resource_id=resource_id, region=region, plan_id=plan_id, error=str(e), snapshots=snapshots)
            if snapshots:
                # Never lose the restore points: return them instead of raising.
                return {"resource_id": resource_id, "deleted": False, "error": str(e), "snapshots": snapshots}
            raise ToolError(str(e)) from e

        ctx.audit.record("delete.done", resource_id=resource_id, region=region, plan_id=plan_id, action=str(finding.teardown_action), snapshots=snapshots, monthly_saving_usd=finding.monthly_cost_usd)
        return {
            "resource_id": resource_id,
            "deleted": True,
            "action": str(finding.teardown_action),
            "snapshot_ids": [s["snapshot_id"] for s in snapshots],
            "snapshots": snapshots,
            "monthly_saving_usd": finding.monthly_cost_usd,
        }
