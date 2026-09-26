"""Tag-based protection: resources that must never be torn down, whatever the metrics say."""

from __future__ import annotations

from collections.abc import Iterable


def protection_reason(tags: dict[str, str], protected_tags: Iterable[tuple[str, str]]) -> str | None:
    """Return a human-readable reason if any protected tag matches, else None."""
    for key, value in protected_tags:
        if tags.get(key) == value:
            return f"tag {key}={value}"
    return None
