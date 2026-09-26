import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from cloud_cost_janitor.providers.aws.client import AwsClients
from cloud_cost_janitor.providers.aws.provider import AwsProvider

REGION = "us-east-1"
AMI = "ami-12345678"  # moto accepts any id


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def mocked_aws():
    with mock_aws():
        yield


@pytest.fixture
def provider(mocked_aws) -> AwsProvider:
    return AwsProvider(AwsClients())


@pytest.fixture
def ec2(mocked_aws):
    return boto3.client("ec2", region_name=REGION)


@pytest.fixture
def elbv2(mocked_aws):
    return boto3.client("elbv2", region_name=REGION)


@pytest.fixture
def cloudwatch(mocked_aws):
    return boto3.client("cloudwatch", region_name=REGION)


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


def run_instance(ec2, *, instance_type="t3.micro", tags=None, stop=False) -> str:
    spec = [{"ResourceType": "instance", "Tags": [{"Key": k, "Value": v} for k, v in (tags or {}).items()]}] if tags else []
    resp = ec2.run_instances(
        ImageId=AMI,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=spec,
        BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 8, "VolumeType": "gp3"}}],
    )
    iid = resp["Instances"][0]["InstanceId"]
    if stop:
        ec2.stop_instances(InstanceIds=[iid])
    return iid


def put_cpu(cloudwatch, instance_id: str, *, hours: int, avg: float, maximum: float, now: datetime) -> None:
    """Write hourly CPUUtilization + Network datapoints ending at ``now``."""
    data = []
    for h in range(hours):
        ts = now - timedelta(hours=h + 1)
        dims = [{"Name": "InstanceId", "Value": instance_id}]
        data.append({"MetricName": "CPUUtilization", "Dimensions": dims, "Timestamp": ts, "Value": avg, "Unit": "Percent"})
        data.append({"MetricName": "CPUUtilization", "Dimensions": dims, "Timestamp": ts, "Value": maximum, "Unit": "Percent"})
        data.append({"MetricName": "NetworkIn", "Dimensions": dims, "Timestamp": ts, "Value": 1024, "Unit": "Bytes"})
        data.append({"MetricName": "NetworkOut", "Dimensions": dims, "Timestamp": ts, "Value": 1024, "Unit": "Bytes"})
    for i in range(0, len(data), 20):
        cloudwatch.put_metric_data(Namespace="AWS/EC2", MetricData=data[i : i + 20])


def make_vpc_with_subnets(ec2) -> tuple[str, list[str], str]:
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnets = [
        ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24", AvailabilityZone=f"{REGION}a")["Subnet"]["SubnetId"],
        ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.2.0/24", AvailabilityZone=f"{REGION}b")["Subnet"]["SubnetId"],
    ]
    sg = ec2.create_security_group(GroupName="janitor-test", Description="test", VpcId=vpc)["GroupId"]
    return vpc, subnets, sg
