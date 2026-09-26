#!/usr/bin/env bash
# Drive the saved TrueForge agent from the command line (what the chat UI does, scripted).
#   scripts/smoke_test.sh new "<message>"                 start a session with cloud-cost-janitor and send a message
#   scripts/smoke_test.sh say <session_id> "<message>"    send another message
#   scripts/smoke_test.sh answer <session_id> "<text>"     answer a pending ask_user_question
#   scripts/smoke_test.sh approve <session_id> allow|deny  resolve ALL pending tool approvals the same way
#   scripts/smoke_test.sh show <session_id>                print the last turn again
# Env: TRUEFORGE_URL (default http://localhost:8790), AGENT (default cloud-cost-janitor), TIMEOUT seconds (default 900)
set -euo pipefail
API="${TRUEFORGE_URL:-http://localhost:8790}/api/v1"
AGENT="${AGENT:-cloud-cost-janitor}"
TIMEOUT="${TIMEOUT:-900}"
cmd="${1:-}"; shift || true

py() { python3 -c "$@"; }

# The list endpoint's ordering is not guaranteed across versions, so pick the newest by created_at.
last_turn() { curl -s "$API/sessions/$1/turns?limit=25" | py 'import sys,json; d=json.load(sys.stdin)["data"]; print(max(d, key=lambda t: t["created_at"])["id"] if d else "")'; }

wait_and_show() { # session turn
  local sid="$1" tid="$2" status=running start
  start=$(date +%s)
  while [ "$status" = running ]; do
    [ $(( $(date +%s) - start )) -ge "$TIMEOUT" ] && { echo "timeout after ${TIMEOUT}s"; break; }
    sleep 3
    status=$(curl -s "$API/sessions/$sid/turns/$tid" | py 'import sys,json;print(json.load(sys.stdin)["data"]["state"]["status"])')
  done
  curl -s "$API/sessions/$sid/turns/$tid" > /tmp/janitor_turn.json
  curl -s "$API/sessions/$sid/turns/$tid/events?limit=100" > /tmp/janitor_events.json || true
  py '
import json
st=json.load(open("/tmp/janitor_turn.json"))["data"]["state"]
print("status:", st["status"])
if st["status"]=="error": print("error:", st.get("message"))
out=(st.get("output") or {}).get("content")
if out: print("---- agent ----\n"+out+"\n---------------")
for ra in st.get("required_actions") or []:
    calls=[c["id"] for c in ra.get("tool_calls",[])]
    print("PENDING:", ra["type"], calls)
try: evs=json.load(open("/tmp/janitor_events.json")).get("data",[])
except Exception: evs=[]
for it in evs:
    e=it.get("event",it); t=e.get("type")
    if t=="model.message":
        for tc in e.get("tool_calls") or []:
            args=tc.get("function",{}).get("arguments") or ""
            print("tool call:", tc["function"]["name"], args[:160].replace("\n"," "))
    elif t in ("sandbox.created","tool.approval_required","tool.response_required","mcp.initialize"):
        print("event:", t)
    elif t=="tool.response":
        print("tool result:", (e.get("content") or "")[:200].replace("\n"," "))
m=st.get("metrics") or {}
if m: print("tokens:", m.get("total_tokens"), "cost_usd:", m.get("total_cost_in_usd"))
'
  rm -f /tmp/janitor_turn.json /tmp/janitor_events.json
}

send_turn() { # session body
  local tid
  tid=$(curl -s -X POST "$API/sessions/$1/turns" -H 'content-type: application/json' -d "$2" | py 'import sys,json; d=json.load(sys.stdin); print(d.get("data",{}).get("id") or ("ERR "+json.dumps(d)))')
  case "$tid" in ERR*) echo "$tid" >&2; exit 1;; esac
  wait_and_show "$1" "$tid"
}

pending_calls() { # session -> lines "type thread_id call_id"
  curl -s "$API/sessions/$1/turns/$(last_turn "$1")" | py 'import sys,json
st=json.load(sys.stdin)["data"]["state"]
for ra in st.get("required_actions") or []:
    for c in ra.get("tool_calls",[]): print(ra["type"], ra.get("thread_id","main"), c["id"])'
}

case "$cmd" in
  new)
    sid=$(curl -s -X POST "$API/sessions" -H 'content-type: application/json' -d "{\"agent\":{\"name\":\"$AGENT\"}}" | py 'import sys,json; d=json.load(sys.stdin); print(d.get("data",{}).get("id") or ("ERR "+json.dumps(d)))')
    case "$sid" in ERR*) echo "$sid" >&2; exit 1;; esac
    echo "session: $sid"
    body=$(py 'import json,sys; print(json.dumps({"input":[{"type":"user.message","content":sys.argv[1]}],"stream":False}))' "$1")
    send_turn "$sid" "$body" ;;
  say)
    body=$(py 'import json,sys; print(json.dumps({"input":[{"type":"user.message","content":sys.argv[1]}],"stream":False}))' "$2")
    send_turn "$1" "$body" ;;
  answer)
    items=$(pending_calls "$1" | awk -v t="$2" '$1=="tool.response_required"{printf "{\"type\":\"user.tool_response\",\"thread_id\":\"%s\",\"tool_call_id\":\"%s\",\"content\":%s},", $2, $3, "\"" t "\""}')
    [ -n "$items" ] || { echo "no pending question"; exit 1; }
    send_turn "$1" "{\"input\":[${items%,}],\"stream\":false}" ;;
  approve)
    dec="$2"; reason='"reason":"denied by user"'; [ "$dec" = allow ] && reason=''
    items=$(pending_calls "$1" | awk -v s="$dec" -v r="$reason" '$1=="tool.approval_required"{printf "{\"type\":\"user.tool_approval\",\"thread_id\":\"%s\",\"tool_call_id\":\"%s\",\"approval\":{\"status\":\"%s\"%s}},", $2, $3, s, (r==""?"":","r)}')
    [ -n "$items" ] || { echo "no pending approval"; exit 1; }
    send_turn "$1" "{\"input\":[${items%,}],\"stream\":false}" ;;
  show) wait_and_show "$1" "$(last_turn "$1")" ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
