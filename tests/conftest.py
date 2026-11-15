from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from governed_rag.engine import build_config
from governed_rag.ingest import ingest
from governed_rag.policy import load_policy

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
EVALS = ROOT / "evals"


@pytest.fixture(scope="session")
def policy():
    return load_policy(EXAMPLES / "policy.yaml")


@pytest.fixture(scope="session")
def config():
    return build_config()


@pytest.fixture(scope="session")
def db(tmp_path_factory, policy, config) -> Path:
    """The bundled corpus, ingested once for the whole session (read-only use)."""
    path = tmp_path_factory.mktemp("db") / "db.lancedb"
    res = asyncio.run(ingest(EXAMPLES / "corpus", policy, path, config))
    assert res.passed and len(res.added) == 24
    return path


@pytest.fixture
def corpus_copy(tmp_path) -> Path:
    dst = tmp_path / "corpus"
    shutil.copytree(EXAMPLES / "corpus", dst)
    return dst


def unhooked_config(**_: Any) -> Any:
    """haiku.rag config with the same embedder but no governed hook at all."""
    from haiku.rag.config import AppConfig

    from governed_rag.engine import offline_embeddings

    return AppConfig.model_validate({"embeddings": offline_embeddings(), "reranking": {"model": None}})


def write_doc(directory: Path, name: str, acl: str | None, body: str, title: str = "T") -> Path:
    fm = f"title: {title}\n" + (f"acl: {acl}\n" if acl is not None else "")
    p = directory / f"{name}.md"
    p.write_text(f"---\n{fm}---\n\n{body}\n", encoding="utf-8")
    return p
