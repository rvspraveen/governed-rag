"""Governed search and ask: identity -> hooked search -> answer -> audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import audit
from .answer import Answer, extractive_answer
from .errors import GragError
from .identity import acting_as
from .policy import Policy


@dataclass
class AskResult:
    user: str | None
    labels: frozenset[str]
    results: list[Any]
    answer: Answer
    postcheck_blocked: list[str] = field(default_factory=list)

    @property
    def doc_uris(self) -> list[str]:
        return list(dict.fromkeys(r.document_uri for r in self.results if r.document_uri))


async def governed_search(client: Any, policy: Policy, user: str | None, query: str, limit: int = 5, strict: bool = True) -> tuple[list[Any], list[str]]:
    labels = policy.labels_for(user)
    with acting_as(user, labels) as ctx:
        results = await client.search(query, limit=limit)
    if strict and ctx.hook_calls == 0:
        # Fail closed: the database was opened without the enforcement hook.
        raise GragError("the governed_acl hook did not run; refusing to return results")
    return results, list(ctx.postcheck_blocked)


async def governed_ask(
    client: Any,
    policy: Policy,
    user: str | None,
    question: str,
    *,
    limit: int = 5,
    audit_path: str | Path | None = None,
    log_query: bool = False,
    strict: bool = True,
) -> AskResult:
    results, blocked = await governed_search(client, policy, user, question, limit=limit, strict=strict)
    ans = extractive_answer(question, results)
    out = AskResult(user=user, labels=policy.labels_for(user), results=results, answer=ans, postcheck_blocked=blocked)
    if audit_path is not None:
        audit.record(audit_path, user=user, labels=out.labels, query=question, docs=out.doc_uris, blocked=blocked, refused=ans.refused, log_query=log_query)
    return out
