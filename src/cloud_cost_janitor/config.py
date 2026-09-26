"""Environment-driven settings. Loaded once at server start; passed explicitly to code that needs it.

Identity policy: the AWS identity must be named explicitly in the environment — a named profile
(recommended) or an access-key pair (containers/CI). There is deliberately no fallback to whatever the
host's default credentials happen to be. Secrets are excluded from ``repr`` so they never reach logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Tags that mark a resource as never-delete. Case-sensitive on key and value, as in AWS.
DEFAULT_PROTECTED_TAGS: tuple[tuple[str, str], ...] = (
    ("env", "prod"),
    ("Environment", "Production"),
    ("janitor:keep", "true"),
)

IDENTITY_HELP = (
    "AWS identity must be set in .env: AWS_PROFILE=<name> (recommended) "
    "or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (containers/CI). See .env.example."
)


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    regions: tuple[str, ...] = ("us-east-1",)
    protected_tags: tuple[tuple[str, str], ...] = DEFAULT_PROTECTED_TAGS
    host: str = "127.0.0.1"
    port: int = 8000
    instance_lookback_days: int = 14
    lb_lookback_days: int = 7
    plan_ttl_seconds: int = 3600
    provider: str = "aws"
    # --- identity (exactly one of profile / key pair; role is optional on top) ---
    aws_profile: str | None = None
    aws_access_key_id: str | None = field(default=None, repr=False)
    aws_secret_access_key: str | None = field(default=None, repr=False)
    aws_session_token: str | None = field(default=None, repr=False)
    aws_role_arn: str | None = None  # audit another account by assuming a role there (no keys stored)
    aws_external_id: str | None = field(default=None, repr=False)


def _validate_identity(s: Settings) -> None:
    has_keys = bool(s.aws_access_key_id and s.aws_secret_access_key)
    half_keys = bool(s.aws_access_key_id) != bool(s.aws_secret_access_key)
    if half_keys:
        raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set together. " + IDENTITY_HELP)
    if s.aws_profile and has_keys:
        raise ValueError("Set either AWS_PROFILE or an access-key pair, not both. " + IDENTITY_HELP)
    if not s.aws_profile and not has_keys:
        raise ValueError(IDENTITY_HELP)
    if s.aws_external_id and not s.aws_role_arn:
        raise ValueError("AWS_EXTERNAL_ID only makes sense together with AWS_ROLE_ARN.")
    if s.aws_external_id and len(s.aws_external_id) < 8:
        raise ValueError("AWS_EXTERNAL_ID must be at least 8 characters (AWS minimum is 2; use a random string).")


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    """Read settings from the environment, after loading ``env_file`` if it exists.

    Raises ``ValueError`` when the bearer token or the AWS identity is missing: the server must never
    start unauthenticated or against an unspecified account.
    """
    if env_file and Path(env_file).exists():
        load_dotenv(env_file, override=False)

    token = _env("COST_JANITOR_TOKEN")
    if not token:
        raise ValueError("COST_JANITOR_TOKEN is not set (see .env.example)")

    regions = tuple(r.strip() for r in os.environ.get("AWS_REGIONS", "us-east-1").split(",") if r.strip())

    settings = Settings(
        token=token,
        regions=regions or ("us-east-1",),
        host=os.environ.get("JANITOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("JANITOR_PORT", "8000")),
        provider=os.environ.get("CLOUD_PROVIDER", "aws").lower(),
        aws_profile=_env("AWS_PROFILE"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=_env("AWS_SESSION_TOKEN"),
        aws_role_arn=_env("AWS_ROLE_ARN"),
        aws_external_id=_env("AWS_EXTERNAL_ID"),
    )
    _validate_identity(settings)
    return settings


__all__ = ["DEFAULT_PROTECTED_TAGS", "IDENTITY_HELP", "Settings", "load_settings"]
