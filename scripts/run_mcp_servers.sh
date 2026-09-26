#!/usr/bin/env bash
# Start both MCP servers in the foreground (Ctrl-C stops both):
#   aws-janitor  (this repo)                      -> http://127.0.0.1:${JANITOR_PORT:-8000}/mcp
#   aws-api      (official awslabs, READ-ONLY)     -> http://127.0.0.1:${AWS_API_PORT:-8001}/mcp
# Reads .env for the identity. If AWS_ROLE_ARN is set, both servers act as that role: the janitor
# assumes it itself (auto-refreshing); for aws-api this script assumes it once with STS and hands the
# temporary credentials to that process only (they expire after an hour, restart the script then).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "missing .env (copy .env.example)"; exit 2; }
set -a; . ./.env; set +a
[ -n "${AWS_PROFILE:-}${AWS_ACCESS_KEY_ID:-}" ] || { echo "set AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in .env"; exit 2; }
JANITOR_PORT="${JANITOR_PORT:-8000}"
AWS_API_PORT="${AWS_API_PORT:-8001}"
REGION="${AWS_REGIONS%%,*}"

# Pinned: bump deliberately after reading its changelog (https://pypi.org/project/awslabs.aws-api-mcp-server/).
AWS_API_MCP_VERSION="${AWS_API_MCP_VERSION:-1.5.5}"

api_env=()
if [ -n "${AWS_ROLE_ARN:-}" ]; then
  extid=(); [ -n "${AWS_EXTERNAL_ID:-}" ] && extid=(--external-id "$AWS_EXTERNAL_ID")
  creds=$(aws sts assume-role --role-arn "$AWS_ROLE_ARN" --role-session-name cloud-cost-janitor-api "${extid[@]}" \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)
  read -r k s t <<< "$creds"
  api_env=(AWS_ACCESS_KEY_ID="$k" AWS_SECRET_ACCESS_KEY="$s" AWS_SESSION_TOKEN="$t" AWS_PROFILE=)
fi

trap 'kill 0' EXIT INT TERM

env "${api_env[@]}" AWS_API_MCP_TRANSPORT=streamable-http AWS_API_MCP_HOST=127.0.0.1 AWS_API_MCP_PORT="$AWS_API_PORT" \
  AUTH_TYPE=no-auth READ_OPERATIONS_ONLY=true AWS_REGION="$REGION" \
  uvx "awslabs.aws-api-mcp-server==$AWS_API_MCP_VERSION" 2>&1 | sed 's/^/[aws-api] /' &

uv run cloud-cost-janitor 2>&1 | sed 's/^/[aws-janitor] /' &

wait
