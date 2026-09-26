"""Elastic Load Balancing v2 (application / network / gateway)."""

from __future__ import annotations

from datetime import datetime

from cloud_cost_janitor.models import LoadBalancer
from cloud_cost_janitor.providers.aws.client import AwsClients
from cloud_cost_janitor.providers.aws.metrics import load_balancer_metrics, utcnow


def _tags_for(elb, arns: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(arns), 20):  # DescribeTags accepts at most 20 ARNs
        resp = elb.describe_tags(ResourceArns=arns[i : i + 20])
        for desc in resp.get("TagDescriptions", []):
            out[desc["ResourceArn"]] = {t["Key"]: t["Value"] for t in desc.get("Tags", [])}
    return out


def _target_counts(elb, lb_arn: str) -> tuple[int, int]:
    registered = healthy = 0
    try:
        groups = elb.describe_target_groups(LoadBalancerArn=lb_arn).get("TargetGroups", [])
    except elb.exceptions.TargetGroupNotFoundException:  # type: ignore[attr-defined]
        groups = []  # a load balancer with no target groups at all
    for tg in groups:
        for th in elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"]).get("TargetHealthDescriptions", []):
            registered += 1
            if th.get("TargetHealth", {}).get("State") == "healthy":
                healthy += 1
    return registered, healthy


def _metric_dimension(lb_arn: str) -> str:
    # arn:aws:elasticloadbalancing:region:acct:loadbalancer/app/name/id -> app/name/id
    return lb_arn.split(":loadbalancer/", 1)[1]


def _lb_from_api(raw: dict, region: str, tags: dict[str, str], registered: int, healthy: int) -> LoadBalancer:
    return LoadBalancer(
        id=raw["LoadBalancerArn"],
        name=raw.get("LoadBalancerName", ""),
        provider="aws",
        region=region,
        tags=tags,
        created_at=raw.get("CreatedTime"),
        lb_type=raw.get("Type", ""),
        registered_targets=registered,
        healthy_targets=healthy,
    )


def list_load_balancers(clients: AwsClients, region: str, *, lookback_days: int, now: datetime | None = None) -> list[LoadBalancer]:
    now = now or utcnow()
    elb = clients.elbv2(region)
    raws: list[dict] = []
    for page in elb.get_paginator("describe_load_balancers").paginate():
        raws.extend(page.get("LoadBalancers", []))
    tags = _tags_for(elb, [r["LoadBalancerArn"] for r in raws])
    cw = clients.cloudwatch(region)

    out: list[LoadBalancer] = []
    for raw in raws:
        registered, healthy = _target_counts(elb, raw["LoadBalancerArn"])
        lb = _lb_from_api(raw, region, tags.get(raw["LoadBalancerArn"], {}), registered, healthy)
        if lb.lb_type == "application":
            lb.metrics = load_balancer_metrics(
                cw, _metric_dimension(lb.id), now=now, created_at=lb.created_at, lookback_days=lookback_days
            )
        out.append(lb)
    return out


def get_load_balancer(clients: AwsClients, region: str, lb_arn: str) -> LoadBalancer | None:
    elb = clients.elbv2(region)
    try:
        resp = elb.describe_load_balancers(LoadBalancerArns=[lb_arn])
    except elb.exceptions.LoadBalancerNotFoundException:  # type: ignore[attr-defined]
        return None
    raws = resp.get("LoadBalancers", [])
    if not raws:
        return None
    registered, healthy = _target_counts(elb, lb_arn)
    return _lb_from_api(raws[0], region, _tags_for(elb, [lb_arn]).get(lb_arn, {}), registered, healthy)


def tag_load_balancers(clients: AwsClients, region: str, arns: list[str], tags: dict[str, str]) -> None:
    if arns and tags:
        clients.elbv2(region).add_tags(ResourceArns=arns, Tags=[{"Key": k, "Value": v} for k, v in tags.items()])


def untag_load_balancers(clients: AwsClients, region: str, arns: list[str], keys: list[str]) -> None:
    if arns and keys:
        clients.elbv2(region).remove_tags(ResourceArns=arns, TagKeys=keys)


def delete_load_balancer(clients: AwsClients, region: str, lb_arn: str) -> None:
    clients.elbv2(region).delete_load_balancer(LoadBalancerArn=lb_arn)
