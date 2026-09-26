# Cloud Cost Janitor

Finds idle EC2 instances, unattached volumes and empty load balancers in your AWS account, works out
what they cost per month, and deletes them. It only deletes after you click Allow.

Built on [TrueForge](https://trueforge.dev), TrueFoundry's open-source agent harness, for the
*Agents That Act* hackathon (TrueFoundry x Polaris, September 2026). `SOLUTION.pdf` is the one-page
design summary; this file is about running it.

```
you:    Audit us-east-1 for wasted cloud spend.
agent:  3 wasteful resources, $18.03/month: an ALB with no targets ($16.43), two unattached
        10 GB volumes ($0.80 each). Which should I tear down?   [All] [ALB only] [Volumes] [Nothing]
you:    Both volumes.
agent:  delete_resource(vol-...a)   [Allow] [Deny]
you:    Deny.
agent:  Denied. Not deleted, no snapshot taken.
you:    OK, go ahead.
agent:  delete_resource(vol-...a)   [Allow]
        Deleted. Restore point snap-0faee..., saving $0.80/month.
```

## Why

Every AWS account I have worked in had a few hundred dollars a month of forgotten resources:
volumes left behind by terminated instances, load balancers whose targets were deleted years ago,
test boxes nobody switched off. The finding part is easy. The hard part is deleting things without
someone getting paged at 2am, which is why nobody automates it.

So the agent does the boring work (scan, price, plan) on its own and stops at the one step that matters.

Every deletion is a separate approval, taken with a snapshot first, and checked again at the moment
of deletion in case something changed since the plan was made.

## How it works

```mermaid
flowchart LR
  U[You, in TrueForge chat] --> A[Agent]
  A -->|generated Python| S[TrueForge sandbox]
  S -->|mcp_client.call_tool| J
  A -->|MCP tools| J[aws-janitor server<br/>this repo, 127.0.0.1:8000]
  A -->|read-only CLI, each call approved| O[aws-api server<br/>official awslabs, 127.0.0.1:8001]
  J --> P[boto3]
  P --> AWS[(Your AWS account)]
  O --> AWS
  A -. delete_resource: Allow / Deny .-> U
```

Three processes run on your machine. TrueForge hosts the agent and the chat. The `aws-janitor` MCP
server (this repo) talks to AWS with boto3 and exposes ten tools, one of which is destructive.
The official [awslabs AWS API server](https://awslabs.github.io/mcp/servers/aws-api-mcp-server) runs in
read-only mode for ad-hoc questions like "what else is in that VPC".

An audit goes like this:

1. The agent calls `generate_cost_report`. The server lists instances, volumes and load balancers,
   pulls 14 days of CloudWatch data, applies the rules below, prices each finding and returns a plan
   with a `plan_id`.
2. The agent writes a short Python script and runs it in TrueForge's sandbox. The script calls the
   same tool through `mcp_client` and prints totals per type and confidence. The sandbox has no AWS
   credentials; its calls are bridged back to the server.
3. The agent shows the plan as a table and asks which resources to remove.
4. For each one you name it calls `delete_resource` once. TrueForge pauses for Allow or Deny.
5. On Allow, the server re-checks the resource, snapshots it, deletes it, and returns the snapshot id.

### Detection rules

The thresholds are AWS Trusted Advisor's, not mine.

| Finding | Rule |
|---|---|
| Idle instance | running, daily CPU at or under 10% and network at or under 5 MB on every observed day of a 14-day window (first hour after launch ignored) |
| Stopped instance | reported with its EBS cost only |
| Orphaned volume | state `available` |
| Idle load balancer | an application load balancer with no healthy targets, unless it served 100 requests/day or more over the window (a redirect-only listener or Lambda targets can serve real traffic with no healthy targets to show); or under 100 requests a day over 7 days with healthy targets. Targets in state `unavailable` or `initial` count as healthy, since they are not proven idle. Non-application load balancers have no request metric and are judged on healthy targets alone |
| Protected | tagged `env=prod`, `Environment=Production` or `janitor:keep=true`, matched case-insensitively on key and value; reported, never planned |

Each finding carries a `confidence`. A box launched this morning has three hours of data, so it is
flagged with low confidence rather than hidden.

### Repository layout

```
src/cloud_cost_janitor/
  models.py       resources, metrics, findings, plans
  pricing.py      PriceBook interface, static us-east-1 fallback table, monthly estimates
  config.py       settings from .env: token, regions, AWS identity
  providers/      CloudProvider interface; aws/ is the only place boto3 is imported
                  (EC2, EBS, ELBv2, CloudWatch, Price List API, Cost Explorer)
  rules/          pure functions: resource in, finding out
  planner/        ordered teardown plan, snapshot-first steps, plan registry, re-verification
  server/         FastMCP app: scan, plan and teardown tools, bearer auth
trueforge/        agent.json, connectors.json, setup.sh
skills/           cloud-cost-audit, the TrueForge skill with the audit playbook
scripts/          run_mcp_servers.sh, seed_demo.sh, cleanup_demo.sh, smoke_test.sh
tests/            unit and server tests; AWS is mocked with moto, the MCP server is tested in-process
```

Each directory has an `AGENTS.md` with the rules for that directory.

## Quick start

You need Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 for TrueForge, and the AWS CLI.
On macOS you also need Homebrew's git (`brew install git`); TrueForge's sandbox cannot run Apple's
`/usr/bin/git` shim, and skills fail to clone without it.

```bash
git clone https://github.com/ayush22667/cloud-cost-janitor && cd cloud-cost-janitor
uv sync
cp .env.example .env    # set COST_JANITOR_TOKEN and the AWS identity, see below
uv run pytest           # no AWS needed
```

Start TrueForge with its outbound guard allowing loopback (it blocks `127.0.0.1` by default), add a
model under Settings > Models, then register everything:

```bash
OUTBOUND_URL_ALLOWED_HOSTS='["127.0.0.1","localhost"]' npx @truefoundry/trueforge     # terminal 1
scripts/run_mcp_servers.sh                                                             # terminal 2
MODEL=<provider/model> bash trueforge/setup.sh
```

`setup.sh` checks that TrueForge, the model and both servers are up, registers the two connectors and
the skill, and creates the agent. Open http://localhost:8790, go to Agents, and press Try.

`MODEL` is whatever name TrueForge shows under Settings > Models, for example `openai/gpt-5.2`. I
developed it on Kimi K3 behind an OpenAI-compatible gateway.

The skill is required: `setup.sh` registers it from a pinned release tag of this repository (currently
`v0.1.3`; there is no fallback if the registration fails) and fails if the repo is not public or the tag
does not exist. Working from a fork? Set `SKILL_REPO_URL` to your fork (it must be public) and `SKILL_REF`
to a tag or commit in it.

### How the agent is split

The agent definition follows the TrueForge docs: `trueforge/agent.json` holds only the role, the two
connectors with their approval gates, and the runtime toggles. The procedure lives in
`skills/cloud-cost-audit`, a skill in the [Agent Skills](https://agentskills.io) format: `SKILL.md` with
the playbook, `scripts/aggregate_plan.py` the agent runs in the sandbox to total the plan, and
`evals/evals.json` with the three scenarios to re-run after changing it. The frontmatter `description` is
the only text the model sees before it loads the skill, so `setup.sh` registers that exact text.

## Configuration

Everything is read from `.env`. The server refuses to start if the token or the AWS identity is
missing, and it never logs which account it is talking to.

| Variable | Purpose |
|---|---|
| `COST_JANITOR_TOKEN` | bearer token TrueForge sends to the server (any random string) |
| `AWS_PROFILE` | named profile from `~/.aws`. Recommended on a laptop, ideally an SSO profile |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | the alternative, for containers and CI |
| `AWS_ROLE_ARN`, `AWS_EXTERNAL_ID` | optional. Audit another account by assuming a role there |
| `AWS_REGIONS` | comma-separated, default `us-east-1` |
| `JANITOR_HOST`, `JANITOR_PORT` | default `127.0.0.1:8000` |
| `JANITOR_AUDIT_LOG` | append-only JSONL, default `janitor-audit.jsonl` |
| `CLOUD_PROVIDER` | default `aws`, the only one implemented |

Set either a profile or a key pair, not both. A blank `AWS_*` line in `.env` is treated as unset, not as an
empty value.

There is deliberately no fallback to whatever credentials happen to be on the machine.

### Scoping the identity

The server ships no allowlist of its own. Which resources the identity may touch at all is the IAM
policy on the user or role you name in `.env`, and that is yours to write. Keep it small: `Describe*` on
EC2, ELBv2 and CloudWatch for the scan; `CreateSnapshot`, `CreateTags`, `DeleteVolume`,
`TerminateInstances` and `DeleteLoadBalancer` only on resources that carry a tag you choose, such as
`janitor-demo=true`; `pricing:GetProducts` and `ce:GetCostAndUsage` if you want live prices and
`get_actual_spend`. Without the last two, pricing falls back to the static table and `get_actual_spend`
fails with an explanation. If you attach broader rights to seed the demo, remove them before the demo.

When AWS refuses a call, the agent sees `AWS UnauthorizedOperation: IAM denied DeleteVolume` and nothing
else: the principal and account in AWS's own message never reach the model or the audit log.

### Another account

Create a role in the other account that trusts your principal and requires an External ID, with the
same scoped permissions. Put its ARN and the shared string in `.env` as `AWS_ROLE_ARN` and
`AWS_EXTERNAL_ID`. The server assumes the role with STS and refreshes the temporary credentials itself;
`run_mcp_servers.sh` assumes it once more for the official `aws-api` server, so both act as the same
role (that one expires after an hour, restart the script). Deleting the role revokes access. No keys
change hands.

## What stops it deleting the wrong thing

1. TrueForge pauses every `delete_resource`, `mark_for_teardown` and `unmark_teardown` call for Allow or
   Deny. The server only sees approved calls.
2. A call needs a `plan_id` from a report less than an hour old. A server restart forgets all plans, on
   purpose. History lives in the audit log instead (below).
3. The resource is described again right before deletion and refused if it is now attached, running,
   has more healthy targets than the plan expected, gained a protect tag (matched case-insensitively), or
   is gone.
4. Volumes, and the volumes of an instance, are snapshotted first, tagged with the resource's own tags
   plus the plan id. A retry reuses the snapshot instead of taking another, and if the delete fails
   after the snapshot the result still lists the snapshot ids. Pass `wait_for_snapshot=true` to block
   until the snapshot is completed before deleting; without it AWS still finishes an in-progress
   snapshot after the volume is gone.
5. IAM only permits deleting tagged resources (see above).
6. `mark_for_teardown` is an optional two-phase mode: tag now, delete after a grace period of 1 to 90
   days. It is Cloud Custodian's mark-for-op pattern. Unmarking needs the same plan and approval.
7. The agent calls `delete_resource` once per resource and never from a script, so each deletion is
   its own approval.
8. The official AWS server runs with `READ_OPERATIONS_ONLY=true` and every one of its calls is
   approval-gated as well, because its single `call_aws` tool carries no annotations. Its version is
   pinned in `scripts/run_mcp_servers.sh`, and the skill is registered from a release tag, not `main`.
9. Everything the server is asked to do is appended to `janitor-audit.jsonl` (path from
   `JANITOR_AUDIT_LOG`): plans, requests, refusals with reasons, deletions with snapshot ids. It never
   contains the identity or a credential, and AWS error messages are redacted before they reach it or the
   model: an IAM denial becomes `"AWS <Code>: IAM denied <Operation>"` (for example `"AWS
   UnauthorizedOperation: IAM denied DeleteVolume"`), and any other AWS message has ARNs replaced by
   `<arn>` and 12-digit account ids by `<account>`.
10. The agent is told that resource names, tags and descriptions are data, never instructions, since
    anyone who can tag a resource can write text the model will read.

## Demo

```bash
scripts/seed_demo.sh          # about $0.04/hour: an idle t3.micro, two 10 GB volumes, an empty ALB
scripts/run_mcp_servers.sh
```

Then in the chat: "Audit us-east-1 for wasted cloud spend." Pick the volumes. Deny the first approval
and show the volume still exists in the console. Ask again, Allow, and show the snapshot and the
missing volume. TrueForge's Sessions page has the full trace, including the sandbox run and the
approval pause.

The same flow from a terminal: `scripts/smoke_test.sh new "Audit us-east-1..."`, then `answer`,
`approve deny`, `approve allow`. Clean up with `scripts/cleanup_demo.sh --snapshots`.

## Limitations

Prices come from the AWS Price List API for the region being scanned, cached for the life of the
process; if that API is not permitted, a table of us-east-1 list prices in `pricing.py` answers
instead and the `cost_note` says so. Either way the numbers are on-demand estimates: no Savings Plans,
no LCU charges, no data transfer. `get_actual_spend` reads real billed spend from Cost Explorer so
the two can be compared, but only after the account owner has enabled Cost Explorer and IAM access to
billing data; until then the tool explains what to enable.

Idle detection looks at CPU and network only, over a window of 1 to 365 days. Classic ELBs are not covered
(they are a separate, older API that `providers/aws/elb.py` never calls). Auto Scaling group members
are not excluded from idle-instance findings, so a healthy group running below its scale-in threshold can
still be flagged. Only AWS is implemented; `CloudProvider` in `providers/base.py` is the seam for GCP or
Azure, and both publish MCP servers that could take the `aws-api` role. Plans live in memory.

The delete-time check on a load balancer re-reads its state and target health only, not traffic: a load
balancer that went idle-by-traffic in the plan is not re-checked against fresh request counts before
deletion, only against whether it has gained healthy targets since.

TrueForge's local sandbox can only reach PyPI and GitHub, which is why all AWS calls live in the
server and not in generated code.

## Hackathon notes

| Requirement | Where |
|---|---|
| Runs on TrueForge | `trueforge/agent.json`, registered by `setup.sh` |
| Reaches a real system | boto3 against the operator's own account, plus the official AWS MCP server |
| Generated code runs in a sandbox | the aggregation step; the trace shows `sandbox.created` and `exec` |
| Human approval before irreversible actions | `delete_resource` is gated by name and by its `destructiveHint` |
| Own credentials, nothing in the repo | identity named in `.env`, verified at startup, never logged |

The architecture (the cloud-agnostic core, an MCP server with one gated destructive tool, the agent
on top) is mine. I refined and built it with Claude Code, which checked the design against the
installed TrueForge and caught several API shapes I had wrong; `PLAN.md` has the list. Each step was
reviewed and run against a real account. The agent ran on Kimi K3 during development. No credentials
or account identifiers are in this repository.

## License

MIT. See [LICENSE](LICENSE).
