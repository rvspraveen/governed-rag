"""The enforcement hook, registered with haiku.rag as the `governed_acl` entry point.

Two independent layers:

1. before_search: inject a document filter limited to the caller's labels.
   No identity, or no labels, means a filter that matches nothing.
2. after_search: re-check every result's label from both its URI and its stored
   metadata. Mismatches are dropped and recorded. With layer 1 working this
   never triggers, so any drop is a defect worth investigating.
"""

from __future__ import annotations

from typing import Any

from haiku.rag.hooks import Hook

from . import identity
from .acl import label_of, prefilter


class GovernedAclHook(Hook):
    def __init__(self, prefilter: bool = True, postcheck: bool = True):
        # Both layers are always on in the grag CLI. The switches exist so the
        # test suite can prove each layer blocks leaks on its own.
        self.prefilter = prefilter
        self.postcheck = postcheck

    async def before_search(self, client: Any, request: Any) -> Any:
        ctx = identity.current()
        if ctx:
            ctx.hook_calls += 1
        if not self.prefilter:
            return request
        clause = prefilter(ctx.labels if ctx else frozenset())
        request.filter = f"({request.filter}) AND {clause}" if request.filter else clause
        if ctx:
            ctx.prefilter_applied += 1
        return request

    async def after_search(self, client: Any, request: Any, results: list[Any]) -> list[Any]:
        if not self.postcheck:
            return results
        ctx = identity.current()
        allowed = ctx.labels if ctx else frozenset()
        kept = []
        for r in results:
            uri_label = label_of(r.document_uri)
            meta_label = (r.document_meta or {}).get("acl")
            if uri_label is not None and uri_label == meta_label and uri_label in allowed:
                kept.append(r)
            elif ctx is not None:
                ctx.postcheck_blocked.append(r.document_uri or "<no uri>")
        return kept
