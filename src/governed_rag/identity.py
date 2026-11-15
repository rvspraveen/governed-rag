"""Per-request identity, carried in a context variable.

haiku.rag hooks receive the client and the search request, not the caller.
A ContextVar gives each asyncio task its own identity, so concurrent requests
for different users cannot see each other's labels.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class AccessContext:
    user: str | None
    labels: frozenset[str]
    hook_calls: int = 0
    prefilter_applied: int = 0
    postcheck_blocked: list[str] = field(default_factory=list)


_CURRENT: ContextVar[AccessContext | None] = ContextVar("governed_rag_access", default=None)


def current() -> AccessContext | None:
    return _CURRENT.get()


@contextmanager
def acting_as(user: str | None, labels: frozenset[str]) -> Iterator[AccessContext]:
    ctx = AccessContext(user=user, labels=frozenset(labels))
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)
