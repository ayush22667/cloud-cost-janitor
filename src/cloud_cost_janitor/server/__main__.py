"""Entry point: ``uv run cloud-cost-janitor`` or ``python -m cloud_cost_janitor.server``.

Startup verifies that the configured AWS identity works and then serves. Nothing about that
identity — account, principal, key id — is ever printed.
"""

from __future__ import annotations

import sys

from botocore.exceptions import BotoCoreError

from cloud_cost_janitor.config import load_settings
from cloud_cost_janitor.providers import ProviderError, get_provider
from cloud_cost_janitor.server.app import create_app


def main() -> None:
    try:
        settings = load_settings()
        provider = get_provider(settings)
    except (ValueError, ProviderError, BotoCoreError) as e:  # configuration errors should be readable, not a traceback
        print(f"cloud-cost-janitor: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        provider.verify_credentials()  # fail fast; no point serving without working credentials
    except ProviderError as e:
        print(f"cloud-cost-janitor: AWS credentials rejected: {e}", file=sys.stderr)
        sys.exit(2)

    print(
        f"cloud-cost-janitor: provider={provider.name} regions={','.join(settings.regions)} "
        f"-> http://{settings.host}:{settings.port}/mcp",
        file=sys.stderr,
    )
    # stateless_http: no per-client session ids, so a server restart is invisible to TrueForge's
    # long-lived connector (otherwise it gets "Session not found" until it reinitialises).
    create_app(settings, provider).run(transport="http", host=settings.host, port=settings.port, stateless_http=True)


if __name__ == "__main__":
    main()
