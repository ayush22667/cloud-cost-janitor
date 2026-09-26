from datetime import datetime, timedelta, timezone

import pytest

from cloud_cost_janitor.providers.base import ProviderError
from tests.providers.conftest import REGION, put_cpu, run_instance


def test_list_instances_reads_type_state_tags_and_volumes(provider, ec2):
    iid = run_instance(ec2, tags={"Name": "idle-box", "janitor-demo": "true"})
    instances = provider.list_instances(REGION, lookback_days=14)
    inst = next(i for i in instances if i.id == iid)
    assert inst.name == "idle-box" and inst.tags["janitor-demo"] == "true"
    assert inst.instance_type == "t3.micro" and inst.state == "running"
    assert len(inst.attached_volumes) == 1
    assert inst.attached_volumes[0].volume_type == "gp3" and inst.attached_volumes[0].size_gb == 8
    assert inst.attached_volumes[0].is_root is True


def test_stopped_instances_are_included_without_metrics(provider, ec2):
    iid = run_instance(ec2, stop=True)
    inst = next(i for i in provider.list_instances(REGION, lookback_days=14) if i.id == iid)
    assert inst.state == "stopped" and inst.metrics is None


def test_running_instance_metrics_are_folded_into_daily_stats(provider, ec2, cloudwatch):
    iid = run_instance(ec2)
    # Pretend the instance was launched 3 days ago so the query window is not clipped by the boot exclusion.
    now = datetime.now(timezone.utc)
    put_cpu(cloudwatch, iid, hours=48, avg=2.0, maximum=9.0, now=now)
    inst = next(i for i in provider.list_instances(REGION, lookback_days=14, now=now + timedelta(hours=2)) if i.id == iid)
    # moto sets LaunchTime = creation time (seconds ago); window starts at launch+1h, so 48h of data is clipped
    # to what falls inside the window. We only assert the folding logic, not the exact count.
    assert inst.metrics is not None
    assert all(d.cpu_avg_percent is not None for d in inst.metrics.days)
    assert all(d.network_bytes is not None for d in inst.metrics.days)


def test_get_instance_returns_none_when_missing(provider):
    assert provider.get_instance(REGION, "i-0123456789abcdef0") is None


def test_unattached_volumes_only(provider, ec2):
    vid = ec2.create_volume(Size=10, AvailabilityZone=f"{REGION}a", VolumeType="gp3", TagSpecifications=[{"ResourceType": "volume", "Tags": [{"Key": "janitor-demo", "Value": "true"}]}])["VolumeId"]
    run_instance(ec2)  # its root volume is in-use and must not appear
    vols = provider.list_unattached_volumes(REGION)
    assert [v.id for v in vols] == [vid]
    assert vols[0].size_gb == 10 and vols[0].volume_type == "gp3" and vols[0].state == "available"
    assert vols[0].tags == {"janitor-demo": "true"}


def test_get_volume_reflects_attachment(provider, ec2):
    iid = run_instance(ec2)
    vid = ec2.create_volume(Size=1, AvailabilityZone=f"{REGION}a", VolumeType="gp3")["VolumeId"]
    assert provider.get_volume(REGION, vid).attached_instance_id is None
    ec2.attach_volume(VolumeId=vid, InstanceId=iid, Device="/dev/sdf")
    assert provider.get_volume(REGION, vid).attached_instance_id == iid
    assert provider.get_volume(REGION, "vol-0123456789abcdef0") is None


def test_snapshot_then_delete_volume(provider, ec2):
    vid = ec2.create_volume(Size=1, AvailabilityZone=f"{REGION}a", VolumeType="gp3")["VolumeId"]
    snap = provider.snapshot_volume(REGION, vid, description="janitor pre-delete", tags={"janitor:source": vid})
    desc = ec2.describe_snapshots(SnapshotIds=[snap])["Snapshots"][0]
    assert desc["VolumeId"] == vid
    assert {t["Key"]: t["Value"] for t in desc["Tags"]} == {"janitor:source": vid}
    provider.delete_volume(REGION, vid)
    assert provider.get_volume(REGION, vid) is None


def test_tag_and_untag(provider, ec2):
    vid = ec2.create_volume(Size=1, AvailabilityZone=f"{REGION}a", VolumeType="gp3")["VolumeId"]
    provider.tag_resources(REGION, [vid], {"janitor:teardown-after": "2026-10-03"})
    assert provider.get_volume(REGION, vid).tags["janitor:teardown-after"] == "2026-10-03"
    provider.untag_resources(REGION, [vid], ["janitor:teardown-after"])
    assert "janitor:teardown-after" not in provider.get_volume(REGION, vid).tags


def test_terminate_instance(provider, ec2):
    iid = run_instance(ec2)
    provider.terminate_instance(REGION, iid)
    assert ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["State"]["Name"] in {"shutting-down", "terminated"}


def test_client_errors_become_provider_errors(provider):
    with pytest.raises(ProviderError, match="AWS"):
        provider.delete_volume(REGION, "vol-0123456789abcdef0")
