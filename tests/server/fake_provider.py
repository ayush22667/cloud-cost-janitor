"""In-memory CloudProvider for server tests: records every write, never touches a network."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from cloud_cost_janitor.models import (
    AttachedVolume,
    DailyStat,
    Instance,
    LoadBalancer,
    UtilisationMetrics,
    Volume,
)
from cloud_cost_janitor.providers.base import CloudProvider, ProviderError

REGION = "us-east-1"
NOW = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def idle_days(n: int) -> list[DailyStat]:
    return [DailyStat(day=date(2026, 9, 20) + timedelta(days=i), cpu_avg_percent=0.5, cpu_max_percent=3.0, network_bytes=2048) for i in range(n)]


class FakeProvider(CloudProvider):
    def __init__(self) -> None:
        self.instances: dict[str, Instance] = {
            "i-idle": Instance(
                id="i-idle", name="idle-box", provider="aws", region=REGION, tags={"janitor-demo": "true"},
                created_at=NOW - timedelta(days=10), instance_type="t3.micro", state="running",
                attached_volumes=[AttachedVolume("vol-root", "gp3", 8, is_root=True)],
                metrics=UtilisationMetrics(14, 96.0, idle_days(4)),
            ),
            "i-prod": Instance(
                id="i-prod", name="prod-db", provider="aws", region=REGION, tags={"env": "prod"},
                created_at=NOW - timedelta(days=100), instance_type="m5.large", state="running",
                metrics=UtilisationMetrics(14, 336.0, idle_days(14)),
            ),
        }
        self.volumes: dict[str, Volume] = {
            "vol-a": Volume(id="vol-a", name="vol-a", provider="aws", region=REGION, tags={"janitor-demo": "true"}, volume_type="gp3", size_gb=10, state="available"),
            "vol-b": Volume(id="vol-b", name="vol-b", provider="aws", region=REGION, tags={"janitor-demo": "true"}, volume_type="gp3", size_gb=10, state="available"),
            "vol-untagged": Volume(id="vol-untagged", name="vol-untagged", provider="aws", region=REGION, tags={}, volume_type="gp2", size_gb=5, state="available"),
        }
        self.lbs: dict[str, LoadBalancer] = {
            "arn:lb/empty": LoadBalancer(id="arn:lb/empty", name="empty-alb", provider="aws", region=REGION, tags={"janitor-demo": "true"}, lb_type="application", registered_targets=0, healthy_targets=0),
        }
        self.snapshots: list[tuple[str, dict[str, str]]] = []
        self.tags_written: list[tuple[list[str], dict[str, str]]] = []
        self.deleted: list[str] = []
        self.fail_with: str | None = None

    @property
    def name(self) -> str:
        return "aws"

    def verify_credentials(self) -> None:
        self._maybe_fail()

    def _maybe_fail(self):
        if self.fail_with:
            raise ProviderError(self.fail_with)

    def list_regions(self):
        return [REGION, "ap-south-1"]

    def list_instances(self, region, *, lookback_days, now=None):
        self._maybe_fail()
        return [i for i in self.instances.values() if i.region == region]

    def list_unattached_volumes(self, region):
        return [v for v in self.volumes.values() if v.region == region and v.state == "available"]

    def list_load_balancers(self, region, *, lookback_days, now=None):
        return [l for l in self.lbs.values() if l.region == region]

    def get_instance(self, region, instance_id):
        return self.instances.get(instance_id)

    def get_volume(self, region, volume_id):
        return self.volumes.get(volume_id)

    def get_load_balancer(self, region, lb_id):
        return self.lbs.get(lb_id)

    def snapshot_volume(self, region, volume_id, *, description, tags):
        sid = f"snap-{volume_id}"
        self.snapshots.append((sid, tags))
        return sid

    def tag_resources(self, region, resource_ids, tags):
        self.tags_written.append((resource_ids, tags))
        for rid in resource_ids:
            for store in (self.instances, self.volumes, self.lbs):
                if rid in store:
                    store[rid].tags.update(tags)

    def untag_resources(self, region, resource_ids, keys):
        for rid in resource_ids:
            for store in (self.instances, self.volumes, self.lbs):
                if rid in store:
                    for k in keys:
                        store[rid].tags.pop(k, None)

    def terminate_instance(self, region, instance_id):
        self.deleted.append(instance_id)
        self.instances.pop(instance_id, None)

    def delete_volume(self, region, volume_id):
        self.deleted.append(volume_id)
        self.volumes.pop(volume_id, None)

    def delete_load_balancer(self, region, lb_id):
        self.deleted.append(lb_id)
        self.lbs.pop(lb_id, None)
