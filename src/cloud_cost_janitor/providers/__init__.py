"""Cloud provider adapters. Use ``get_provider(settings)`` to obtain the configured one."""

from __future__ import annotations

from cloud_cost_janitor.config import Settings
from cloud_cost_janitor.providers.base import CloudProvider, ProviderError


def get_provider(settings: Settings) -> CloudProvider:
    if settings.provider == "aws":
        from cloud_cost_janitor.providers.aws.client import AwsCredentials
        from cloud_cost_janitor.providers.aws.provider import AwsProvider

        return AwsProvider(credentials=AwsCredentials.from_settings(settings))
    raise ProviderError(
        f"Unsupported CLOUD_PROVIDER={settings.provider!r}. Only 'aws' is implemented; "
        "add a subclass of CloudProvider under providers/<cloud>/ to support another cloud."
    )


__all__ = ["CloudProvider", "ProviderError", "get_provider"]
