# providers
`base.py` defines `CloudProvider`, the abstract interface every cloud must implement: list instances /
volumes / load balancers with metrics, tag, snapshot, delete. Everything above this package talks to
`CloudProvider` only and receives objects from `models.py`. One subpackage per cloud (`aws/` today).
Adding a cloud = new subpackage implementing `CloudProvider`; no changes elsewhere.
