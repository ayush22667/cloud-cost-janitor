# providers/aws
The only place boto3 is imported. `client.py` builds per-region clients from an **explicit**
`AwsCredentials` (profile or key pair from `.env`; optional `role_arn`/`external_id` → STS AssumeRole with
auto-refreshing temporary credentials, built explicitly from the base session's profile, never from a
no-argument `boto3.Session()`). `verify()` proves the credentials work and returns nothing; no code here
may log or return the identity.
`ec2.py` (instances, volumes and snapshots share this one module — no separate volumes module),
`elb.py` (elbv2, target health, RequestCount), `metrics.py` (CloudWatch stats folded into daily figures),
`prices.py` (live AWS Price List API lookups), `spend.py` (Cost Explorer) return `models.py` objects or
plain values. `provider.py` wires them all into `AwsProvider`.
CloudWatch: `metrics.period_for(lookback_days)` scales the period with the window so datapoints stay under
the 1,440-per-call limit — `3600` s up to 60 days, larger multiples of 3600 beyond that.
Write methods perform the real operation; the server decides whether to call them. Tests: `tests/providers/` with moto.
