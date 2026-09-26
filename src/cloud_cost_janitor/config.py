"""Environment-driven settings. Loaded once at server start; passed explicitly to code that needs it."""

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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_tag(value: str | None) -> tuple[str, str] | None:
    """'key=value' -> ('key', 'value'); empty/None -> None."""
    if not value or "=" not in value:
        return None
    key, _, val = value.partition("=")
    key, val = key.strip(), val.strip()
    return (key, val) if key and val else None


@dataclass(frozen=True)
class Settings:
    token: str
    regions: tuple[str, ...] = ("us-east-1",)
    allow_delete: bool = False
    delete_only_tag: tuple[str, str] | None = ("janitor-demo", "true")
    protected_tags: tuple[tuple[str, str], ...] = DEFAULT_PROTECTED_TAGS
    host: str = "127.0.0.1"
    port: int = 8000
    instance_lookback_days: int = 14
    lb_lookback_days: int = 7
    plan_ttl_seconds: int = 3600
    aws_profile: str | None = None
    provider: str = "aws"

    @property
    def dry_run(self) -> bool:
        return not self.allow_delete


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    """Read settings from the environment, after loading ``env_file`` if it exists.

    Raises ``ValueError`` when ``COST_JANITOR_TOKEN`` is missing: the server must never start unauthenticated.
    """
    if env_file and Path(env_file).exists():
        load_dotenv(env_file, override=False)

    token = os.environ.get("COST_JANITOR_TOKEN", "").strip()
    if not token:
        raise ValueError("COST_JANITOR_TOKEN is not set (see .env.example)")

    regions = tuple(r.strip() for r in os.environ.get("AWS_REGIONS", "us-east-1").split(",") if r.strip())
    delete_only_raw = os.environ.get("DELETE_ONLY_TAGGED")
    delete_only_tag = _parse_tag(delete_only_raw) if delete_only_raw is not None else ("janitor-demo", "true")

    return Settings(
        token=token,
        regions=regions or ("us-east-1",),
        allow_delete=_truthy(os.environ.get("ALLOW_DELETE")),
        delete_only_tag=delete_only_tag,
        host=os.environ.get("JANITOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("JANITOR_PORT", "8000")),
        aws_profile=os.environ.get("AWS_PROFILE") or None,
        provider=os.environ.get("CLOUD_PROVIDER", "aws").lower(),
    )


__all__ = ["DEFAULT_PROTECTED_TAGS", "Settings", "load_settings"]
