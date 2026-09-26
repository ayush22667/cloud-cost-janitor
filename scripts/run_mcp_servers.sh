#!/usr/bin/env bash
# Start both MCP servers in the foreground (Ctrl-C stops both):
#   aws-janitor  (this repo)                      -> http://127.0.0.1:${JANITOR_PORT:-8000}/mcp
#   aws-api      (official awslabs, READ-ONLY)     -> http://127.0.0.1:${AWS_API_PORT:-8001}/mcp
# Reads .env for the janitor; AWS credentials come from the host credential chain.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "missing .env (copy .env.example)"; exit 2; }
set -a; . ./.env; set +a
JANITOR_PORT="${JANITOR_PORT:-8000}"
AWS_API_PORT="${AWS_API_PORT:-8001}"
REGION="${AWS_REGIONS%%,*}"

trap 'kill 0' EXIT INT TERM

AWS_API_MCP_TRANSPORT=streamable-http AWS_API_MCP_HOST=127.0.0.1 AWS_API_MCP_PORT="$AWS_API_PORT" \
AUTH_TYPE=no-auth READ_OPERATIONS_ONLY=true AWS_REGION="$REGION" \
  uvx awslabs.aws-api-mcp-server@latest 2>&1 | sed 's/^/[aws-api] /' &

uv run cloud-cost-janitor 2>&1 | sed 's/^/[aws-janitor] /' &

wait
