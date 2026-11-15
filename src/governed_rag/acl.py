"""Document URIs carry the ACL label: acl://<label>/<doc_id>."""

from __future__ import annotations

import re

from .policy import LABEL_RE

SCHEME = "acl://"
DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DENY_FILTER = "uri = 'acl://__deny__/'"  # matches nothing: '_' is not a valid label character


def make_uri(label: str, doc_id: str) -> str:
    if not LABEL_RE.match(label) or not DOC_ID_RE.match(doc_id):
        raise ValueError(f"invalid label or doc id: {label!r}, {doc_id!r}")
    return f"{SCHEME}{label}/{doc_id}"


def label_of(uri: str | None) -> str | None:
    if not uri or not uri.startswith(SCHEME):
        return None
    label, _, rest = uri[len(SCHEME) :].partition("/")
    return label if LABEL_RE.match(label) and rest else None


def prefilter(labels: frozenset[str]) -> str:
    """SQL WHERE clause restricting documents to the given labels (deny-all if empty)."""
    safe = sorted(lab for lab in labels if LABEL_RE.match(lab))
    if not safe:
        return DENY_FILTER
    return "(" + " OR ".join(f"uri LIKE '{SCHEME}{lab}/%'" for lab in safe) + ")"
