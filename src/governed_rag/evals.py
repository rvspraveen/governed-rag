"""Leak eval (must be zero) and quality-eval export for rag-eval-gate."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .acl import label_of
from .corpus import chunk_doc, read_corpus
from .errors import GragError
from .policy import Policy
from .service import governed_ask


def _load_cases(path: str | Path, key: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        raise GragError(f"cases file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cases = data.get(key) if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise GragError(f"{p}: expected a non-empty '{key}' list")
    for n, c in enumerate(cases, 1):
        if not isinstance(c, dict) or "as" not in c:
            raise GragError(f"{p}: {key}[{n}] needs an 'as' key (use null for anonymous)")
    return cases


@dataclass
class LeakFinding:
    case: int
    user: str | None
    query: str
    leaked: list[str]
    reason: str


@dataclass
class LeakReport:
    cases: int = 0
    findings: list[LeakFinding] = field(default_factory=list)
    postcheck_blocked: int = 0
    refused: int = 0
    by_user: dict[str, int] = field(default_factory=dict)

    @property
    def leaks(self) -> int:
        return len(self.findings)

    def passed(self, prefilter_expected: bool = True) -> bool:
        # With the pre-filter on, the post-check should never fire; a block is a defect.
        return self.leaks == 0 and (not prefilter_expected or self.postcheck_blocked == 0)


def canaries(corpus_dir: str | Path) -> dict[str, tuple[str, str]]:
    """canary string -> (doc_id, label) for every document that declares one."""
    out = {}
    for d in read_corpus(corpus_dir):
        c = d.meta.get("canary")
        if isinstance(c, str) and c:
            out[c] = (d.doc_id, str(d.acl))
    return out


async def leak_eval(client: Any, policy: Policy, cases_path: str | Path, corpus_dir: str | Path, *, limit: int = 10, strict: bool = True) -> LeakReport:
    cases = _load_cases(cases_path, "cases")
    marks = canaries(corpus_dir)
    rep = LeakReport(cases=len(cases))
    for n, c in enumerate(cases, 1):
        user = c["as"]
        query = str(c.get("query", ""))
        forbidden = set(c.get("forbidden") or [])
        res = await governed_ask(client, policy, user, query, limit=limit, strict=strict)
        allowed = res.labels
        key = user or "anonymous"
        rep.by_user[key] = rep.by_user.get(key, 0) + 1
        rep.postcheck_blocked += len(res.postcheck_blocked)
        rep.refused += res.answer.refused
        leaked, reasons = [], []
        for uri in res.doc_uris:
            label = label_of(uri)
            doc_id = uri.rsplit("/", 1)[-1]
            if label not in allowed:
                leaked.append(uri)
                reasons.append(f"returned {label!r} document")
            elif doc_id in forbidden:
                leaked.append(uri)
                reasons.append("returned a forbidden document")
        for mark, (doc_id, label) in marks.items():
            if label not in allowed and mark in res.answer.text:
                leaked.append(f"canary:{doc_id}")
                reasons.append("restricted canary in answer")
        if leaked:
            rep.findings.append(LeakFinding(n, user, query, leaked, "; ".join(dict.fromkeys(reasons))))
    return rep


async def export_quality(client: Any, policy: Policy, cases_path: str | Path, corpus_dir: str | Path, out_dir: str | Path, *, limit: int = 3) -> int:
    """Write dataset.jsonl and run.jsonl in rag-eval-gate format."""
    cases = _load_cases(cases_path, "cases")
    gold_chunks = {d.doc_id: [c.text for c in chunk_doc(d)] for d in read_corpus(corpus_dir)}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ds, run = [], []
    for n, c in enumerate(cases, 1):
        cid = str(c.get("id") or f"q{n:02d}")
        gold = c.get("gold")
        if gold not in gold_chunks:
            raise GragError(f"quality case {cid}: unknown gold doc {gold!r}")
        question = str(c["question"])
        res = await governed_ask(client, policy, c["as"], question, limit=limit)
        ds.append({"id": cid, "question": question, "ground_truth_context": gold_chunks[gold], "ground_truth_answers": [str(c.get("answer", ""))]})
        run.append({"id": cid, "retrieved_context": [r.content for r in res.results], "answer": res.answer.text})
    (out / "dataset.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in ds), encoding="utf-8")
    (out / "run.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in run), encoding="utf-8")
    return len(ds)
