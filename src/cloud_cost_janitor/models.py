"""Plain data types shared by backends, analysis, and the MCP server."""

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Instance:
    id: str
    region: str
    instance_type: str
    state: str  # running | stopped | ...
    launched_at: datetime
    tags: dict[str, str] = field(default_factory=dict)
    avg_cpu_percent: float | None = None  # over the lookback window; None = no metrics
    max_cpu_percent: float | None = None
    stopped_at: datetime | None = None
    attached_volume_ids: list[str] = field(default_factory=list)


@dataclass
class Volume:
    id: str
    region: str
    volume_type: str
    size_gb: int
    state: str  # available (unattached) | in-use
    created_at: datetime
    tags: dict[str, str] = field(default_factory=dict)
    attached_instance_id: str | None = None


@dataclass
class LoadBalancer:
    id: str  # ARN on AWS
    name: str
    region: str
    lb_type: str  # application | network | gateway | classic
    created_at: datetime
    tags: dict[str, str] = field(default_factory=dict)
    registered_targets: int = 0
    healthy_targets: int = 0
    requests_in_window: int | None = None  # None = no metrics


@dataclass
class Finding:
    resource_id: str
    resource_type: str  # instance | volume | load_balancer
    region: str
    name: str
    reason: str
    evidence: dict
    monthly_cost_usd: float | None
    protected: bool
    protection_reason: str | None
    teardown_action: str
    reversible_first_step: str | None

    def to_dict(self) -> dict:
        return asdict(self)
