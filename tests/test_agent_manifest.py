"""The TrueForge agent manifest must stay within the rules from the TrueForge docs."""

import json
import re
from pathlib import Path

AGENT = json.loads((Path(__file__).resolve().parents[1] / "trueforge" / "agent.json").read_text())
MANIFEST = AGENT["manifest"]


def test_name_and_description_are_valid_for_the_api():
    assert re.fullmatch(r"[a-z][a-z0-9-]{0,62}[a-z0-9]", AGENT["name"])
    assert 1 <= len(AGENT["description"].strip()) <= 1024
    assert not [k for k in AGENT if k.startswith("_")]  # the file is sent as-is: no pseudo fields


def test_instructions_are_role_only_and_point_to_the_skill():
    text = MANIFEST["instructions"]
    assert "cloud-cost-audit" in text
    assert len(text) < 1000  # the playbook lives in the skill, not in the prompt
    assert not re.search(r"\n\s*\d+\.\s", text)  # no numbered procedure in the prompt


def test_skill_requires_the_sandbox():
    assert [s["name"] for s in MANIFEST["skills"]] == ["cloud-cost-audit"]
    assert MANIFEST["config"]["sandbox"]["enabled"] is True


def test_every_state_changing_tool_is_gated():
    servers = {s["name"]: s for s in MANIFEST["mcp_servers"]}
    janitor = servers["aws-janitor"]["require_approval_for_tools"]
    assert {"@destructive", "@write", "delete_resource"} <= set(janitor)
    assert servers["aws-api"]["require_approval_for_tools"] == ["@all"]
    assert set(servers["aws-api"]["enable_tools"]) == {"call_aws", "suggest_aws_commands"}


def test_no_secrets_or_hosts_in_the_manifest():
    text = json.dumps(MANIFEST)
    assert "Bearer" not in text and "http://" not in text and "AKIA" not in text
