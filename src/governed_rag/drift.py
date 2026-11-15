"""Index snapshots and drift reports, including ACL changes that widen exposure."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .acl import SCHEME, label_of
from .errors import GragError
from .policy import Policy
from .service import governed_search

SCHEMA = "governed-rag/snapshot@1"


def _probes(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    p = Path(path)
    if not p.is_file():
        raise GragError(f"probes file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    probes = data.get("probes") if isinstance(data, dict) else None
    if not isinstance(probes, list):
        raise GragError(f"{p}: expected a 'probes' list")
    return probes


async def snapshot(client: Any, policy: Policy, probes_path: str | Path | None = None, k: int = 5) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    for d in await client.list_documents(include_content=True):
        if not d.uri or not d.uri.startswith(SCHEME):
            continue
        meta = d.metadata or {}
        doc_id = str(meta.get("doc_id") or d.uri.rsplit("/", 1)[-1])
        docs[doc_id] = {
            "uri": d.uri,
            "acl": label_of(d.uri),
            "title": d.title,
            "sha256": hashlib.sha256((d.content or "").encode("utf-8")).hexdigest(),
        }
    probes = []
    for pr in _probes(probes_path):
        results, _ = await governed_search(client, policy, pr.get("as"), str(pr["query"]), limit=k)
        uris = list(dict.fromkeys(r.document_uri for r in results if r.document_uri))
        probes.append({"as": pr.get("as"), "query": pr["query"], "top": uris})
    return {"schema": SCHEMA, "tool": f"governed-rag {__version__}", "k": k, "docs": dict(sorted(docs.items())), "probes": probes}


@dataclass
class AclChange:
    doc_id: str
    before: str | None
    after: str | None
    new_readers: list[str]

    @property
    def widened(self) -> bool:
        return bool(self.new_readers)


@dataclass
class DriftReport:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    acl_changes: list[AclChange] = field(default_factory=list)
    probe_overlap: list[tuple[str | None, str, float]] = field(default_factory=list)
    min_overlap: float = 0.6

    @property
    def widened(self) -> list[AclChange]:
        return [c for c in self.acl_changes if c.widened]

    @property
    def low_overlap(self) -> list[tuple[str | None, str, float]]:
        return [p for p in self.probe_overlap if p[2] < self.min_overlap]


def _check(s: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(s, dict) or s.get("schema") != SCHEMA or not isinstance(s.get("docs"), dict):
        raise GragError(f"{label}: not a governed-rag snapshot")
    return s


def diff(before: dict[str, Any], after: dict[str, Any], policy: Policy, min_overlap: float = 0.6) -> DriftReport:
    b, a = _check(before, "before")["docs"], _check(after, "after")["docs"]
    rep = DriftReport(min_overlap=min_overlap)
    rep.added = sorted(set(a) - set(b))
    rep.removed = sorted(set(b) - set(a))
    for doc_id in sorted(set(a) & set(b)):
        if a[doc_id]["sha256"] != b[doc_id]["sha256"]:
            rep.changed.append(doc_id)
        if a[doc_id]["acl"] != b[doc_id]["acl"]:
            old = policy.audience(b[doc_id]["acl"]) if b[doc_id]["acl"] in policy.labels else frozenset()
            new = policy.audience(a[doc_id]["acl"]) if a[doc_id]["acl"] in policy.labels else frozenset()
            rep.acl_changes.append(AclChange(doc_id, b[doc_id]["acl"], a[doc_id]["acl"], sorted(new - old)))
    before_probes = {(p.get("as"), p["query"]): set(p["top"]) for p in before.get("probes", [])}
    for p in after.get("probes", []):
        key = (p.get("as"), p["query"])
        if key in before_probes:
            x, y = before_probes[key], set(p["top"])
            rep.probe_overlap.append((key[0], key[1], 1.0 if not (x | y) else len(x & y) / len(x | y)))
    return rep
