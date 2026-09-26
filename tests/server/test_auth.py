"""HTTP-level auth: the in-memory client bypasses transport auth, so drive the ASGI app with httpx."""

import httpx

from tests.server.conftest import TOKEN

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


async def _post(mcp, extra_headers: dict[str, str] | None = None) -> int:
    """Build the app, run its lifespan and send one initialize request, all in the current task."""
    app = mcp.http_app(path="/mcp")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/mcp", json=INIT, headers={**HEADERS, **(extra_headers or {})})
            return r.status_code


async def test_missing_token_is_401(mcp):
    assert await _post(mcp) == 401


async def test_wrong_token_is_401(mcp):
    assert await _post(mcp, {"authorization": "Bearer nope"}) == 401


async def test_right_token_initialises(mcp):
    assert await _post(mcp, {"authorization": f"Bearer {TOKEN}"}) == 200
