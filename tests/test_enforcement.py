"""The security-critical behaviour, tested against a real haiku.rag index."""

from __future__ import annotations

import asyncio

import pytest

from governed_rag.engine import build_config, open_client
from governed_rag.errors import GragError
from governed_rag.evals import leak_eval
from governed_rag.service import governed_ask, governed_search

from .conftest import EVALS, EXAMPLES, unhooked_config

Q = "What were Q3 salaries for analysts and managers?"


async def test_each_user_sees_only_their_labels(db, config, policy):
    async with open_client(db, config, read_only=True) as c:
        for user in (None, "analyst", "finance_mgr", "hr_lead", "counsel"):
            allowed = policy.labels_for(user)
            results, blocked = await governed_search(c, policy, user, "salary forecast dispute Reno revenue", limit=20)
            assert blocked == []
            assert {r.document_uri.split("/")[2] for r in results} <= allowed
            if user is None:
                assert results == []


async def test_salary_question_by_role(db, config, policy):
    async with open_client(db, config, read_only=True) as c:
        analyst = await governed_ask(c, policy, "analyst", Q)
        hr = await governed_ask(c, policy, "hr_lead", Q)
    assert analyst.answer.refused
    assert "acl://hr/q3-salaries" not in analyst.doc_uris
    assert not hr.answer.refused and "95,000" in hr.answer.text
    assert hr.answer.citations[0].uri == "acl://hr/q3-salaries"


async def test_caller_filter_is_combined_not_replaced(db, config, policy):
    from governed_rag.identity import acting_as

    async with open_client(db, config, read_only=True) as c:
        with acting_as("analyst", policy.labels_for("analyst")):
            # A caller-supplied filter that would select an HR doc must not widen access.
            results = await c.search(Q, limit=10, filter="uri LIKE 'acl://hr/%'")
    assert results == []


async def test_postcheck_alone_blocks_and_records(db, policy):
    cfg = build_config(hook_options={"prefilter": False})
    async with open_client(db, cfg, read_only=True) as c:
        results, blocked = await governed_search(c, policy, "analyst", Q, limit=10)
    assert all(r.document_uri.startswith("acl://public/") for r in results)
    assert "acl://hr/q3-salaries" in blocked


async def test_prefilter_alone_blocks(db, policy):
    cfg = build_config(hook_options={"postcheck": False})
    async with open_client(db, cfg, read_only=True) as c:
        results, blocked = await governed_search(c, policy, "analyst", Q, limit=10)
    assert results and all(r.document_uri.startswith("acl://public/") for r in results)
    assert blocked == []


async def test_leak_eval_passes_with_enforcement(db, config, policy):
    async with open_client(db, config, read_only=True) as c:
        rep = await leak_eval(c, policy, EVALS / "leak_cases.yaml", EXAMPLES / "corpus")
    assert rep.cases >= 80 and rep.leaks == 0 and rep.postcheck_blocked == 0 and rep.passed()


async def test_leak_eval_detects_leaks_when_both_layers_off(db, policy):
    """Proves the eval can fail: with enforcement switched off it must find leaks."""
    cfg = build_config(hook_options={"prefilter": False, "postcheck": False})
    async with open_client(db, cfg, read_only=True) as c:
        rep = await leak_eval(c, policy, EVALS / "leak_cases.yaml", EXAMPLES / "corpus")
    assert rep.leaks > 50 and not rep.passed()
    reasons = {f.reason for f in rep.findings}
    assert any("restricted canary in answer" in r for r in reasons)


async def test_prefilter_off_counts_as_defect(db, policy):
    cfg = build_config(hook_options={"prefilter": False})
    async with open_client(db, cfg, read_only=True) as c:
        rep = await leak_eval(c, policy, EVALS / "leak_cases.yaml", EXAMPLES / "corpus")
    assert rep.leaks == 0 and rep.postcheck_blocked > 0
    assert not rep.passed() and rep.passed(prefilter_expected=False)


async def test_missing_hook_fails_closed(db, policy):
    async with open_client(db, unhooked_config(), read_only=True) as c:
        with pytest.raises(GragError, match="hook did not run"):
            await governed_ask(c, policy, "analyst", Q)
        rep = await leak_eval(c, policy, EVALS / "leak_cases.yaml", EXAMPLES / "corpus", strict=False)
    assert rep.leaks > 50


async def test_concurrent_identities_do_not_mix(db, config, policy):
    async with open_client(db, config, read_only=True) as c:
        users = ["analyst", "hr_lead"] * 10
        outs = await asyncio.gather(*(governed_search(c, policy, u, Q, limit=10) for u in users))
    for u, (results, _) in zip(users, outs, strict=True):
        uris = {r.document_uri for r in results}
        assert ("acl://hr/q3-salaries" in uris) == (u == "hr_lead")


async def test_tampered_metadata_is_dropped(tmp_path, config, policy):
    """A document whose URI says public but whose stored ACL says hr never reaches readers."""
    from docling_core.types.doc import DocItemLabel, DoclingDocument
    from haiku.rag.store.models.chunk import Chunk

    path = tmp_path / "t.lancedb"
    text = "Secret salary table for managers."
    async with open_client(path, config, create=True) as c:
        dd = DoclingDocument(name="x")
        dd.add_text(label=DocItemLabel.TEXT, text=text)
        await c.import_document(dd, [Chunk(content=text)], uri="acl://public/x", title="x", metadata={"acl": "hr"})
    async with open_client(path, config, read_only=True) as c:
        results, blocked = await governed_search(c, policy, "analyst", "salary table managers")
    assert results == [] and blocked == ["acl://public/x"]
