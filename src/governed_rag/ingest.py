"""Governed ingest: built-in ACL checks, optional data contract, then sync into haiku.rag."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .acl import SCHEME
from .contracts import ContractResult, run_contract
from .corpus import Chunk, Doc, check_corpus, chunk_doc, read_corpus
from .engine import open_client
from .policy import Policy


@dataclass
class IngestResult:
    docs: int = 0
    chunks: int = 0
    problems: list[str] = field(default_factory=list)
    contract: ContractResult | None = None
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems and (self.contract is None or self.contract.passed)


def _docling(doc: Doc) -> Any:
    from docling_core.types.doc import DocItemLabel, DoclingDocument

    dd = DoclingDocument(name=doc.doc_id)
    for para in (p.strip() for p in doc.body.split("\n\n")):
        if para:
            dd.add_text(label=DocItemLabel.TEXT, text=para)
    return dd


async def ingest(corpus_dir: str | Path, policy: Policy, db: str | Path, config: Any, contract: str | Path | None = None) -> IngestResult:
    """Validate the whole corpus first; write nothing unless every check passes.

    The database is synced to the corpus: new and changed documents are
    imported, and documents no longer in the corpus (or whose ACL moved them to
    a different URI) are deleted.
    """
    from haiku.rag.store.models.chunk import Chunk as HaikuChunk

    docs = read_corpus(corpus_dir)
    res = IngestResult(docs=len(docs))
    res.problems = check_corpus(docs, policy).problems
    if res.problems:
        return res
    chunks_by_doc: dict[str, list[Chunk]] = {d.doc_id: chunk_doc(d) for d in docs}
    all_chunks = [c for cs in chunks_by_doc.values() for c in cs]
    res.chunks = len(all_chunks)
    if contract is not None:
        res.contract = run_contract(contract, all_chunks)
        if not res.contract.passed:
            return res

    async with open_client(db, config, create=True) as client:
        existing = {d.uri: d for d in await client.list_documents() if d.uri and d.uri.startswith(SCHEME)}
        wanted = {d.uri for d in docs}
        for doc in docs:
            old = existing.get(doc.uri)
            if old is not None and (old.metadata or {}).get("sha256") == doc.sha256 and old.title == doc.title:
                res.unchanged.append(doc.doc_id)
                continue
            meta = {
                "acl": doc.acl,
                "doc_id": doc.doc_id,
                "sha256": doc.sha256,
                "source": doc.path.name,
                **{k: v for k, v in doc.meta.items() if k in ("owner", "classification") and isinstance(v, str)},
            }
            hchunks = [HaikuChunk(content=c.text, order=c.order, metadata={"chunk_id": c.chunk_id}) for c in chunks_by_doc[doc.doc_id]]
            if old is not None:
                await client.delete_document(old.id)
            await client.import_document(_docling(doc), hchunks, uri=doc.uri, title=doc.title, metadata=meta)
            (res.updated if old is not None else res.added).append(doc.doc_id)
        for uri, old in existing.items():
            if uri not in wanted:
                await client.delete_document(old.id)
                res.removed.append(uri)
    return res
