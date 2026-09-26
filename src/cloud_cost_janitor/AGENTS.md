# src/cloud_cost_janitor
Provider-agnostic core lives at this level: `models.py` (dataclasses), `pricing.py` (`PriceBook`
protocol, the static us-east-1 fallback table, estimate helpers; live prices come from
`providers/aws/prices.py`), `config.py` (env-driven settings). Nothing here may import boto3 or any cloud SDK.
Subpackages: `providers/` (cloud adapters), `rules/` (detection), `planner/` (teardown plans), `server/` (MCP).
Tests for this level: `tests/test_pricing.py`, `tests/test_models.py`.
