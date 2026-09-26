"""Append-only audit log of what the server was asked to do and what it did.

One JSON object per line. Records tool names, arguments, resource ids, plan ids, snapshot ids,
outcomes and reasons. It never records the AWS identity, account id or any credential.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, event: str, **fields: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
        line = json.dumps(entry, default=str, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


class NullAuditLog(AuditLog):
    """For tests and callers that do not want a file."""

    def __init__(self) -> None:  # noqa: D107
        self.path = Path("/dev/null")
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, event: str, **fields: Any) -> None:
        with self._lock:
            self.entries.append({"event": event, **fields})
