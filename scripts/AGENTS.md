# scripts
Operational shell scripts, all idempotent and safe to re-run. `run_mcp_servers.sh` starts both MCP
servers. `seed_demo.sh` creates demo waste in the caller's AWS account tagged `janitor-demo=true` (VPC,
idle t3.micro, two unattached volumes, empty ALB) and prints ids. `cleanup_demo.sh` deletes everything with
that tag in dependency order. `smoke_test.sh` runs one turn against the saved agent. Scripts must never
embed credentials; they read `.env` and the AWS credential chain.
