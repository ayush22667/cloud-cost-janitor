# tests
Mirror `src/`. Unit tests for rules/pricing/planner use hand-built `models.py` objects — no AWS, no network.
`providers/` tests use moto (`@mock_aws`) with dummy credentials. `server/` tests use the in-memory FastMCP
client and a fake provider; never the real server on :8000. Run everything with `uv run pytest`.
