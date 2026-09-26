"""Full scan -> teardown plan with a plan_id that authorises later teardown calls."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cloud_cost_janitor.planner import build_plan
from cloud_cost_janitor.providers.base import ProviderError
from cloud_cost_janitor.rules import evaluate_all
from cloud_cost_janitor.server.context import ServerContext
from cloud_cost_janitor.server.tools.scan_tools import READ_ONLY


def _summary(plan) -> str:
    n = len(plan.findings)
    return (
        f"{n} wasteful resource(s) across {', '.join(plan.regions)}: "
        f"${plan.total_monthly_waste_usd:,.2f}/month estimated waste, "
        f"${plan.planned_saving_usd:,.2f}/month recoverable via {len(plan.steps)} step(s); "
        f"{plan.protected_count} protected, {plan.unpriced_count} unpriced."
    )


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool(title="Generate cost report", annotations=READ_ONLY)
    def generate_cost_report(
        regions: list[str] | None = None,
        instance_lookback_days: int = 14,
        lb_lookback_days: int = 7,
    ) -> dict[str, Any]:
        """Scan the given regions (default: configured AWS_REGIONS) for idle instances, orphaned volumes and idle
        load balancers, price them, and return a TeardownPlan: ordered steps with a reversible snapshot before every
        stateful delete, totals, and a plan_id valid for one hour. The plan_id is REQUIRED by mark_for_teardown and
        delete_resource. Read-only; nothing is changed."""
        target = list(regions or ctx.settings.regions)
        findings = []
        scanned: dict[str, int] = {"instances": 0, "unattached_volumes": 0, "load_balancers": 0}
        try:
            for region in target:
                instances = ctx.provider.list_instances(region, lookback_days=instance_lookback_days)
                volumes = ctx.provider.list_unattached_volumes(region)
                lbs = ctx.provider.list_load_balancers(region, lookback_days=lb_lookback_days)
                scanned["instances"] += len(instances)
                scanned["unattached_volumes"] += len(volumes)
                scanned["load_balancers"] += len(lbs)
                findings.extend(evaluate_all([*instances, *volumes, *lbs], ctx.settings, ctx.prices))
        except ProviderError as e:
            raise ToolError(str(e)) from e

        plan = build_plan(findings, regions=target, settings=ctx.settings)
        ctx.plans.add(plan)
        return {
            "summary": _summary(plan),
            "scanned": scanned,
            "plan": plan.to_dict(),
        }

    @mcp.tool(title="Get plan", annotations=READ_ONLY)
    def get_plan(plan_id: str) -> dict[str, Any]:
        """Return a previously generated plan by plan_id, or an error if it expired (plans live one hour;
        re-run generate_cost_report to get a fresh one). Read-only."""
        plan = ctx.plans.get(plan_id)
        if plan is None:
            raise ToolError(f"plan {plan_id!r} not found or expired; run generate_cost_report again")
        return {"summary": _summary(plan), "plan": plan.to_dict()}
