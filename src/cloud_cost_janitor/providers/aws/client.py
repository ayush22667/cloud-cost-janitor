"""boto3 session and per-region clients, built from an explicitly named identity.

There is no ``boto3.Session()`` without arguments anywhere in this project: the caller must say which
profile or key pair to use. To audit a *different* account, pass ``role_arn`` (and ideally
``external_id``): the base identity is used only to call ``sts:AssumeRole`` and every service client
then runs on auto-refreshing temporary credentials for that account. Nothing about the resolved
identity is logged or stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.credentials import DeferredRefreshableCredentials, create_assume_role_refresher

from cloud_cost_janitor.config import Settings

_RETRY = Config(retries={"max_attempts": 5, "mode": "standard"})
ROLE_SESSION_NAME = "cloud-cost-janitor"


@dataclass(frozen=True)
class AwsCredentials:
    """Which identity to use. Secrets are hidden from repr so they never appear in logs or tracebacks."""

    profile: str | None = None
    access_key_id: str | None = field(default=None, repr=False)
    secret_access_key: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    role_arn: str | None = None
    external_id: str | None = field(default=None, repr=False)

    @classmethod
    def from_settings(cls, s: Settings) -> AwsCredentials:
        return cls(
            profile=s.aws_profile,
            access_key_id=s.aws_access_key_id,
            secret_access_key=s.aws_secret_access_key,
            session_token=s.aws_session_token,
            role_arn=s.aws_role_arn,
            external_id=s.aws_external_id,
        )

    def base_session(self) -> boto3.Session:
        if self.profile:
            return boto3.Session(profile_name=self.profile)
        if self.access_key_id and self.secret_access_key:
            return boto3.Session(
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                aws_session_token=self.session_token,
            )
        raise ValueError("AwsCredentials needs a profile or an access-key pair")


def _assumed_session(credentials: AwsCredentials, base: boto3.Session) -> boto3.Session:
    params: dict[str, str] = {"RoleArn": credentials.role_arn or "", "RoleSessionName": ROLE_SESSION_NAME}
    if credentials.external_id:
        params["ExternalId"] = credentials.external_id
    refresher = create_assume_role_refresher(base.client("sts", config=_RETRY), params)
    creds = DeferredRefreshableCredentials(refresh_using=refresher, method="assume-role")
    # A second session built exactly like the base one (same explicit profile or key pair, never the host
    # default chain), with botocore's documented way to plug refreshable credentials into it.
    session = credentials.base_session()
    session._session._credentials = creds
    return session


class AwsClients:
    def __init__(self, credentials: AwsCredentials) -> None:
        base = credentials.base_session()
        self._session = _assumed_session(credentials, base) if credentials.role_arn else base

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

    def verify(self) -> None:
        """Prove the credentials work (raises otherwise). Deliberately returns nothing about who we are."""
        self._client("sts", "us-east-1").get_caller_identity()
