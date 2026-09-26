"""Actual billed spend, so estimates can be put next to what the account really pays."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cloud_cost_janitor.providers.base import ProviderError
from cloud_cost_janitor.server.context import ServerContext
from cloud_cost_janitor.server.tools.scan_tools import READ_ONLY


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool(title="Get actual spend", annotations=READ_ONLY)
    def get_actual_spend(days: int = 30, group_by: str = "service") -> dict[str, Any]:
        """Actual billed spend for the account over the last `days` (1-365) from the cloud billing API
        (AWS Cost Explorer), grouped by "service", "region" or "usage_type", largest first, in USD.
        Use it to compare the estimated waste from generate_cost_report with real spend. Read-only.
        Fails with an explanation if billing access is not enabled for this identity."""
        try:
            start, end, rows = ctx.provider.actual_spend(days=days, group_by=group_by)
        except ProviderError as e:
            raise ToolError(str(e)) from e
        ctx.audit.record("spend.read", days=days, group_by=group_by, total_usd=round(sum(r.amount_usd for r in rows), 2))
        return {
            "period": {"start": start, "end": end},
            "group_by": group_by,
            "total_usd": round(sum(r.amount_usd for r in rows), 2),
            "rows": [r.to_dict() for r in rows],
            "note": "Unblended cost as billed by AWS; excludes credits and refunds only if AWS does.",
        }
