"""Reference aggregation for the cloud-cost-audit skill (runs inside the TrueForge sandbox).

Calls generate_cost_report through the sandbox's MCP bridge and prints totals. Adapt as needed; write
your own version rather than running this file unchanged.
"""

import asyncio
from collections import defaultdict

from mcp_client import call_tool


async def main() -> None:
    report = await call_tool("aws-janitor", "generate_cost_report", body={"regions": ["us-east-1"]})
    plan = report["plan"]
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
    for conf in ("high", "medium", "low"):
        costs = by_conf.get(conf, [])
        print(f"{conf:<8} {len(costs):>2} resource(s)  ${sum(costs):>8.2f}/mo")

    print("\n=== Findings by cost ===")
    for f in sorted(findings, key=lambda f: -(f.get("monthly_cost_usd") or 0.0)):
        cost = f.get("monthly_cost_usd")
        cost_s = f"${cost:.2f}/mo" if cost is not None else "unpriced"
        flag = f" PROTECTED ({f['protection_reason']})" if f["protected"] else ""
        print(f"- {f['name']} [{f['resource_type']}, {f['confidence']}] {cost_s}: {f['reason']}{flag}")

    print(
        f"\nHEADLINE: ${plan['total_monthly_waste_usd']:.2f}/mo estimated waste, "
        f"${plan['planned_saving_usd']:.2f}/mo recoverable via {len(plan['steps'])} step(s); "
        f"{plan['protected_count']} protected, {plan['unpriced_count']} unpriced. plan_id={plan['plan_id']}"
    )


asyncio.run(main())
