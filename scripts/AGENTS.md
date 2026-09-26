# scripts
Operational shell scripts. `seed_demo.sh` and `cleanup_demo.sh` are idempotent (safe to re-run; each skips
what is already created or already gone). `run_mcp_servers.sh` and `smoke_test.sh` are not: `run_mcp_servers.sh`
fails if one of its two ports is already taken, and `smoke_test.sh new` creates a fresh TrueForge session
every time it runs.

`run_mcp_servers.sh` starts both MCP servers. `seed_demo.sh` creates demo waste in the caller's AWS account
tagged `janitor-demo=true` (VPC, idle t3.micro, two unattached volumes, empty ALB) and prints ids.
`cleanup_demo.sh` deletes everything with that tag in dependency order. `smoke_test.sh` drives one turn
against the saved agent from the command line. Scripts must never embed credentials; they read `.env` and
the AWS identity named there.
