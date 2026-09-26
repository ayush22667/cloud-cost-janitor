"""Entry point: ``uv run cloud-cost-janitor`` or ``python -m cloud_cost_janitor.server``."""

from __future__ import annotations

import sys

from cloud_cost_janitor.config import load_settings
from cloud_cost_janitor.providers import get_provider
from cloud_cost_janitor.server.app import create_app


def main() -> None:
    try:
        settings = load_settings()
        provider = get_provider(settings)
    except Exception as e:  # configuration errors should be readable, not a traceback
        print(f"cloud-cost-janitor: {e}", file=sys.stderr)
        sys.exit(2)

    mode = "LIVE (ALLOW_DELETE=true)" if settings.allow_delete else "dry-run"
    guard = f"{settings.delete_only_tag[0]}={settings.delete_only_tag[1]}" if settings.delete_only_tag else "off"
    print(
        f"cloud-cost-janitor: provider={provider.name} regions={','.join(settings.regions)} "
        f"mode={mode} delete_only_tag={guard} -> http://{settings.host}:{settings.port}/mcp",
        file=sys.stderr,
    )
    create_app(settings, provider).run(transport="http", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
