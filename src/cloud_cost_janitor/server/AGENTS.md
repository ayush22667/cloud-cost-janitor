# server
FastMCP 4 application. `app.py` creates the `FastMCP` instance with bearer auth (`COST_JANITOR_TOKEN`,
constant-time compare) and registers tools from `tools/`. `__main__.py` runs streamable HTTP on
`JANITOR_HOST:JANITOR_PORT` (path `/mcp`). One module per capability in `tools/`; each exposes
`register(mcp, provider)`. Tool docstrings are what the model reads: say what it returns and what it does
NOT do. Annotations are mandatory. Only `teardown_tools.delete_resource` is destructive.
Tests: `tests/server/` using FastMCP's in-memory `Client(transport=mcp)`.
