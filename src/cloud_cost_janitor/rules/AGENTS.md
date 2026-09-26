# rules
Pure functions: `(resource, metrics, settings) -> Finding | None`. No I/O, no SDK imports, deterministic.
Defaults follow AWS Trusted Advisor: idle instance = daily CPU <= 10% and network <= 5 MB on every observed
day (lookback 14 d, first hour excluded, `confidence` by days observed); orphaned volume = state
`available`; idle load balancer = 0 healthy targets or < 100 requests/day over 7 d (no data = 0).
`protection.py` marks `env=prod`, `Environment=Production`, `janitor:keep=true` as protected.
Every threshold is a named constant with a comment citing the source. Tests: `tests/test_rules.py`.
