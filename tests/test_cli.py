from __future__ import annotations

import json
import shutil

import pytest

from governed_rag import __version__
from governed_rag.cli import main

from .conftest import EVALS, EXAMPLES

P = ["-p", str(EXAMPLES / "policy.yaml")]


@pytest.fixture
def dbcopy(db, tmp_path):
    dst = tmp_path / "db.lancedb"
    shutil.copytree(db, dst)
    return ["--db", str(dst)]


def test_ingest_bad_and_good(tmp_path, capsys):
    db = ["--db", str(tmp_path / "db.lancedb")]
    assert main(["ingest", str(EXAMPLES / "corpus_bad"), *P, *db]) == 1
    assert "nothing was written" in capsys.readouterr().out
    assert main(["ingest", str(EXAMPLES / "corpus"), *P, *db]) == 0
    assert "24 added" in capsys.readouterr().out


def test_ingest_with_contract(tmp_path, capsys):
    pytest.importorskip("corpusgate")
    db = ["--db", str(tmp_path / "db.lancedb")]
    assert main(["ingest", str(EXAMPLES / "corpus"), "-c", str(EXAMPLES / "contract.yaml"), *P, *db]) == 0
    out = capsys.readouterr().out
    assert "contract passed" in out and "warn:" in out
    strict = tmp_path / "strict.yaml"
    strict.write_text("version: 1\nrag:\n  - test: unique_ids\n    column: doc_id\n")
    assert main(["ingest", str(EXAMPLES / "corpus"), "-c", str(strict), *P, "--db", str(tmp_path / "db2")]) == 0
    strict.write_text("version: 1\nrag:\n  - test: chunk_length\n    column: text\n    min_chars: 5000\n    max_chars: 9000\n")
    assert main(["ingest", str(EXAMPLES / "corpus"), "-c", str(strict), *P, "--db", str(tmp_path / "db3")]) == 1
    assert "contract FAILED" in capsys.readouterr().out


def test_ask(dbcopy, tmp_path, capsys):
    audit = tmp_path / "audit.jsonl"
    q = "What were Q3 salaries for analysts and managers?"
    assert main(["ask", q, "--as", "hr_lead", "--audit", str(audit), *P, *dbcopy]) == 0
    out = capsys.readouterr().out
    assert "95,000" in out and "acl://hr/q3-salaries" in out
    assert main(["ask", q, "--as", "analyst", "--json", "--audit", str(audit), "--log-query", *P, *dbcopy]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["refused"] is True and payload["labels"] == ["public"]
    assert main(["ask", q, "--audit", str(audit), *P, *dbcopy]) == 0
    assert "can read: nothing" in capsys.readouterr().out
    entries = [json.loads(x) for x in audit.read_text().splitlines()]
    assert [e["user"] for e in entries] == ["hr_lead", "analyst", None]
    assert "query" not in entries[0] and entries[1]["query"] == q
    assert entries[0]["docs"][0] == "acl://hr/q3-salaries" and entries[2]["docs"] == []


def test_ask_unknown_user_exit_2(dbcopy, capsys):
    assert main(["ask", "x", "--as", "mallory", *P, *dbcopy]) == 2
    assert "unknown user" in capsys.readouterr().err


def test_leak_and_quality(dbcopy, tmp_path, capsys):
    assert main(["eval", "leak", "--corpus", str(EXAMPLES / "corpus"), "--cases", str(EVALS / "leak_cases.yaml"), *P, *dbcopy]) == 0
    assert "leak eval PASS: leaks 0/" in capsys.readouterr().out
    out = tmp_path / "q"
    assert main(["eval", "quality", "--corpus", str(EXAMPLES / "corpus"), "--cases", str(EVALS / "quality_cases.yaml"), "-o", str(out), *P, *dbcopy]) == 0
    assert (out / "run.jsonl").exists()


def test_leak_failure_output(dbcopy, tmp_path, capsys, monkeypatch):
    from governed_rag import engine

    real = engine.build_config
    monkeypatch.setattr("governed_rag.cli.build_config", lambda o=None: real(o, hook_options={"prefilter": False, "postcheck": False}))
    assert main(["eval", "leak", "--corpus", str(EXAMPLES / "corpus"), "--cases", str(EVALS / "leak_cases.yaml"), *P, *dbcopy]) == 1
    out = capsys.readouterr().out
    assert "leak eval FAIL" in out and "restricted canary in answer" in out
    monkeypatch.setattr("governed_rag.cli.build_config", lambda o=None: real(o, hook_options={"prefilter": False}))
    assert main(["eval", "leak", "--corpus", str(EXAMPLES / "corpus"), "--cases", str(EVALS / "leak_cases.yaml"), *P, *dbcopy]) == 1
    assert "investigate the filter" in capsys.readouterr().out


def test_snapshot_and_drift(dbcopy, tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert main(["snapshot", "--probes", str(EVALS / "probes.yaml"), "-o", str(a), *P, *dbcopy]) == 0
    corpus = tmp_path / "c"
    shutil.copytree(EXAMPLES / "corpus", corpus)
    p = corpus / "q3-salaries.md"
    p.write_text(p.read_text().replace("acl: hr", "acl: public"))
    (corpus / "offices.md").unlink()
    assert main(["ingest", str(corpus), *P, *dbcopy]) == 0
    assert main(["snapshot", "--probes", str(EVALS / "probes.yaml"), "-o", str(b), *P, *dbcopy]) == 0
    capsys.readouterr()
    assert main(["drift", "--before", str(a), "--after", str(b), *P]) == 1
    out = capsys.readouterr().out
    assert "acl q3-salaries: hr -> public now readable by analyst, counsel, finance_mgr" in out
    assert "removed: offices" in out and "probe [analyst]" in out
    assert main(["drift", "--before", str(a), "--after", str(b), "--allow-widening", *P]) == 0
    assert main(["drift", "--before", str(a), "--after", str(a), *P]) == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["ask", "x", "--db", "/nonexistent/db"],
        ["drift", "--before", "/nope.json", "--after", "/nope.json"],
        ["ingest", "/nonexistent-dir"],
        ["frobnicate"],
        [],
    ],
)
def test_usage_errors_exit_2(argv):
    assert main([*argv, *P] if argv and argv[0] != "frobnicate" else argv) == 2


def test_bad_json_snapshot(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{")
    assert main(["drift", "--before", str(p), "--after", str(p), *P]) == 2


def test_version(capsys):
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
