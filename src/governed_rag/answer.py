"""Extractive, cited answers built only from permitted search results. No LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .acl import label_of
from .text import words

REFUSAL = "I can't answer that from documents you have access to."

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "many",
        "much",
        "of",
        "on",
        "or",
        "our",
        "please",
        "show",
        "tell",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "me",
        "give",
        "list",
        "about",
        "any",
        "all",
        "ignore",
        "previous",
        "instruction",
        "instructions",
    ]
)
_SENT = re.compile(r"(?<=[.!?])\s+")


def terms(text: str) -> set[str]:
    return {w for w in words(text) if w not in STOPWORDS}


@dataclass
class Citation:
    n: int
    uri: str
    title: str
    label: str | None


@dataclass
class Answer:
    text: str
    refused: bool
    citations: list[Citation] = field(default_factory=list)


def _cite(sentence: str, n: int) -> str:
    """Put the marker before the final punctuation: 'It is 42 [1].'"""
    if sentence[-1:] in ".!?":
        return f"{sentence[:-1]} [{n}]{sentence[-1]}"
    return f"{sentence} [{n}]"


def extractive_answer(question: str, results: list[Any], max_sentences: int = 3) -> Answer:
    """Pick the sentences that share the most question terms.

    A sentence needs 2 shared terms (1 for one-term questions) to lead an
    answer. Once a chunk contributes a sentence, its other sentences need only
    1 shared term, so a fact split over two sentences is kept together.
    """
    q = terms(question)
    if not q or not results:
        return Answer(REFUSAL, refused=True)
    need = 1 if len(q) == 1 else 2
    cands: list[tuple[int, int, int, str, Any]] = []
    for rank, r in enumerate(results):
        for pos, sent in enumerate(s.strip() for s in _SENT.split(r.content or "")):
            hit = len(q & terms(sent))
            if sent and hit:
                cands.append((hit, rank, pos, sent, r))
    leads = sorted((c for c in cands if c[0] >= need), key=lambda c: (-c[0], c[1], c[2]))
    if not leads:
        return Answer(REFUSAL, refused=True)
    chosen = leads[:1]
    lead_rank = leads[0][1]
    support = [c for c in cands if c[1] == lead_rank and c is not leads[0]]
    for c in sorted(leads[1:] + support, key=lambda c: (-c[0], c[1], c[2])):
        if len(chosen) >= max_sentences:
            break
        if c not in chosen and (c[0] >= need or c[1] == lead_rank):
            chosen.append(c)
    chosen.sort(key=lambda c: (c[1], c[2]))  # keep document order for readability
    citations: dict[str, Citation] = {}
    parts = []
    for _, _, _, sent, r in chosen:
        uri = r.document_uri or ""
        if uri not in citations:
            citations[uri] = Citation(len(citations) + 1, uri, r.document_title or uri, label_of(uri))
        parts.append(_cite(sent, citations[uri].n))
    return Answer(" ".join(parts), refused=False, citations=list(citations.values()))
