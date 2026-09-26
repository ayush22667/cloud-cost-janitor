"""Actual billed spend from AWS Cost Explorer (``ce:GetCostAndUsage``).

Cost Explorer is global; its endpoint is us-east-1. Each call costs $0.01. The account owner must
enable Cost Explorer once in the console, and enable IAM access to billing data, before this works:
until then AWS answers "User not enabled for cost explorer access".
"""

from __future__ import annotations

from datetime import date, timedelta

from botocore.exceptions import ClientError

from cloud_cost_janitor.providers.base import ProviderError, SpendRow

GROUP_KEYS = {"service": "SERVICE", "region": "REGION", "usage_type": "USAGE_TYPE"}


def actual_spend(clients, *, days: int, group_by: str) -> tuple[str, str, list[SpendRow]]:
    key = GROUP_KEYS.get(group_by)
    if key is None:
        raise ProviderError(f"group_by must be one of {sorted(GROUP_KEYS)}")
    end = date.today()
    start = end - timedelta(days=max(1, min(days, 365)))
    ce = clients._client("ce", "us-east-1")
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": key}],
        )
    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", "")
        if "not enabled for cost explorer" in msg.lower():
            raise ProviderError(
                "Cost Explorer is not enabled for this identity. The account owner must enable Cost Explorer "
                "(Billing > Cost Explorer) and 'IAM user and role access to Billing information' (root user, Account settings)."
            ) from e
        raise
    totals: dict[str, float] = {}
    for period in resp.get("ResultsByTime", []):
        for g in period.get("Groups", []):
            totals[g["Keys"][0]] = totals.get(g["Keys"][0], 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
    rows = sorted((SpendRow(k, v) for k, v in totals.items()), key=lambda r: -r.amount_usd)
    return start.isoformat(), end.isoformat(), rows
