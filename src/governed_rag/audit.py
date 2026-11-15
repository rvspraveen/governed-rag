"""Append-only JSONL audit log. Queries are stored as SHA-256 unless asked otherwise."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def record(
    path: str | Path, *, user: str | None, labels: frozenset[str], query: str, docs: list[str], blocked: list[str], refused: bool, log_query: bool = False
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "user": user,
        "labels": sorted(labels),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "docs": docs,
        "postcheck_blocked": blocked,
        "refused": refused,
    }
    if log_query:
        entry["query"] = query
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry
