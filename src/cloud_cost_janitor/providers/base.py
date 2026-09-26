"""The cloud-provider interface. Everything above ``providers/`` depends only on this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from cloud_cost_janitor.models import Instance, LoadBalancer, Volume


class ProviderError(RuntimeError):
    """Raised for provider failures that the caller should surface to the user (permissions, not found)."""


class CloudProvider(ABC):
    """Read resources with utilisation metrics; perform the few write actions the janitor needs.

    Write methods perform the real operation. Deciding *whether* to call them (dry-run, approval,
    protection, tag guard) is the planner's and server's job, not the provider's.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """'aws' | 'gcp' | 'azure'"""

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
