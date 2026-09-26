---
name: cloud-cost-audit
description: Use when asked to audit cloud spend, find idle or orphaned resources, price waste, draft a teardown plan, or tear down cloud resources with the aws-janitor MCP server. Covers the full loop from scan to approved deletion.
---

# Cloud cost audit and teardown

You have the `aws-janitor` MCP server (scan, plan, gated delete) and, for ad-hoc questions, the read-only
`aws-api` server. Work through the steps below in order. Do not skip the aggregation step: the numbers
you present must come from code you ran, not from mental arithmetic.

## 1. Scan and plan

Call `generate_cost_report` (optionally with `regions`, `instance_lookback_days`, `lb_lookback_days`).
It returns `summary`, `scanned` and `plan` with a `plan_id` valid for one hour.
Keep the `plan_id`; every teardown call needs it.

## 2. Aggregate in the sandbox (Code Mode)

Write a short Python script and run it in the sandbox. It must call `generate_cost_report` through
`mcp_client.call_tool` (do not paste the JSON into the script) and print:

- totals per resource type (count, USD/month),
- totals per confidence level,
- findings sorted by monthly cost, marking protected ones,
- the headline: total estimated waste, recoverable amount, protected count, unpriced count.

`scripts/aggregate_example.py` in this skill shows the shape; adapt it, don't copy blindly. Write the
file in the current working directory (a relative path), then run it with `python3`.

## 3. Present the plan

Show a table with: resource name/id, type, region, evidence (with confidence), estimated USD/month,
protected (with the reason). Use a Generative UI table when there are three or more rows, otherwise
markdown. Then the headline line. State that costs are on-demand list-price estimates and repeat any
`cost_note` caveats briefly.

Call out protected resources explicitly as *not deletable* and never propose them for teardown.

## 4. Ask what to tear down

Ask which unprotected resources to remove. Use a structured question when the choice is not obvious;
offer sensible groupings (all, by type, nothing). Never assume consent from the audit request itself.

## 5. Tear down, one resource per call

For each resource the user named: call `delete_resource(resource_type, resource_id, region, plan_id)`
directly from the conversation, one call per resource, never from a script. Each call pauses for the
user's Allow or Deny. Then report per resource:

| Response | What it means | What to say |
|---|---|---|
| `deleted: true` | removed; `snapshot_ids` are restore points | deleted, snapshot id, monthly saving |
| `refused: true` | server safety check blocked it (stale plan, protected, grace period, state changed) | the `reason`; if the plan expired, re-run `generate_cost_report` and ask again — the new plan needs a fresh approval |
| tool error mentioning `AccessDenied` / `UnauthorizedOperation` | the identity's IAM policy does not allow deleting that resource | say IAM refused it; nothing was changed |
| tool error "User denied tool call" | the user clicked Deny | not deleted, nothing snapshotted; do not retry unless asked |

Never try to work around a refusal or a denial. If a resource is not in the current plan, regenerate the
plan rather than guessing.

## 6. Real spend next to the estimate

When the user asks what the account actually costs, or when presenting a plan for an account that is
not a demo, call `get_actual_spend(days=30)` and show the top services next to the estimated waste
("EC2 compute $412 last 30 days; $58/month of it is idle"). If the tool says Cost Explorer is not
enabled, say exactly that and what the account owner must enable; do not guess a figure.

## 7. Ad-hoc questions

For "what else is in that VPC", "what does this instance run", etc., use `aws-api` (`call_aws` with a
read-only AWS CLI command). Every call there is approval-gated; explain what the command does when it
pauses.

## Tone

Concise and specific. Ids exactly as returned. Money as `$12.34/month`. Estimates are estimates.
