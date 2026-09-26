from cloud_cost_janitor.providers.aws.elb import counts_as_healthy, lb_id_from_arn
from tests.providers.conftest import REGION, make_vpc_with_subnets, run_instance


def create_alb(elbv2, ec2, name="janitor-test-alb", tags=None):
    _, subnets, sg = make_vpc_with_subnets(ec2)
    kwargs = {"Name": name, "Subnets": subnets, "SecurityGroups": [sg], "Scheme": "internet-facing", "Type": "application"}
    if tags:
        kwargs["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
    resp = elbv2.create_load_balancer(**kwargs)
    return resp["LoadBalancers"][0]["LoadBalancerArn"], subnets[0]


def test_alb_with_no_targets(provider, elbv2, ec2):
    arn, _ = create_alb(elbv2, ec2, tags={"janitor-demo": "true"})
    lbs = provider.list_load_balancers(REGION, lookback_days=7)
    lb = next(l for l in lbs if l.id == lb_id_from_arn(arn))
    assert lb.id.startswith("app/janitor-test-alb/") and "arn:" not in lb.id  # no account id in ids
    assert lb.lb_type == "application" and lb.name == "janitor-test-alb"
    assert lb.registered_targets == 0 and lb.healthy_targets == 0
    assert lb.tags == {"janitor-demo": "true"}
    assert lb.metrics is not None and lb.metrics.observed_days >= 1
    assert all((d.request_count or 0) == 0 for d in lb.metrics.days)


def test_alb_counts_registered_targets(provider, elbv2, ec2):
    arn, subnet = create_alb(elbv2, ec2)
    vpc = ec2.describe_subnets(SubnetIds=[subnet])["Subnets"][0]["VpcId"]
    tg = elbv2.create_target_group(Name="janitor-tg", Protocol="HTTP", Port=80, VpcId=vpc)["TargetGroups"][0]["TargetGroupArn"]
    elbv2.create_listener(LoadBalancerArn=arn, Protocol="HTTP", Port=80, DefaultActions=[{"Type": "forward", "TargetGroupArn": tg}])
    iid = run_instance(ec2)
    elbv2.register_targets(TargetGroupArn=tg, Targets=[{"Id": iid, "Port": 80}])
    lb = provider.get_load_balancer(REGION, lb_id_from_arn(arn))
    assert lb is not None and lb.registered_targets == 1


def test_get_and_delete_load_balancer_by_id(provider, elbv2, ec2):
    arn, _ = create_alb(elbv2, ec2)
    lb_id = lb_id_from_arn(arn)
    assert provider.get_load_balancer(REGION, lb_id) is not None
    assert provider.get_load_balancer(REGION, arn) is not None  # a full ARN still resolves
    assert provider.get_load_balancer(REGION, "app/janitor-test-alb/0000000000000000") is None  # same name, other hash
    provider.delete_load_balancer(REGION, lb_id)
    assert provider.get_load_balancer(REGION, lb_id) is None


def test_tag_load_balancer_via_generic_tagging(provider, elbv2, ec2):
    arn, _ = create_alb(elbv2, ec2)
    lb_id = lb_id_from_arn(arn)
    provider.tag_resources(REGION, [lb_id], {"janitor:teardown-after": "2026-10-03"})
    assert provider.get_load_balancer(REGION, lb_id).tags.get("janitor:teardown-after") == "2026-10-03"
    provider.untag_resources(REGION, [lb_id], ["janitor:teardown-after"])
    assert "janitor:teardown-after" not in provider.get_load_balancer(REGION, lb_id).tags


def test_target_health_states_that_do_not_prove_idleness_count_as_healthy():
    assert counts_as_healthy("healthy") and counts_as_healthy("unavailable") and counts_as_healthy("initial")
    assert not counts_as_healthy("unhealthy") and not counts_as_healthy("draining") and not counts_as_healthy("unused")
    assert not counts_as_healthy(None)
