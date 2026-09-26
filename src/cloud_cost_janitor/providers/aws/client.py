"""boto3 session and per-region clients. Credentials come from the host chain; never from config files here."""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.config import Config

_RETRY = Config(retries={"max_attempts": 5, "mode": "standard"})


class AwsClients:
    def __init__(self, profile: str | None = None) -> None:
        self._session = boto3.Session(profile_name=profile) if profile else boto3.Session()

    @lru_cache(maxsize=64)  # noqa: B019 - one client per (service, region) for the process lifetime
    def _client(self, service: str, region: str):
        return self._session.client(service, region_name=region, config=_RETRY)

    def ec2(self, region: str):
        return self._client("ec2", region)

    def cloudwatch(self, region: str):
        return self._client("cloudwatch", region)

    def elbv2(self, region: str):
        return self._client("elbv2", region)

    def list_regions(self) -> list[str]:
        resp = self.ec2("us-east-1").describe_regions(AllRegions=False)
        return sorted(r["RegionName"] for r in resp["Regions"])
