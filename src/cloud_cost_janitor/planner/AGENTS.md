# planner
`build_plan(findings) -> TeardownPlan`: orders steps (instances -> load balancers -> volumes), inserts a
mandatory reversible step (snapshot) before every stateful delete, excludes protected findings, sums cost,
and registers the plan under a `plan_id` with a 1-hour TTL (`PlanRegistry`). `refusal_reason(finding, fresh,
settings)` is the delete-time check: called with a freshly described resource right before deletion, it
returns why the delete must not proceed (gone, protected, still in its grace period, or state changed),
or `None` if it may. No cloud SDK imports. Tests: `tests/test_planner.py`.
