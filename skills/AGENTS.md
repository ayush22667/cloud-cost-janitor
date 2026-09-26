# skills
TrueForge skills: git-backed `SKILL.md` instruction packs the agent loads on demand inside its sandbox.
`cloud-cost-audit/` is the audit-to-teardown playbook; `scripts/aggregate_example.py` is a reference
the agent adapts (it must still write its own script — the sandbox runs generated code).
Registration needs this repository to be public (TrueForge clones it): `SKILL_REPO_URL=<repo url>
bash trueforge/setup.sh`. Keep the frontmatter `description` sharp — it is all the model sees before
loading the skill. Test: `tests/test_skill.py`.
