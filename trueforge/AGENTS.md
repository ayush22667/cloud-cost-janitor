# trueforge
Definition of the TrueForge agent and its connectors, written the way the TrueForge docs prescribe.
`agent.json` is the create body (`name`, `description`, `manifest`) sent as-is: role-only instructions
that point to the `cloud-cost-audit` skill (no playbook in the prompt), both MCP servers with their
approval gates, the skill, and the runtime config. `connectors.json` holds the connector manifests with a
`${COST_JANITOR_TOKEN}` placeholder. `setup.sh` runs preflight checks (server up, allowlist working, model
available), PUTs the connectors, registers the skill from the pinned tag with the description read from
`SKILL.md`, and creates or updates the agent via `http://localhost:8790/api/v1`. Agents are stored in
TrueForge's DB, not in this repo; these files recreate it.
Gates: `aws-janitor` -> `["@destructive","@write","delete_resource"]` (delete, mark and unmark all pause); `aws-api` -> `["@all"]`.
Rules: no pseudo fields in `agent.json`; skills need `config.sandbox.enabled: true`; never put secrets or
hosts in the manifest. Checked by `tests/test_agent_manifest.py`.
