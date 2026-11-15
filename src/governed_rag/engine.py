"""Builds the haiku.rag configuration and opens clients.

The enforcement hook is always appended here, after any user overrides, so it
cannot be configured away through the CLI.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml

from .embedder import DIM, MODEL, OfflineEmbedder
from .errors import GragError

HOOK_NAME = "governed_acl"
DEFAULT_DB = Path(".grag") / "db.lancedb"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def offline_embeddings() -> dict[str, Any]:
    return {
        "model": {"provider": "openai", "name": MODEL, "vector_dim": DIM, "base_url": OfflineEmbedder.base_url(), "api_key": "offline"},
    }


def build_config(overrides: dict[str, Any] | None = None, hook_options: dict[str, bool] | None = None) -> Any:
    """Return a haiku.rag AppConfig with the governed hook enforced."""
    from haiku.rag.config import AppConfig
    from pydantic import ValidationError

    overrides = dict(overrides or {})
    if "hooks" in overrides:
        raise GragError("haiku config overrides may not set 'hooks'; governed-rag manages them")
    base: dict[str, Any] = {"reranking": {"model": None}}
    if "embeddings" not in overrides:
        base["embeddings"] = offline_embeddings()
    data = _merge(base, overrides)
    data["hooks"] = [{"name": HOOK_NAME, "options": hook_options or {}}]
    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        raise GragError(f"invalid haiku.rag configuration: {e.errors()[0]['msg']}") from e


def load_overrides(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    p = Path(path)
    if not p.is_file():
        raise GragError(f"haiku config file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise GragError(f"{p}: expected a mapping")
    return data


@asynccontextmanager
async def open_client(db: str | Path, config: Any, *, create: bool = False, read_only: bool = False) -> AsyncIterator[Any]:
    from haiku.rag.client import HaikuRAG

    db = Path(db)
    if not create and not db.exists():
        raise GragError(f"database not found: {db} (run `grag ingest` first)")
    if create:
        db.parent.mkdir(parents=True, exist_ok=True)
    async with HaikuRAG(db, config=config, create=create, read_only=read_only) as client:
        yield client
