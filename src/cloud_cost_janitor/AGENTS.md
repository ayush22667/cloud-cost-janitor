# src/cloud_cost_janitor
Provider-agnostic core lives at this level: `models.py` (dataclasses), `pricing.py` (static list prices +
estimate helpers), `config.py` (env-driven settings). Nothing here may import boto3 or any cloud SDK.
Subpackages: `providers/` (cloud adapters), `rules/` (detection), `planner/` (teardown plans), `server/` (MCP).
Tests for this level: `tests/test_pricing.py`, `tests/test_models.py`.
