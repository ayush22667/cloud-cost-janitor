# providers/aws
The only place boto3 is imported. `client.py` builds per-region clients from an **explicit**
`AwsCredentials` (profile or key pair from `.env`; optional `role_arn`/`external_id` → STS AssumeRole with
auto-refreshing temporary credentials). Never construct `boto3.Session()` without arguments. `verify()`
proves the credentials work and returns nothing; no code here may log or return the identity.
`ec2.py` (instances + CloudWatch CPU/network), `ebs.py` (volumes, snapshots), `elb.py` (elbv2, target
health, RequestCount) return `models.py` objects. `provider.py` wires them into `AwsProvider`.
CloudWatch: use `period=3600` (14 days at 5-min would exceed the 1440-datapoint limit).
Every write path honours `dry_run` and the tag guard from `config.py`. Tests: `tests/providers/` with moto.
