"""Detection rules: pure functions from a resource to an optional Finding."""

from __future__ import annotations

from collections.abc import Iterable

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.models import Finding, Instance, LoadBalancer, Resource, Volume
from cloud_cost_janitor.pricing import STATIC, PriceBook
from cloud_cost_janitor.rules.idle_instance import evaluate_instance
from cloud_cost_janitor.rules.idle_load_balancer import evaluate_load_balancer
from cloud_cost_janitor.rules.unattached_volume import evaluate_volume


def evaluate(resource: Resource, settings: Settings, prices: PriceBook = STATIC) -> Finding | None:
    if isinstance(resource, Instance):
        return evaluate_instance(resource, settings, prices)
    if isinstance(resource, Volume):
        return evaluate_volume(resource, settings, prices)
    if isinstance(resource, LoadBalancer):
        return evaluate_load_balancer(resource, settings, prices)
    raise TypeError(f"no rule for {type(resource).__name__}")


def evaluate_all(resources: Iterable[Resource], settings: Settings, prices: PriceBook = STATIC) -> list[Finding]:
    return [f for f in (evaluate(r, settings, prices) for r in resources) if f is not None]


__all__ = ["evaluate", "evaluate_all", "evaluate_instance", "evaluate_load_balancer", "evaluate_volume"]
