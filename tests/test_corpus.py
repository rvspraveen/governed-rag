from __future__ import annotations

import pytest

from governed_rag.corpus import check_corpus, chunk_doc, read_corpus, read_doc
from governed_rag.errors import CorpusError

from .conftest import EXAMPLES, write_doc


def test_example_corpus(policy):
    docs = read_corpus(EXAMPLES / "corpus")
    assert len(docs) == 24
    assert check_corpus(docs, policy).passed
    hr = next(d for d in docs if d.doc_id == "q3-salaries")
    assert hr.acl == "hr" and hr.uri == "acl://hr/q3-salaries" and hr.meta["canary"].startswith("GRAG-CANARY-")


def test_bad_corpus_problems(policy):
    probs = check_corpus(read_corpus(EXAMPLES / "corpus_bad"), policy).problems
    assert probs == [
        "board-minutes.md: missing 'acl' in front matter",
        "exec-comp.md: acl 'executive' is not a label in the policy (finance, hr, legal, public)",
    ]


def test_more_problems(tmp_path, policy):
    write_doc(tmp_path, "Bad_Name", "public", "x")
    write_doc(tmp_path, "empty", "public", "")
    write_doc(tmp_path, "listacl", "public", "x").write_text("---\nacl: [hr]\n---\nbody\n")
    probs = " | ".join(check_corpus(read_corpus(tmp_path), policy).problems)
    assert "Bad_Name.md: file name must be" in probs
    assert "empty.md: empty body" in probs
    assert "listacl.md: acl ['hr']" in probs


def test_duplicate_ids(tmp_path, policy):
    d = read_doc(write_doc(tmp_path, "a", "public", "x"))
    assert "duplicate doc id 'a'" in check_corpus([d, d], policy).problems[0]


def test_no_front_matter(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("just text\n")
    d = read_doc(p)
    assert d.meta == {} and d.acl is None and d.title == "plain"


@pytest.mark.parametrize(("text", "match"), [("---\n: [\n---\nx\n", "invalid front matter"), ("---\n- a\n---\nx\n", "must be a mapping")])
def test_bad_front_matter(tmp_path, text, match):
    p = tmp_path / "x.md"
    p.write_text(text)
    with pytest.raises(CorpusError, match=match):
        read_doc(p)


def test_unreadable(tmp_path):
    p = tmp_path / "bin.md"
    p.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(CorpusError, match="cannot read"):
        read_doc(p)


def test_read_corpus_errors(tmp_path):
    with pytest.raises(CorpusError, match="not found"):
        read_corpus(tmp_path / "nope")
    with pytest.raises(CorpusError, match=r"no \.md files"):
        read_corpus(tmp_path)


def test_chunking(tmp_path):
    body = "\n\n".join(["a" * 300, "b" * 300, "c" * 300, "d" * 2000])
    chunks = chunk_doc(read_doc(write_doc(tmp_path, "long", "public", body)), max_chars=800)
    assert [len(c.text) for c in chunks] == [601, 300, 2000]
    assert [c.chunk_id for c in chunks] == ["long#0", "long#1", "long#2"]
    assert chunks[0].to_row()["acl"] == "public"
