"""Provider-agnostic data model.

Everything above ``providers/`` works only with these types. Cloud SDK objects never leave the
provider package. All dataclasses serialise with ``to_dict()`` so MCP tools can return plain JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class ResourceType(StrEnum):
    INSTANCE = "instance"
    VOLUME = "volume"
    LOAD_BALANCER = "load_balancer"


class FindingStatus(StrEnum):
    IDLE = "idle"  # running but unused
    STOPPED = "stopped"  # instance stopped; still paying for its disks
    ORPHANED = "orphaned"  # volume not attached to anything
    UNUSED = "unused"  # load balancer with no healthy targets / no traffic


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TeardownAction(StrEnum):
    TERMINATE_INSTANCE = "terminate_instance"
    DELETE_VOLUME = "delete_volume"
    DELETE_LOAD_BALANCER = "delete_load_balancer"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass
class _Serialisable:
    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


# --- Metrics ---------------------------------------------------------------------------------


@dataclass
class DailyStat(_Serialisable):
    """One day of utilisation for an instance or load balancer."""

    day: date
    cpu_avg_percent: float | None = None
    cpu_max_percent: float | None = None
    network_bytes: int | None = None  # NetworkIn + NetworkOut
    request_count: int | None = None  # load balancers


@dataclass
class UtilisationMetrics(_Serialisable):
    """Daily stats over a lookback window. ``observed_hours`` says how much data actually exists."""

    lookback_days: int
    observed_hours: float
    days: list[DailyStat] = field(default_factory=list)

    @property
    def observed_days(self) -> int:
        return len(self.days)


# --- Resources -------------------------------------------------------------------------------


@dataclass
class Resource(_Serialisable):
    id: str
    name: str
    provider: str  # "aws" | "gcp" | "azure"
    region: str
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None

    @property
    def resource_type(self) -> ResourceType:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass
class AttachedVolume(_Serialisable):
    volume_id: str
    volume_type: str
    size_gb: int
    is_root: bool = False


@dataclass
class Instance(Resource):
    instance_type: str = ""
    state: str = "running"  # running | stopped | ...
    attached_volumes: list[AttachedVolume] = field(default_factory=list)
    metrics: UtilisationMetrics | None = None

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.INSTANCE


@dataclass
class Volume(Resource):
    volume_type: str = ""
    size_gb: int = 0
    state: str = "available"  # available (unattached) | in-use
    attached_instance_id: str | None = None

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.VOLUME


@dataclass
class LoadBalancer(Resource):
    lb_type: str = ""  # application | network | gateway | classic
    registered_targets: int = 0
    healthy_targets: int = 0
    metrics: UtilisationMetrics | None = None

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.LOAD_BALANCER


# --- Findings and plans ----------------------------------------------------------------------


@dataclass
class Finding(_Serialisable):
    """A resource the rules consider wasteful, with the evidence and the cost of keeping it."""

    resource_id: str
    resource_type: ResourceType
    provider: str
    region: str
    name: str
    status: FindingStatus
    reason: str
    evidence: dict[str, Any]
    confidence: Confidence
    monthly_cost_usd: float | None
    cost_note: str
    protected: bool
    protection_reason: str | None
    teardown_action: TeardownAction
    reversible_first_step: str | None  # e.g. "snapshot", None when nothing to preserve


@dataclass
class TeardownStep(_Serialisable):
    order: int
    resource_id: str
    resource_type: ResourceType
    region: str
    action: str  # snapshot | terminate_instance | delete_volume | delete_load_balancer
    reversible: bool
    description: str
    monthly_saving_usd: float | None


@dataclass
class TeardownPlan(_Serialisable):
    plan_id: str
    created_at: datetime
    expires_at: datetime
    regions: list[str]
    findings: list[Finding]
    steps: list[TeardownStep]
    total_monthly_waste_usd: float
    protected_count: int
    unpriced_count: int
