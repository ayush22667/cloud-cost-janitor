"""Read-only discovery tools. Each scans one region and returns findings as JSON."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cloud_cost_janitor.providers.base import ProviderError
from cloud_cost_janitor.rules import evaluate_all
from cloud_cost_janitor.server.context import ServerContext

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


def _guard(fn):
    try:
        return fn()
    except ProviderError as e:
        raise ToolError(str(e)) from e


def _pack(region: str, kind: str, scanned: int, findings) -> dict[str, Any]:
    return {
        "region": region,
        "scanned": {kind: scanned},
        "finding_count": len(findings),
        "findings": [f.to_dict() for f in findings],
    }


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool(title="List regions", annotations=READ_ONLY)
    def list_regions() -> dict[str, Any]:
        """List the cloud regions configured for scanning (AWS_REGIONS) and all regions the account can use.
        Returns {"provider", "configured", "available"}. Does not scan anything."""
        return _guard(
            lambda: {
                "provider": ctx.provider.name,
                "configured": list(ctx.settings.regions),
                "available": ctx.provider.list_regions(),
            }
        )

    @mcp.tool(title="Find idle instances", annotations=READ_ONLY)
    def find_idle_instances(region: str, lookback_days: int = 14) -> dict[str, Any]:
        """Find compute instances that are stopped, or running with daily CPU <= 10% and network <= 5 MB on every
        observed day of the lookback window (AWS Trusted Advisor thresholds). Returns findings with evidence,
        confidence (low when the instance is younger than a day) and an estimated monthly cost in USD.
        Read-only. Use generate_cost_report for a full multi-resource scan with a plan_id."""
        def run():
            instances = ctx.provider.list_instances(region, lookback_days=lookback_days)
            return _pack(region, "instances", len(instances), evaluate_all(instances, ctx.settings, ctx.prices))

        return _guard(run)

    @mcp.tool(title="Find orphaned volumes", annotations=READ_ONLY)
    def find_orphaned_volumes(region: str) -> dict[str, Any]:
        """Find block-storage volumes that are not attached to any instance (state "available") and still billed.
        Returns findings with size, type and estimated monthly cost. Read-only."""
        def run():
            volumes = ctx.provider.list_unattached_volumes(region)
            return _pack(region, "unattached_volumes", len(volumes), evaluate_all(volumes, ctx.settings, ctx.prices))

        return _guard(run)

    @mcp.tool(title="Find idle load balancers", annotations=READ_ONLY)
    def find_idle_load_balancers(region: str, lookback_days: int = 7) -> dict[str, Any]:
        """Find load balancers with no healthy targets, or fewer than 100 requests/day over the lookback window.
        Returns findings with target counts, requests/day and estimated monthly cost (hourly charge only). Read-only."""
        def run():
            lbs = ctx.provider.list_load_balancers(region, lookback_days=lookback_days)
            return _pack(region, "load_balancers", len(lbs), evaluate_all(lbs, ctx.settings, ctx.prices))

        return _guard(run)
