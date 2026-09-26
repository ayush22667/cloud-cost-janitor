# trueforge
Definition of the TrueForge agent and its connectors. `agent.json` is the agent manifest (model,
instructions, both MCP servers with their approval gates, runtime config). `connectors.json` holds the
connector manifests with a `${COST_JANITOR_TOKEN}` placeholder. `setup.sh` runs preflight checks (server up,
allowlist working, model available), PUTs the connectors and creates/updates the agent via
`http://localhost:8790/api/v1`. Agents are stored in TrueForge's DB, not in this repo — these files recreate it.
Gates: `aws-janitor` -> `["@destructive","@write","delete_resource"]` (delete, mark and unmark all pause); `aws-api` -> `["@all"]`.
