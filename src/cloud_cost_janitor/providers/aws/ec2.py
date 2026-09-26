"""EC2 instances and EBS volumes."""

from __future__ import annotations

from datetime import datetime

from cloud_cost_janitor.models import AttachedVolume, Instance, Volume
from cloud_cost_janitor.providers.aws.client import AwsClients
from cloud_cost_janitor.providers.aws.metrics import instance_metrics, utcnow


def _tags(raw: list[dict] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (raw or [])}


# Error codes AWS uses when a resource id is unknown or malformed. Any of these means "does not exist".
_NOT_FOUND_CODES = {
    "InvalidInstanceID.NotFound",
    "InvalidInstanceID.Malformed",
    "InvalidVolume.NotFound",
    "InvalidVolumeID.Malformed",
    "InvalidParameterValue",
}


def _is_not_found(err: Exception) -> bool:
    code = getattr(err, "response", {}).get("Error", {}).get("Code", "")
    return code in _NOT_FOUND_CODES


def _name(tags: dict[str, str], fallback: str) -> str:
    return tags.get("Name") or fallback


def _describe_volumes(ec2, volume_ids: list[str]) -> dict[str, dict]:
    if not volume_ids:
        return {}
    out: dict[str, dict] = {}
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(VolumeIds=volume_ids):
        for v in page["Volumes"]:
            out[v["VolumeId"]] = v
    return out


def _instance_from_api(raw: dict, region: str, volumes: dict[str, dict]) -> Instance:
    tags = _tags(raw.get("Tags"))
    root_dev = raw.get("RootDeviceName")
    attached: list[AttachedVolume] = []
    for bdm in raw.get("BlockDeviceMappings", []):
        vid = bdm.get("Ebs", {}).get("VolumeId")
        if not vid:
            continue
        v = volumes.get(vid, {})
        attached.append(
            AttachedVolume(
                volume_id=vid,
                volume_type=v.get("VolumeType", "unknown"),
                size_gb=int(v.get("Size", 0)),
                is_root=bdm.get("DeviceName") == root_dev,
            )
        )
    return Instance(
        id=raw["InstanceId"],
        name=_name(tags, raw["InstanceId"]),
        provider="aws",
        region=region,
        tags=tags,
        created_at=raw.get("LaunchTime"),
        instance_type=raw.get("InstanceType", ""),
        state=raw.get("State", {}).get("Name", "unknown"),
        attached_volumes=attached,
    )


def list_instances(clients: AwsClients, region: str, *, lookback_days: int, now: datetime | None = None) -> list[Instance]:
    now = now or utcnow()
    ec2 = clients.ec2(region)
    raw_instances: list[dict] = []
    for page in ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}]
    ):
        for res in page["Reservations"]:
            raw_instances.extend(res["Instances"])

    vol_ids = [b["Ebs"]["VolumeId"] for i in raw_instances for b in i.get("BlockDeviceMappings", []) if "Ebs" in b]
    volumes = _describe_volumes(ec2, vol_ids)

    cw = clients.cloudwatch(region)
    result: list[Instance] = []
    for raw in raw_instances:
        inst = _instance_from_api(raw, region, volumes)
        if inst.state == "running":
            inst.metrics = instance_metrics(cw, inst.id, now=now, launched_at=inst.created_at, lookback_days=lookback_days)
        result.append(inst)
    return result


def get_instance(clients: AwsClients, region: str, instance_id: str) -> Instance | None:
    ec2 = clients.ec2(region)
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
    except ec2.exceptions.ClientError as e:  # type: ignore[attr-defined]
        if _is_not_found(e):
            return None
        raise
    raws = [i for r in resp["Reservations"] for i in r["Instances"]]
    if not raws:
        return None
    vol_ids = [b["Ebs"]["VolumeId"] for b in raws[0].get("BlockDeviceMappings", []) if "Ebs" in b]
    return _instance_from_api(raws[0], region, _describe_volumes(ec2, vol_ids))


def _volume_from_api(raw: dict, region: str) -> Volume:
    tags = _tags(raw.get("Tags"))
    attachments = raw.get("Attachments") or []
    return Volume(
        id=raw["VolumeId"],
        name=_name(tags, raw["VolumeId"]),
        provider="aws",
        region=region,
        tags=tags,
        created_at=raw.get("CreateTime"),
        volume_type=raw.get("VolumeType", ""),
        size_gb=int(raw.get("Size", 0)),
        state=raw.get("State", ""),
        attached_instance_id=attachments[0].get("InstanceId") if attachments else None,
    )


def list_unattached_volumes(clients: AwsClients, region: str) -> list[Volume]:
    ec2 = clients.ec2(region)
    out: list[Volume] = []
    for page in ec2.get_paginator("describe_volumes").paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        out.extend(_volume_from_api(v, region) for v in page["Volumes"])
    return out


def get_volume(clients: AwsClients, region: str, volume_id: str) -> Volume | None:
    ec2 = clients.ec2(region)
    try:
        resp = ec2.describe_volumes(VolumeIds=[volume_id])
    except ec2.exceptions.ClientError as e:  # type: ignore[attr-defined]
        if _is_not_found(e):
            return None
        raise
    vols = resp.get("Volumes", [])
    return _volume_from_api(vols[0], region) if vols else None


def snapshot_volume(clients: AwsClients, region: str, volume_id: str, *, description: str, tags: dict[str, str]) -> str:
    ec2 = clients.ec2(region)
    resp = ec2.create_snapshot(
        VolumeId=volume_id,
        Description=description[:255],
        TagSpecifications=[{"ResourceType": "snapshot", "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}],
    )
    return resp["SnapshotId"]


def tag_resources(clients: AwsClients, region: str, resource_ids: list[str], tags: dict[str, str]) -> None:
    if resource_ids and tags:
        clients.ec2(region).create_tags(Resources=resource_ids, Tags=[{"Key": k, "Value": v} for k, v in tags.items()])


def untag_resources(clients: AwsClients, region: str, resource_ids: list[str], keys: list[str]) -> None:
    if resource_ids and keys:
        clients.ec2(region).delete_tags(Resources=resource_ids, Tags=[{"Key": k} for k in keys])


def terminate_instance(clients: AwsClients, region: str, instance_id: str) -> None:
    clients.ec2(region).terminate_instances(InstanceIds=[instance_id])


def delete_volume(clients: AwsClients, region: str, volume_id: str) -> None:
    clients.ec2(region).delete_volume(VolumeId=volume_id)
