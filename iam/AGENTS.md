# iam
Least-privilege IAM artifacts. `janitor-read-policy.json` = everything the audit needs (Describe*,
CloudWatch, GetCallerIdentity). `janitor-actions-policy.json` = snapshot/tag/delete, every statement
conditioned on `aws:ResourceTag/janitor-demo=true` so IAM itself refuses untagged resources even if the
server's own guard failed. `janitor-demo-seed-policy.json` = extra rights for `scripts/seed_demo.sh` / `cleanup_demo.sh` only (remove
after the demo; includes the service-linked-role grant a brand-new account needs for its first load
balancer). `janitor-pricing-policy.json` = optional Price List + Cost Explorer read access.
`cross-account-role.yaml` = CloudFormation for another account's owner:
a role trusting the janitor's principal with an External ID (delete the stack to revoke). Keep the
JSON and the YAML in sync; `tests/test_iam.py` checks the tag condition is present on every action.
