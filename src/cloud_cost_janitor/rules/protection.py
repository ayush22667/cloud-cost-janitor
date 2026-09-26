"""Tag-based protection: resources that must never be torn down, whatever the metrics say.

Matching is case-insensitive on both key and value. AWS tags are case-sensitive, so this is stricter
than AWS itself: ``Environment=production`` and ``ENV=PROD`` both protect. Over-protecting is the safe
direction for a tool that deletes things.
"""

from __future__ import annotations

from collections.abc import Iterable


def protection_reason(tags: dict[str, str], protected_tags: Iterable[tuple[str, str]]) -> str | None:
    """Return a human-readable reason if any protected tag matches, else None."""
    folded = {k.casefold(): v.casefold() for k, v in tags.items()}
    for key, value in protected_tags:
        if folded.get(key.casefold()) == value.casefold():
            return f"tag {key}={value}"
    return None
