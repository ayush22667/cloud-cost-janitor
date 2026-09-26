# Cloud Cost Janitor — conventions for agents and humans

Python 3.12 project managed with **uv**. An MCP server (FastMCP 4) that finds idle AWS resources,
prices them, plans a teardown, and deletes only through an approval-gated tool used by a TrueForge agent.
Read `PLAN.md` first: it holds the architecture, the rules, and the build steps.

## Commands
- Install: `uv sync`
- Tests: `uv run pytest` (must be green before every commit; CI runs the same)
- Run MCP server: `uv run cloud-cost-janitor` (reads `.env`; see `.env.example`)
- Register in TrueForge: `bash trueforge/setup.sh`

## Layout (closest `AGENTS.md` wins)
`src/cloud_cost_janitor/{models,pricing,config}.py` are provider-agnostic. `providers/aws/` is the only
place boto3 is imported. `rules/` are pure functions. `planner/` builds ordered, reversible-first teardown
plans. `server/` exposes MCP tools. `tests/` mirrors `src/`. `trueforge/` holds the agent definition and
setup script. `scripts/` holds demo/ops shell scripts.

## Rules that must not be broken
- `delete_resource` is the **only** destructive tool. It is dry-run unless `ALLOW_DELETE=true`, refuses
  protected tags, refuses resources not in a live plan, and re-verifies the resource before deleting.
- Never import boto3 outside `providers/aws/`. Never put cloud-specific shapes into `models`/`rules`/`planner`.
- No secrets in the repo: tokens come from `.env` (git-ignored). The AWS identity is **named explicitly**
  in `.env` (`AWS_PROFILE` or a key pair; optional `AWS_ROLE_ARN`) — never call `boto3.Session()` without
  arguments and never fall back to the host's default credentials. Never log or print identity or
  credentials (no account id, principal, key id), and keep account ids out of docs.
- Least privilege is enforced twice: by the server's tag guard and by the IAM policies in `iam/`.
- Every MCP tool declares `title`, `readOnlyHint`, `destructiveHint`.
- Type hints everywhere; docstrings on tools are the text the model sees — keep them precise and short.
- Small, focused commits; each build step in `PLAN.md` ends with its tests passing.

## AI assistance
The architecture was designed by the author and refined and implemented with Claude Code (disclosed in
README). Keep the disclosure section accurate when tools change.
