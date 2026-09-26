"""Shared state handed to every tool module."""

from __future__ import annotations

from dataclasses import dataclass, field

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.planner import PlanRegistry
from cloud_cost_janitor.pricing import PriceBook
from cloud_cost_janitor.providers.base import CloudProvider
from cloud_cost_janitor.server.audit import AuditLog


@dataclass
class ServerContext:
    settings: Settings
    provider: CloudProvider
    plans: PlanRegistry = field(default_factory=PlanRegistry)
    audit: AuditLog = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.audit is None:
            self.audit = AuditLog(self.settings.audit_log)

    @property
    def prices(self) -> PriceBook:
        return self.provider.price_book()
