"""Reading a Markdown corpus with front matter, built-in ACL checks, and chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .acl import DOC_ID_RE, make_uri
from .errors import CorpusError
from .policy import Policy

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
MAX_CHARS = 800


@dataclass
class Doc:
    doc_id: str
    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def acl(self) -> Any:
        return self.meta.get("acl")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.doc_id)

    @property
    def uri(self) -> str:
        return make_uri(self.acl, self.doc_id)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    order: int
    text: str
    acl: Any
    source: str
    title: str

    def to_row(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "order": self.order,
            "text": self.text,
            "acl": self.acl,
            "source": self.source,
            "title": self.title,
        }


@dataclass
class CorpusCheck:
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def read_doc(path: Path) -> Doc:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CorpusError(f"{path}: cannot read ({e})") from e
    m = FRONT_MATTER.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            raise CorpusError(f"{path}: invalid front matter ({e})") from e
        if not isinstance(meta, dict):
            raise CorpusError(f"{path}: front matter must be a mapping")
        body = m.group(2)
    else:
        meta, body = {}, text
    return Doc(doc_id=path.stem, path=path, meta=meta, body=body.strip())


def read_corpus(directory: str | Path) -> list[Doc]:
    d = Path(directory)
    if not d.is_dir():
        raise CorpusError(f"corpus directory not found: {d}")
    docs = [read_doc(p) for p in sorted(d.glob("*.md"))]
    if not docs:
        raise CorpusError(f"{d}: no .md files")
    return docs


def check_corpus(docs: list[Doc], policy: Policy) -> CorpusCheck:
    """Checks that always run, with or without a data contract. Fail closed."""
    out = CorpusCheck()
    seen: set[str] = set()
    for doc in docs:
        where = doc.path.name
        if not DOC_ID_RE.match(doc.doc_id):
            out.problems.append(f"{where}: file name must be lowercase letters, digits and '-' (it becomes the doc id)")
        if doc.doc_id in seen:
            out.problems.append(f"{where}: duplicate doc id {doc.doc_id!r}")
        seen.add(doc.doc_id)
        if doc.acl is None:
            out.problems.append(f"{where}: missing 'acl' in front matter")
        elif not isinstance(doc.acl, str) or doc.acl not in policy.labels:
            out.problems.append(f"{where}: acl {doc.acl!r} is not a label in the policy ({', '.join(sorted(policy.labels))})")
        if not doc.body:
            out.problems.append(f"{where}: empty body")
    return out


def _paragraphs(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def chunk_doc(doc: Doc, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """Greedy paragraph packing. A paragraph longer than max_chars becomes its own chunk."""
    pieces: list[str] = []
    buf = ""
    for para in _paragraphs(doc.body):
        if buf and len(buf) + 1 + len(para) > max_chars:
            pieces.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        pieces.append(buf)
    return [
        Chunk(
            chunk_id=f"{doc.doc_id}#{i}",
            doc_id=doc.doc_id,
            order=i,
            text=text,
            acl=doc.acl,
            source=doc.path.name,
            title=doc.title,
        )
        for i, text in enumerate(pieces)
    ]
