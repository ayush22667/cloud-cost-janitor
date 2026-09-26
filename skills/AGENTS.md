# skills
TrueForge skills: git-backed instruction packs in the Agent Skills format (agentskills.io) that the agent
loads on demand inside its sandbox. `cloud-cost-audit/` is the audit-to-teardown playbook:
`SKILL.md` (frontmatter `name` = directory name, `description` starting "Use when", `license`,
`compatibility`, `metadata`; body under 500 lines with a checklist and the response table),
`scripts/aggregate_plan.py` (runnable utility the agent executes with a `plan_id`; it calls `get_plan`
through the sandbox bridge and never rescans) and `evals/evals.json` (three scenarios to re-run after any
change). Reference files from `SKILL.md` by relative path, one level deep.
Rules: procedures go here, not into `trueforge/agent.json`; the frontmatter `description` is all the model
sees before loading the skill and `setup.sh` registers that exact text; TrueForge clones this repo at the
tag `setup.sh` pins (`SKILL_REF`), so bump the tag after changing anything here.
Check: `uv run pytest tests/test_skill.py` and `uvx --from skills-ref agentskills validate skills/cloud-cost-audit`.
