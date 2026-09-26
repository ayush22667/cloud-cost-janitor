"""Monthly cost estimates.

Prices come from a ``PriceBook``. ``StaticPriceBook`` is a table of AWS on-demand list prices for
us-east-1 and is the fallback; ``providers/aws/prices.py`` provides a live book backed by the AWS
Price List API. Every estimate says which source it used. Estimates ignore discounts (Savings Plans,
RIs, EDP), load-balancer capacity units and data transfer.
"""

from __future__ import annotations

from typing import Protocol

HOURS_PER_MONTH = 730  # AWS's own convention for monthly estimates
STATIC_REGION = "us-east-1"

# USD per instance-hour, Linux, shared tenancy, on-demand
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

# USD per load-balancer-hour (base charge only)
LB_HOURLY: dict[str, float] = {
    "application": 0.0225,
    "network": 0.0225,
    "gateway": 0.0125,
    "classic": 0.025,
}


class PriceBook(Protocol):
    """Unit prices by region. Return None when a price is unknown; never guess."""

    def instance_hourly(self, region: str, instance_type: str) -> float | None: ...
    def volume_gb_month(self, region: str, volume_type: str) -> float | None: ...
    def lb_hourly(self, region: str, lb_type: str) -> float | None: ...
    def source(self, region: str) -> str: ...


class StaticPriceBook:
    """List prices for us-east-1 from the tables above, used for any region."""

    def instance_hourly(self, region: str, instance_type: str) -> float | None:
        return EC2_HOURLY.get(instance_type)

    def volume_gb_month(self, region: str, volume_type: str) -> float | None:
        return EBS_GB_MONTH.get(volume_type)

    def lb_hourly(self, region: str, lb_type: str) -> float | None:
        return LB_HOURLY.get(lb_type)

    def source(self, region: str) -> str:
        note = f"static {STATIC_REGION} list price"
        return note if region == STATIC_REGION else note + f" (used for {region}; real prices differ slightly)"


STATIC = StaticPriceBook()


def instance_monthly_cost(book: PriceBook, region: str, instance_type: str) -> float | None:
    """Compute-only monthly cost of a running instance, or None if the type is unknown."""
    hourly = book.instance_hourly(region, instance_type)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def volume_monthly_cost(book: PriceBook, region: str, volume_type: str, size_gb: int) -> float | None:
    rate = book.volume_gb_month(region, volume_type)
    return None if rate is None else round(rate * size_gb, 2)


def load_balancer_monthly_cost(book: PriceBook, region: str, lb_type: str) -> float | None:
    hourly = book.lb_hourly(region, lb_type)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def cost_note(book: PriceBook, region: str, *, extra: str = "") -> str:
    """Human-readable caveat attached to every estimate."""
    base = f"{book.source(region)}, on-demand, no discounts, {HOURS_PER_MONTH} h/month"
    return base + (f"; {extra}" if extra else "")
