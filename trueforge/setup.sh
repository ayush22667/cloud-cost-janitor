#!/usr/bin/env bash
# Register the MCP connectors and the cloud-cost-janitor agent in a local TrueForge.
# Usage: bash trueforge/setup.sh            (reads .env; MODEL and TRUEFORGE_URL may be overridden in the environment)
set -euo pipefail
cd "$(dirname "$0")/.."

TRUEFORGE_URL="${TRUEFORGE_URL:-http://localhost:8790}"
API="$TRUEFORGE_URL/api/v1"
MODEL="${MODEL:-litellm/glm-latest}"
JANITOR_PORT="${JANITOR_PORT:-8000}"
AWS_API_PORT="${AWS_API_PORT:-8001}"

[ -f .env ] || { echo "missing .env (copy .env.example)"; exit 2; }
COST_JANITOR_TOKEN=$(grep -E '^COST_JANITOR_TOKEN=' .env | cut -d= -f2- | tr -d '"')
[ -n "$COST_JANITOR_TOKEN" ] || { echo "COST_JANITOR_TOKEN is empty in .env"; exit 2; }
export COST_JANITOR_TOKEN JANITOR_PORT AWS_API_PORT MODEL

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
subst() { python3 -c 'import os,sys,string; print(string.Template(sys.stdin.read()).substitute(os.environ))'; }
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

say "Preflight: TrueForge at $TRUEFORGE_URL"
curl -sf -m 5 "$API/capabilities" >/dev/null || fail "TrueForge is not reachable. Start it with:
  OUTBOUND_URL_ALLOWED_HOSTS='[\"127.0.0.1\",\"localhost\"]' npx @truefoundry/trueforge"

say "Preflight: model $MODEL is configured"
curl -s "$API/models" | jget "[m['name'] for m in d['data']]" | grep -q "'$MODEL'" \
  || fail "model $MODEL not found in TrueForge (Settings -> Models). Set MODEL=<provider/model> to use another."

say "Preflight: MCP servers are running"
curl -sf -m 5 -o /dev/null -w '' -X POST "http://127.0.0.1:$JANITOR_PORT/mcp" -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -H "authorization: Bearer $COST_JANITOR_TOKEN" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup","version":"0"}}}' \
  || fail "aws-janitor server not answering on :$JANITOR_PORT (run scripts/run_mcp_servers.sh)"
curl -s -m 5 -o /dev/null "http://127.0.0.1:$AWS_API_PORT/mcp" || fail "aws-api server not answering on :$AWS_API_PORT (run scripts/run_mcp_servers.sh)"

say "Registering connectors"
python3 -c 'import json,sys; [print(json.dumps(c)) for c in json.load(sys.stdin)]' < trueforge/connectors.json | while read -r line; do
  body=$(printf '%s' "$line" | subst)
  name=$(printf '%s' "$body" | jget "d['manifest']['name']")
  code=$(curl -s -o /tmp/tf_setup_resp.json -w '%{http_code}' -X PUT "$API/settings/mcp-servers" -H 'content-type: application/json' -d "$body")
  [ "$code" = "200" ] || [ "$code" = "201" ] || fail "connector $name: HTTP $code $(cat /tmp/tf_setup_resp.json)"
  tools=$(curl -s -m 30 "$API/mcp-servers/$name/tools" | jget "len(d.get('data',[]))" 2>/dev/null || echo 0)
  [ "$tools" -gt 0 ] || fail "TrueForge cannot list tools of $name. If it runs on 127.0.0.1, restart TrueForge with
  OUTBOUND_URL_ALLOWED_HOSTS='[\"127.0.0.1\",\"localhost\"]' (its outbound guard blocks loopback by default)."
  echo "  $name: $tools tools"
done

say "Registering agent"
agent_body=$(subst < trueforge/agent.json)
existing=$(curl -s "$API/agents?agent_name=cloud-cost-janitor" | jget "next((a['id'] for a in d['data'] if a['name']=='cloud-cost-janitor'), '')")
if [ -n "$existing" ]; then
  update=$(printf '%s' "$agent_body" | jget "json.dumps({'description': d['description'], 'manifest': d['manifest']})")
  code=$(curl -s -o /tmp/tf_setup_resp.json -w '%{http_code}' -X PUT "$API/agents/$existing" -H 'content-type: application/json' -d "$update")
  [ "$code" = "200" ] || fail "agent update: HTTP $code $(cat /tmp/tf_setup_resp.json)"
  echo "  updated agent $existing"
else
  code=$(curl -s -o /tmp/tf_setup_resp.json -w '%{http_code}' -X POST "$API/agents" -H 'content-type: application/json' -d "$agent_body")
  [ "$code" = "201" ] || fail "agent create: HTTP $code $(cat /tmp/tf_setup_resp.json)"
  existing=$(jget "d['data']['id']" < /tmp/tf_setup_resp.json)
  echo "  created agent $existing"
fi
gates=$(jget "[(s['name'], s.get('require_approval_for_tools')) for s in d['data']['manifest']['mcp_servers']]" < /tmp/tf_setup_resp.json)
echo "  approval gates: $gates"
rm -f /tmp/tf_setup_resp.json
say "Done. Open $TRUEFORGE_URL -> Agents -> cloud-cost-janitor -> Try"
