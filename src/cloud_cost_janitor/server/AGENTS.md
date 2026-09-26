# server
FastMCP 4 application. `app.py` creates the `FastMCP` instance with bearer auth (`COST_JANITOR_TOKEN`,
constant-time compare) and registers tools from `tools/`. `__main__.py` runs streamable HTTP on
`JANITOR_HOST:JANITOR_PORT` (path `/mcp`). One module per capability in `tools/`; each exposes
`register(mcp, ctx)`, where `ctx` is a `ServerContext` (settings, provider, plans, audit, prices).

Ten tools total, only `delete_resource` destructive:
- `scan_tools.py`: `list_regions()`, `find_idle_instances(region, lookback_days=14)`,
  `find_orphaned_volumes(region)`, `find_idle_load_balancers(region, lookback_days=7)`
- `plan_tools.py`: `generate_cost_report(regions=None, instance_lookback_days=14, lb_lookback_days=7)`,
  `get_plan(plan_id)`
- `teardown_tools.py`: `mark_for_teardown(resource_ids, region, plan_id, grace_days=7)`,
  `unmark_teardown(resource_ids, region, plan_id)`,
  `delete_resource(resource_type, resource_id, region, plan_id, wait_for_snapshot=False)`
- `spend_tools.py`: `get_actual_spend(days=30, group_by="service")`

Tool docstrings are what the model reads: say what it returns and what it does NOT do. Annotations are
mandatory.
Tests: `tests/server/` using FastMCP's in-memory `Client(transport=mcp)`.
