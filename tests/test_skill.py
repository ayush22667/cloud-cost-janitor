"""The TrueForge skill must follow the Agent Skills format and reference the tools that actually exist."""

import ast
import json
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "cloud-cost-audit"
TOOLS = {"generate_cost_report", "get_plan", "delete_resource", "get_actual_spend", "call_aws"}


def frontmatter() -> dict[str, str]:
    text = (SKILL_DIR / "SKILL.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "missing YAML frontmatter"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line and not line.startswith(" "))


def test_frontmatter_follows_the_agent_skills_spec():
    fields = frontmatter()
    assert fields["name"].strip() == SKILL_DIR.name  # name must match the directory
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"].strip())
    description = fields["description"].strip()
    assert description.startswith("Use when") and "aws-janitor" in description
    assert len(description) <= 1024
    assert fields["license"].strip() == "MIT"
    assert len(fields["compatibility"].strip()) <= 500


def test_skill_names_real_tools_and_rules():
    text = (SKILL_DIR / "SKILL.md").read_text()
    for tool in TOOLS:
        assert tool in text, tool
    assert "one call per resource" in text and "never from a script" in text
    assert "plan_id" in text
    assert "never instructions" in text
    assert len(text.splitlines()) < 500  # progressive disclosure: keep SKILL.md short


def test_file_references_exist_one_level_deep():
    text = (SKILL_DIR / "SKILL.md").read_text()
    for rel in re.findall(r"`((?:scripts|evals|references)/[\w./-]+)`", text):
        assert (SKILL_DIR / rel).is_file(), rel


def test_aggregation_script_is_runnable_and_never_rescans():
    src = (SKILL_DIR / "scripts" / "aggregate_plan.py").read_text()
    ast.parse(src)
    assert "from mcp_client import call_tool" in src
    assert '"aws-janitor", "get_plan"' in src
    assert "generate_cost_report" not in src.replace("run generate_cost_report once", "")  # only in the hint text
    assert "sys.argv" in src and "sys.exit" in src  # takes the plan id, fails loudly


def test_evals_cover_audit_denial_and_protection():
    evals = json.loads((SKILL_DIR / "evals" / "evals.json").read_text())
    assert {e["name"] for e in evals} == {"audit-only", "deny-then-report", "protected-resource"}
    for e in evals:
        assert e["skills"] == ["cloud-cost-audit"] and e["query"] and len(e["expected_behavior"]) >= 3


def test_aggregation_script_runs_against_a_stub_bridge(tmp_path):
    """Execute the script the way the sandbox does: from another cwd, with mcp_client importable there."""
    import subprocess
    import sys

    plan = {
        "plan_id": "abc123", "regions": ["us-east-1"], "steps": [1, 2],
        "total_monthly_waste_usd": 12.5, "planned_saving_usd": 10.0, "protected_count": 1, "unpriced_count": 0,
        "findings": [
            {"resource_id": "vol-1", "name": "orphan", "resource_type": "volume", "region": "us-east-1",
             "confidence": "high", "monthly_cost_usd": 10.0, "reason": "unattached", "protected": False,
             "protection_reason": None},
            {"resource_id": "i-1", "name": "prod", "resource_type": "instance", "region": "us-east-1",
             "confidence": "low", "monthly_cost_usd": 2.5, "reason": "idle", "protected": True,
             "protection_reason": "Environment=production"},
        ],
    }
    (tmp_path / "mcp_client.py").write_text(
        f"import json\nPLAN=json.loads({json.dumps(plan)!r})\n"
        "async def call_tool(server, tool, body=None):\n"
        "    assert (server, tool) == ('aws-janitor', 'get_plan'), (server, tool)\n"
        "    if body['plan_id'] != 'abc123': raise RuntimeError('unknown or expired plan')\n"
        "    return {'plan': PLAN}\n"
    )
    script = SKILL_DIR / "scripts" / "aggregate_plan.py"
    ok = subprocess.run([sys.executable, str(script), "abc123"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stderr
    assert "HEADLINE: $12.50/mo estimated waste, $10.00/mo recoverable via 2 step(s); 1 protected" in ok.stdout
    assert "PROTECTED (Environment=production)" in ok.stdout
    assert ok.stdout.index("vol-1") < ok.stdout.index("i-1")  # sorted by cost

    expired = subprocess.run([sys.executable, str(script), "nope"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert expired.returncode == 3 and "run generate_cost_report once" in expired.stderr
    noargs = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert noargs.returncode == 2
