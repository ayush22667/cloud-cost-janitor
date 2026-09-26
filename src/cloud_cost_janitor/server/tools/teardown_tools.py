"""Write tools. ``mark_for_teardown`` is reversible; ``delete_resource`` is the only destructive tool.

``delete_resource`` never trusts the plan alone: it re-describes the resource and runs every check in
``planner.refusal_reason`` first, snapshots anything stateful, and does nothing at all in dry-run mode.
"""

from __future__ import annotations

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


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool(title="Mark for teardown", annotations=WRITE_REVERSIBLE)
    def mark_for_teardown(resource_ids: list[str], region: str, plan_id: str, grace_days: int = 7) -> dict[str, Any]:
        """Two-phase mode: tag resources from a plan with janitor:teardown-after=<date> so delete_resource refuses
        them until the grace period ends, giving owners time to object. Reversible via unmark_teardown.
        Only resources present in the given plan are tagged."""
        plan = ctx.plans.get(plan_id)
        if plan is None:
            raise ToolError(f"plan {plan_id!r} not found or expired; run generate_cost_report again")
        in_plan = [rid for rid in resource_ids if find_in_plan(plan, rid, region)]
        skipped = [rid for rid in resource_ids if rid not in in_plan]
        after = teardown_after(datetime.now(timezone.utc), grace_days)
        if in_plan and not ctx.settings.dry_run:
            try:
                ctx.provider.tag_resources(region, in_plan, {TEARDOWN_AFTER_TAG: after, PLAN_TAG: plan_id})
            except ProviderError as e:
                raise ToolError(str(e)) from e
        return {"marked": in_plan, "skipped_not_in_plan": skipped, "teardown_after": after, "dry_run": ctx.settings.dry_run}

    @mcp.tool(title="Unmark teardown", annotations=WRITE_REVERSIBLE)
    def unmark_teardown(resource_ids: list[str], region: str) -> dict[str, Any]:
        """Remove the janitor:teardown-after marker from resources (cancels a pending two-phase teardown)."""
        if not ctx.settings.dry_run:
            try:
                ctx.provider.untag_resources(region, resource_ids, [TEARDOWN_AFTER_TAG, PLAN_TAG])
            except ProviderError as e:
                raise ToolError(str(e)) from e
        return {"unmarked": resource_ids, "dry_run": ctx.settings.dry_run}

    @mcp.tool(title="Delete resource", annotations=DESTRUCTIVE)
    def delete_resource(resource_type: str, resource_id: str, region: str, plan_id: str) -> dict[str, Any]:
        """DESTRUCTIVE and irreversible: terminate an instance, delete a volume, or delete a load balancer.
        resource_type is one of "instance", "volume", "load_balancer". The resource must be in the plan identified
        by plan_id (from generate_cost_report, valid one hour). Before acting, the resource is re-described and the
        call is REFUSED if it is protected, lacks the required tag, is inside a grace period, or its state changed
        (e.g. a volume got attached). Stateful resources are snapshotted first; snapshot ids are returned.
        In dry-run mode (ALLOW_DELETE unset) nothing is changed and the response says dry_run=true.
        Call this once per resource; never from a script."""
        try:
            rtype = ResourceType(resource_type)
        except ValueError:
            raise ToolError('resource_type must be "instance", "volume" or "load_balancer"') from None

        plan = ctx.plans.get(plan_id)
        if plan is None:
            return _refused(resource_id, f"plan {plan_id!r} not found or expired; run generate_cost_report again")
        finding = find_in_plan(plan, resource_id, region)
        if finding is None or finding.resource_type != rtype:
            return _refused(resource_id, "resource is not part of this plan; run generate_cost_report again")
        if finding.protected:
            return _refused(resource_id, f"protected by {finding.protection_reason}")

        try:
            fresh = _fresh(ctx, rtype, region, resource_id)
            reason = refusal_reason(finding, fresh, ctx.settings)
            if reason:
                return _refused(resource_id, reason)

            snapshot_ids = _snapshot_targets(finding, fresh)
            actions = [f"snapshot {v}" for v in snapshot_ids] + [f"{finding.teardown_action} {resource_id}"]
            if ctx.settings.dry_run:
                return {
                    "resource_id": resource_id,
                    "deleted": False,
                    "dry_run": True,
                    "would_do": actions,
                    "monthly_saving_usd": finding.monthly_cost_usd,
                    "note": "ALLOW_DELETE is not enabled on the server; nothing was changed",
                }

            created: list[str] = []
            for vid in snapshot_ids:
                created.append(
                    ctx.provider.snapshot_volume(
                        region,
                        vid,
                        description=f"cloud-cost-janitor pre-delete of {resource_id} (plan {plan_id})",
                        tags={"janitor:source": resource_id, PLAN_TAG: plan_id},
                    )
                )
            if rtype == ResourceType.VOLUME:
                ctx.provider.delete_volume(region, resource_id)
            elif rtype == ResourceType.INSTANCE:
                ctx.provider.terminate_instance(region, resource_id)
            else:
                ctx.provider.delete_load_balancer(region, resource_id)
        except ProviderError as e:
            raise ToolError(str(e)) from e

        return {
            "resource_id": resource_id,
            "deleted": True,
            "dry_run": False,
            "action": str(finding.teardown_action),
            "snapshot_ids": created,
            "monthly_saving_usd": finding.monthly_cost_usd,
        }
