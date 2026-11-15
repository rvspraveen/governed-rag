from __future__ import annotations

import json

import pytest

from governed_rag.drift import SCHEMA, diff, snapshot
from governed_rag.engine import open_client
from governed_rag.errors import GragError
from governed_rag.evals import _load_cases, canaries, export_quality

from .conftest import EVALS, EXAMPLES


def test_canaries_only_on_restricted_docs():
    marks = canaries(EXAMPLES / "corpus")
    assert len(marks) == 16
    assert {label for _, label in marks.values()} == {"finance", "hr", "legal"}


@pytest.mark.parametrize(("text", "match"), [("cases: []\n", "non-empty"), ("cases:\n  - query: x\n", "needs an 'as' key"), ("- 1\n", "non-empty")])
def test_bad_case_files(tmp_path, text, match):
    p = tmp_path / "c.yaml"
    p.write_text(text)
    with pytest.raises(GragError, match=match):
        _load_cases(p, "cases")


def test_missing_case_file(tmp_path):
    with pytest.raises(GragError, match="not found"):
        _load_cases(tmp_path / "x.yaml", "cases")


async def test_export_quality(db, config, policy, tmp_path):
    async with open_client(db, config, read_only=True) as c:
        n = await export_quality(c, policy, EVALS / "quality_cases.yaml", EXAMPLES / "corpus", tmp_path)
    assert n == 20
    ds = [json.loads(x) for x in (tmp_path / "dataset.jsonl").read_text().splitlines()]
    run = [json.loads(x) for x in (tmp_path / "run.jsonl").read_text().splitlines()]
    assert [d["id"] for d in ds] == [r["id"] for r in run]
    hits = sum(any(g in ctx for ctx in r["retrieved_context"] for g in d["ground_truth_context"]) for d, r in zip(ds, run, strict=True))
    assert hits == 20  # every authorised question retrieves its gold chunk


async def test_export_quality_unknown_gold(db, config, policy, tmp_path):
    cases = tmp_path / "q.yaml"
    cases.write_text("cases:\n  - {as: analyst, question: x, gold: nope}\n")
    async with open_client(db, config, read_only=True) as c:
        with pytest.raises(GragError, match="unknown gold doc"):
            await export_quality(c, policy, cases, EXAMPLES / "corpus", tmp_path)


async def test_snapshot(db, config, policy):
    async with open_client(db, config, read_only=True) as c:
        snap = await snapshot(c, policy, EVALS / "probes.yaml")
    assert snap["schema"] == SCHEMA and len(snap["docs"]) == 24
    assert snap["docs"]["q3-salaries"]["acl"] == "hr"
    analyst_probe = next(p for p in snap["probes"] if p["as"] == "analyst" and p["query"] == "Q3 salaries")
    assert all(u.startswith("acl://public/") for u in analyst_probe["top"])


async def test_snapshot_bad_probes(db, config, policy, tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("probes: 3\n")
    async with open_client(db, config, read_only=True) as c:
        with pytest.raises(GragError, match="'probes' list"):
            await snapshot(c, policy, p)
        with pytest.raises(GragError, match="not found"):
            await snapshot(c, policy, tmp_path / "none.yaml")


def _snap(docs, probes=()):
    return {"schema": SCHEMA, "docs": {k: {"acl": a, "sha256": h} for k, (a, h) in docs.items()}, "probes": list(probes)}


def test_diff(policy):
    before = _snap({"a": ("hr", "1"), "b": ("public", "1"), "c": ("legal", "1"), "gone": ("public", "1")}, [{"as": "analyst", "query": "q", "top": ["x", "y"]}])
    after = _snap({"a": ("public", "1"), "b": ("legal", "2"), "c": ("legal", "1"), "new": ("hr", "1")}, [{"as": "analyst", "query": "q", "top": ["y", "z"]}])
    rep = diff(before, after, policy)
    assert rep.added == ["new"] and rep.removed == ["gone"] and rep.changed == ["b"]
    widened = {c.doc_id: c.new_readers for c in rep.widened}
    assert widened == {"a": ["analyst", "counsel", "finance_mgr"]}
    assert [c.doc_id for c in rep.acl_changes] == ["a", "b"]
    assert rep.probe_overlap == [("analyst", "q", pytest.approx(1 / 3))]
    assert rep.low_overlap == rep.probe_overlap


def test_diff_unknown_label_and_empty_probe(policy):
    rep = diff(
        _snap({"a": ("retired", "1")}, [{"as": None, "query": "q", "top": []}]), _snap({"a": ("hr", "1")}, [{"as": None, "query": "q", "top": []}]), policy
    )
    assert rep.widened[0].new_readers == ["hr_lead"]
    assert rep.probe_overlap == [(None, "q", 1.0)]


def test_diff_rejects_non_snapshots(policy):
    with pytest.raises(GragError, match="before: not a governed-rag snapshot"):
        diff({"schema": "x"}, _snap({}), policy)
