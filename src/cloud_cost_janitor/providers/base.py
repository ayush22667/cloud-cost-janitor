"""The cloud-provider interface. Everything above ``providers/`` depends only on this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from cloud_cost_janitor.models import Instance, LoadBalancer, Volume
from cloud_cost_janitor.pricing import STATIC, PriceBook


class ProviderError(RuntimeError):
    """Raised for provider failures that the caller should surface to the user (permissions, not found)."""


class SpendRow:
    """One line of actual billed spend."""

    __slots__ = ("key", "amount_usd")

    def __init__(self, key: str, amount_usd: float) -> None:
        self.key, self.amount_usd = key, amount_usd

    def to_dict(self) -> dict[str, float | str]:
        return {"key": self.key, "amount_usd": round(self.amount_usd, 2)}


class CloudProvider(ABC):
    """Read resources with utilisation metrics; perform the few write actions the janitor needs.

    Write methods perform the real operation. Deciding *whether* to call them (approval, protection,
    re-verification) is the planner's and server's job, not the provider's.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """'aws' | 'gcp' | 'azure'"""

    @abstractmethod
    def verify_credentials(self) -> None:
        """Raise ProviderError if the configured identity cannot be used. Must not return or log who it is."""

    # --- pricing and billing (optional; defaults keep a provider usable without them) ---
    def price_book(self) -> PriceBook:
        """Unit prices for estimates. Default: the static table."""
        return STATIC

    def actual_spend(self, *, days: int, group_by: str) -> tuple[str, str, list[SpendRow]]:
        """Actual billed spend over the last ``days``: (start_date, end_date, rows). Raise ProviderError if unavailable."""
        raise ProviderError(f"{self.name} provider does not expose billing data")

    # --- discovery ---
    @abstractmethod
    def list_regions(self) -> list[str]: ...

    @abstractmethod
    def list_instances(self, region: str, *, lookback_days: int, now: datetime | None = None) -> list[Instance]:
        """All instances in the region, with utilisation metrics attached for running ones."""

    @abstractmethod
    def list_unattached_volumes(self, region: str) -> list[Volume]: ...

    @abstractmethod
    def list_load_balancers(self, region: str, *, lookback_days: int, now: datetime | None = None) -> list[LoadBalancer]: ...

    # --- re-verification before acting ---
    @abstractmethod
    def get_instance(self, region: str, instance_id: str) -> Instance | None: ...

    @abstractmethod
    def get_volume(self, region: str, volume_id: str) -> Volume | None: ...

    @abstractmethod
    def get_load_balancer(self, region: str, lb_id: str) -> LoadBalancer | None: ...

    # --- reversible actions ---
    @abstractmethod
    def snapshot_volume(self, region: str, volume_id: str, *, description: str, tags: dict[str, str]) -> str:
        """Create a snapshot; return its id."""

    @abstractmethod
    def tag_resources(self, region: str, resource_ids: list[str], tags: dict[str, str]) -> None: ...

    @abstractmethod
    def untag_resources(self, region: str, resource_ids: list[str], keys: list[str]) -> None: ...

    # --- destructive actions ---
    @abstractmethod
    def terminate_instance(self, region: str, instance_id: str) -> None: ...

    @abstractmethod
    def delete_volume(self, region: str, volume_id: str) -> None: ...

    @abstractmethod
    def delete_load_balancer(self, region: str, lb_id: str) -> None: ...
