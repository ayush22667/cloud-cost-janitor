"""Static AWS on-demand list prices (us-east-1, Linux, USD) for monthly *estimates*.

The IAM user this project runs under is not allowed to call the AWS Pricing API, so prices are a
table. They ignore discounts (Savings Plans, RIs, EDP), regional differences, data transfer and
load-balancer capacity units. Every estimate carries a note saying so.
"""

from __future__ import annotations

HOURS_PER_MONTH = 730  # AWS's own convention for monthly estimates
PRICE_REGION = "us-east-1"

# USD per instance-hour
EC2_HOURLY: dict[str, float] = {
    "t3.nano": 0.0052,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t2.micro": 0.0116,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "c5.2xlarge": 0.34,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
    "r5.2xlarge": 0.504,
}

# USD per GB-month of provisioned EBS storage
EBS_GB_MONTH: dict[str, float] = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}

# USD per load-balancer-hour (base charge only, LCU/NLCU excluded)
LB_HOURLY: dict[str, float] = {
    "application": 0.0225,
    "network": 0.0225,
    "gateway": 0.0125,
    "classic": 0.025,
}


def instance_monthly_cost(instance_type: str) -> float | None:
    """Compute-only monthly cost of a running instance, or None if the type is not in the table."""
    hourly = EC2_HOURLY.get(instance_type)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def volume_monthly_cost(volume_type: str, size_gb: int) -> float | None:
    rate = EBS_GB_MONTH.get(volume_type)
    return None if rate is None else round(rate * size_gb, 2)


def load_balancer_monthly_cost(lb_type: str) -> float | None:
    hourly = LB_HOURLY.get(lb_type)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def cost_note(region: str, *, extra: str = "") -> str:
    """Human-readable caveat attached to every estimate."""
    base = f"On-demand list price ({PRICE_REGION}), no discounts, {HOURS_PER_MONTH} h/month"
    if region != PRICE_REGION:
        base += f"; {region} prices differ slightly"
    return base + (f"; {extra}" if extra else "")
