from __future__ import annotations

import builtins

import pytest

from governed_rag.engine import open_client
from governed_rag.errors import GragError
from governed_rag.ingest import ingest

from .conftest import EXAMPLES, write_doc


async def test_bad_corpus_writes_nothing(tmp_path, policy, config):
    db = tmp_path / "db.lancedb"
    res = await ingest(EXAMPLES / "corpus_bad", policy, db, config)
    assert not res.passed and len(res.problems) == 2
    assert not db.exists()


async def test_contract_pass_with_pii_warning(tmp_path, policy, config):
    pytest.importorskip("corpusgate")
    db = tmp_path / "db.lancedb"
    res = await ingest(EXAMPLES / "corpus", policy, db, config, contract=EXAMPLES / "contract.yaml")
    assert res.passed and res.contract is not None
    assert res.contract.errors == [] and any("email" in w for w in res.contract.warnings)


async def test_contract_failure_writes_nothing(tmp_path, policy, config):
    pytest.importorskip("corpusgate")
    strict = tmp_path / "strict.yaml"
    strict.write_text("version: 1\nrag:\n  - test: chunk_length\n    column: text\n    min_chars: 5000\n    max_chars: 9000\n")
    db = tmp_path / "db.lancedb"
    res = await ingest(EXAMPLES / "corpus", policy, db, config, contract=strict)
    assert not res.passed and res.contract and res.contract.errors
    assert not db.exists()


async def test_contract_errors(tmp_path, policy, config, monkeypatch):
    pytest.importorskip("corpusgate")
    with pytest.raises(GragError, match="contract"):
        await ingest(EXAMPLES / "corpus", policy, tmp_path / "db", config, contract=tmp_path / "missing.yaml")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("corpusgate"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(GragError, match="needs corpusgate"):
        await ingest(EXAMPLES / "corpus", policy, tmp_path / "db", config, contract=EXAMPLES / "contract.yaml")


async def test_sync_semantics(tmp_path, policy, config):
    corpus = tmp_path / "c"
    corpus.mkdir()
    write_doc(corpus, "a", "public", "Alpha turbines spin.")
    write_doc(corpus, "b", "hr", "Bravo salaries are private.")
    write_doc(corpus, "c", "public", "Charlie office is in Reno.")
    db = tmp_path / "db.lancedb"
    first = await ingest(corpus, policy, db, config)
    assert sorted(first.added) == ["a", "b", "c"]

    write_doc(corpus, "a", "public", "Alpha turbines spin faster now.")  # content change
    write_doc(corpus, "b", "public", "Bravo salaries are private.")  # ACL change -> new URI
    (corpus / "c.md").unlink()  # removed
    second = await ingest(corpus, policy, db, config)
    assert second.updated == ["a"] and second.added == ["b"]
    assert sorted(second.removed) == ["acl://hr/b", "acl://public/c"]

    async with open_client(db, config, read_only=True) as client:
        uris = sorted(d.uri for d in await client.list_documents())
    assert uris == ["acl://public/a", "acl://public/b"]
