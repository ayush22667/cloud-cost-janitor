"""The TrueForge skill must have valid frontmatter and reference the tools that actually exist."""

import ast
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "cloud-cost-audit"
TOOLS = {"generate_cost_report", "delete_resource", "call_aws"}


def test_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "missing YAML frontmatter"
    fields = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    assert fields["name"].strip() == "cloud-cost-audit"
    assert fields["description"].strip().startswith("Use when")
    assert len(fields["description"]) <= 500


def test_skill_names_real_tools_and_rules():
    text = (SKILL_DIR / "SKILL.md").read_text()
    for tool in TOOLS:
        assert tool in text, tool
    assert "one call per resource" in text and "never from a script" in text
    assert "plan_id" in text


def test_example_script_is_valid_python_and_uses_the_bridge():
    src = (SKILL_DIR / "scripts" / "aggregate_example.py").read_text()
    ast.parse(src)
    assert "from mcp_client import call_tool" in src
    assert '"aws-janitor", "generate_cost_report"' in src
