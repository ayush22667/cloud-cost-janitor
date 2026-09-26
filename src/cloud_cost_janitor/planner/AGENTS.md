# planner
`build_plan(findings) -> TeardownPlan`: orders steps (instances -> load balancers -> volumes), inserts a
mandatory reversible step (snapshot) before every stateful delete, excludes protected findings, sums cost,
and registers the plan under a `plan_id` with a 1-hour TTL. `verify_step()` re-checks a resource against a
fresh `Resource` before deletion. No cloud SDK imports. Tests: `tests/test_planner.py`.
