# rules
Pure functions: `(resource, metrics, settings) -> Finding | None`. No I/O, no SDK imports, deterministic.
Defaults follow AWS Trusted Advisor: idle instance = daily CPU <= 10% and network <= 5 MB on every observed
day (lookback 14 d, first hour excluded, `confidence` by days observed); orphaned volume = state
`available`.

Idle load balancer: an application load balancer with 0 healthy targets is flagged unless its request
count over the window is at or above 100/day (a redirect-only listener or Lambda targets can serve real
traffic with no healthy targets to show for it); a target in state `unavailable` or `initial` counts as
healthy, since it is not proven idle. An application load balancer with healthy targets is flagged if it
served under 100 requests/day over 7 d (no datapoints counts as 0). Non-application load balancers
(network/gateway/classic) have no request metrics, so they are judged on healthy targets alone.

`protection.py` marks `env=prod`, `Environment=Production`, `janitor:keep=true` as protected, matched
case-insensitively on both key and value.
Every threshold is a named constant with a comment citing the source. Tests: `tests/test_rules.py`.
