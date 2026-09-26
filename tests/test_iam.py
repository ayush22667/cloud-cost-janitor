"""IAM artifacts must stay least-privilege: every action statement carries the tag condition."""

import json
from pathlib import Path

IAM = Path(__file__).resolve().parents[1] / "iam"
TAG_CONDITION_KEY = "aws:ResourceTag/janitor-demo"


def test_read_policy_is_describe_only():
    doc = json.loads((IAM / "janitor-read-policy.json").read_text())
    actions = [a for st in doc["Statement"] for a in st["Action"]]
    for a in actions:
        assert a.split(":")[1].startswith(("Describe", "GetMetricStatistics", "GetCallerIdentity")), a


def test_actions_policy_requires_tag_on_every_mutating_statement():
    doc = json.loads((IAM / "janitor-actions-policy.json").read_text())
    for st in doc["Statement"]:
        cond = st["Condition"]["StringEquals"]
        if any(a in ("ec2:CreateTags",) for a in st["Action"]) and st["Sid"] == "TagNewSnapshots":
            assert cond == {"ec2:CreateAction": "CreateSnapshot"}
            continue
        assert cond.get(TAG_CONDITION_KEY) == "true", st["Sid"]
        assert st["Resource"] != "*", st["Sid"]


def test_cross_account_template_has_external_id_and_tag_guard():
    text = (IAM / "cross-account-role.yaml").read_text()
    assert "sts:ExternalId" in text
    assert "aws:ResourceTag/${AllowedTagKey}" in text
    assert "NoEcho: true" in text  # the external id is never echoed by CloudFormation
    assert "CloudCostJanitorRole" in text
