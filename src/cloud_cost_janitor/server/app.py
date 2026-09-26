"""FastMCP application factory."""

from __future__ import annotations

import hmac

from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.planner import PlanRegistry
from cloud_cost_janitor.providers.base import CloudProvider
from cloud_cost_janitor.server.context import ServerContext
from cloud_cost_janitor.server.tools import plan_tools, scan_tools, teardown_tools

INSTRUCTIONS = (
    "Cloud Cost Janitor: finds idle instances, orphaned volumes and idle load balancers, prices them, and tears "
    "them down safely. Start with generate_cost_report to get findings and a plan_id. delete_resource is the only "
    "destructive tool: it requires a live plan_id, re-verifies the resource, snapshots stateful data first, and is a "
    "dry run unless the server was started with ALLOW_DELETE=true."
)


def create_app(settings: Settings, provider: CloudProvider, registry: PlanRegistry | None = None) -> FastMCP:
    expected = settings.token

    def validate(token: str) -> bool:
        return hmac.compare_digest(token.encode(), expected.encode())

    auth = DebugTokenVerifier(validate=validate, client_id="trueforge")
    mcp = FastMCP(name="aws-janitor", instructions=INSTRUCTIONS, auth=auth)
    ctx = ServerContext(settings=settings, provider=provider, plans=registry or PlanRegistry())
    scan_tools.register(mcp, ctx)
    plan_tools.register(mcp, ctx)
    teardown_tools.register(mcp, ctx)
    return mcp
