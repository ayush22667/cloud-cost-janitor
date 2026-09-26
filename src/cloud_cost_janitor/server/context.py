"""Shared state handed to every tool module."""

from __future__ import annotations

from dataclasses import dataclass, field

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.planner import PlanRegistry
from cloud_cost_janitor.providers.base import CloudProvider


@dataclass
class ServerContext:
    settings: Settings
    provider: CloudProvider
    plans: PlanRegistry = field(default_factory=PlanRegistry)
