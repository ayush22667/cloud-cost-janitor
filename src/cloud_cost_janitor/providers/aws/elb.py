"""Elastic Load Balancing v2 (application / network / gateway).

Load balancers are identified by the ARN suffix ``app/<name>/<hash>`` (the CloudWatch dimension), never
by the full ARN: the ARN embeds the account id, which must not appear in plans, chat or the audit log.
"""

from __future__ import annotations

from datetime import datetime

from cloud_cost_janitor.models import LoadBalancer
from cloud_cost_janitor.providers.aws.client import AwsClients
from cloud_cost_janitor.providers.aws.metrics import load_balancer_metrics, utcnow

# Target health states that do not prove a target is out of service: "unavailable" means health checks
# are disabled (Lambda targets by default) and "initial" means registration is still in progress.
_HEALTHY_STATES = frozenset({"healthy", "unavailable", "initial"})


def is_load_balancer_id(resource_id: str) -> bool:
    return resource_id.startswith(("app/", "net/", "gwy/"))


def _tags_for(elb, arns: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(arns), 20):  # DescribeTags accepts at most 20 ARNs
        resp = elb.describe_tags(ResourceArns=arns[i : i + 20])
        for desc in resp.get("TagDescriptions", []):
            out[desc["ResourceArn"]] = {t["Key"]: t["Value"] for t in desc.get("Tags", [])}
    return out


def counts_as_healthy(state: str | None) -> bool:
    return state in _HEALTHY_STATES


def _target_counts(elb, lb_arn: str) -> tuple[int, int]:
    registered = healthy = 0
    try:
        groups = elb.describe_target_groups(LoadBalancerArn=lb_arn).get("TargetGroups", [])
    except elb.exceptions.TargetGroupNotFoundException:  # type: ignore[attr-defined]
        groups = []  # a load balancer with no target groups at all
    for tg in groups:
        for th in elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"]).get("TargetHealthDescriptions", []):
            registered += 1
            if counts_as_healthy(th.get("TargetHealth", {}).get("State")):
                healthy += 1
    return registered, healthy


def lb_id_from_arn(lb_arn: str) -> str:
    # arn:aws:elasticloadbalancing:region:acct:loadbalancer/app/name/id -> app/name/id
    return lb_arn.split(":loadbalancer/", 1)[1]


def _resolve_arn(elb, lb_id: str) -> str | None:
    """Look a load balancer up by its id (``app/<name>/<hash>``); None when it no longer exists."""
    if lb_id.startswith("arn:"):
        lb_id = lb_id_from_arn(lb_id)
    parts = lb_id.split("/")
    if len(parts) != 3:
        return None
    try:
        raws = elb.describe_load_balancers(Names=[parts[1]]).get("LoadBalancers", [])
    except elb.exceptions.LoadBalancerNotFoundException:  # type: ignore[attr-defined]
        return None
    for raw in raws:
        if lb_id_from_arn(raw["LoadBalancerArn"]) == lb_id:
            return raw["LoadBalancerArn"]
    return None


def _lb_from_api(raw: dict, region: str, tags: dict[str, str], registered: int, healthy: int) -> LoadBalancer:
    return LoadBalancer(
        id=lb_id_from_arn(raw["LoadBalancerArn"]),
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
        arn = raw["LoadBalancerArn"]
        registered, healthy = _target_counts(elb, arn)
        lb = _lb_from_api(raw, region, tags.get(arn, {}), registered, healthy)
        if lb.lb_type == "application":
            lb.metrics = load_balancer_metrics(cw, lb.id, now=now, created_at=lb.created_at, lookback_days=lookback_days)
        out.append(lb)
    return out


def get_load_balancer(clients: AwsClients, region: str, lb_id: str) -> LoadBalancer | None:
    elb = clients.elbv2(region)
    arn = _resolve_arn(elb, lb_id)
    if arn is None:
        return None
    raws = elb.describe_load_balancers(LoadBalancerArns=[arn]).get("LoadBalancers", [])
    if not raws:
        return None
    registered, healthy = _target_counts(elb, arn)
    return _lb_from_api(raws[0], region, _tags_for(elb, [arn]).get(arn, {}), registered, healthy)


def _resolve_all(elb, lb_ids: list[str]) -> list[str]:
    return [arn for arn in (_resolve_arn(elb, i) for i in lb_ids) if arn]


def tag_load_balancers(clients: AwsClients, region: str, lb_ids: list[str], tags: dict[str, str]) -> None:
    if lb_ids and tags:
        elb = clients.elbv2(region)
        arns = _resolve_all(elb, lb_ids)
        if arns:
            elb.add_tags(ResourceArns=arns, Tags=[{"Key": k, "Value": v} for k, v in tags.items()])


def untag_load_balancers(clients: AwsClients, region: str, lb_ids: list[str], keys: list[str]) -> None:
    if lb_ids and keys:
        elb = clients.elbv2(region)
        arns = _resolve_all(elb, lb_ids)
        if arns:
            elb.remove_tags(ResourceArns=arns, TagKeys=keys)


def delete_load_balancer(clients: AwsClients, region: str, lb_id: str) -> None:
    elb = clients.elbv2(region)
    arn = _resolve_arn(elb, lb_id)
    if arn is None:
        raise elb.exceptions.LoadBalancerNotFoundException(  # type: ignore[attr-defined]
            {"Error": {"Code": "LoadBalancerNotFound", "Message": f"load balancer {lb_id} does not exist"}}, "DeleteLoadBalancer"
        )
    elb.delete_load_balancer(LoadBalancerArn=arn)
