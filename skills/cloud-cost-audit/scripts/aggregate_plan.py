#!/usr/bin/env python3
"""Aggregate an aws-janitor teardown plan inside the TrueForge sandbox.

Usage: python3 scripts/aggregate_plan.py <plan_id>

Fetches the plan you already generated through the sandbox's MCP bridge (get_plan is read-only and
never rescans the account) and prints totals per resource type, totals per confidence level, the
findings sorted by monthly cost, and the headline. Only the printed lines reach the model.

Exit codes: 0 printed the summary; 2 bad arguments; 3 the plan could not be fetched (the message says
whether it expired or the bridge is missing).
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict

# The bridge module lives in the sandbox working directory. When this file runs from the skill
# directory, Python puts that directory first on sys.path, so add the working directory explicitly.
sys.path.insert(0, os.getcwd())

try:
    from mcp_client import call_tool
except ImportError:  # pragma: no cover - only reachable outside the sandbox
    print(
        "aggregate_plan.py: cannot import mcp_client. It is only available inside the TrueForge sandbox; "
        "run this script there, from the sandbox working directory.",
        file=sys.stderr,
    )
    sys.exit(3)

CONFIDENCE_ORDER = ("high", "medium", "low")


def money(value: float | None) -> str:
    return f"${value:.2f}/mo" if value is not None else "unpriced"


async def fetch_plan(plan_id: str) -> dict:
    try:
        report = await call_tool("aws-janitor", "get_plan", body={"plan_id": plan_id})
    except Exception as exc:  # noqa: BLE001 - the bridge surfaces the tool error as a plain exception
        text = str(exc)
        hint = " The plan expired or was never created: run generate_cost_report once and use its plan_id." \
            if "plan" in text.lower() else ""
        print(f"aggregate_plan.py: get_plan failed: {text}.{hint}", file=sys.stderr)
        sys.exit(3)
    if "plan" not in report:
        print(f"aggregate_plan.py: unexpected get_plan response keys: {sorted(report)}", file=sys.stderr)
        sys.exit(3)
    return report["plan"]


def print_summary(plan: dict) -> None:
    findings = plan["findings"]
    by_type: dict[str, list[float]] = defaultdict(list)
    by_conf: dict[str, list[float]] = defaultdict(list)
    for f in findings:
        cost = f.get("monthly_cost_usd") or 0.0
        by_type[f["resource_type"]].append(cost)
        by_conf[f["confidence"]].append(cost)

    print("=== Totals per resource type ===")
    for rtype, costs in sorted(by_type.items(), key=lambda kv: -sum(kv[1])):
        print(f"{rtype:<15} {len(costs):>2} resource(s)  ${sum(costs):>8.2f}/mo")

    print("\n=== Totals per confidence ===")
    for conf in CONFIDENCE_ORDER:
        costs = by_conf.get(conf, [])
        print(f"{conf:<8} {len(costs):>2} resource(s)  ${sum(costs):>8.2f}/mo")

    print("\n=== Findings by cost ===")
    for f in sorted(findings, key=lambda f: -(f.get("monthly_cost_usd") or 0.0)):
        flag = f" PROTECTED ({f['protection_reason']})" if f["protected"] else ""
        print(
            f"- {f['resource_id']} {f['name']} [{f['resource_type']}, {f['region']}, {f['confidence']}] "
            f"{money(f.get('monthly_cost_usd'))}: {f['reason']}{flag}"
        )

    print(
        f"\nHEADLINE: {money(plan['total_monthly_waste_usd'])} estimated waste, "
        f"{money(plan['planned_saving_usd'])} recoverable via {len(plan['steps'])} step(s); "
        f"{plan['protected_count']} protected, {plan['unpriced_count']} unpriced. plan_id={plan['plan_id']}"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    plan = asyncio.run(fetch_plan(argv[1].strip()))
    print_summary(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
