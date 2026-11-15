from __future__ import annotations

import pytest

from governed_rag.engine import HOOK_NAME, build_config, load_overrides, open_client
from governed_rag.errors import GragError


def test_hook_always_enforced(config):
    assert next(h.name if hasattr(h, "name") else h for h in config.hooks) in (HOOK_NAME, {"name": HOOK_NAME})
    assert config.embeddings.model.vector_dim == 256


def test_overrides_cannot_touch_hooks():
    with pytest.raises(GragError, match="may not set 'hooks'"):
        build_config({"hooks": []})


def test_invalid_override():
    with pytest.raises(GragError, match=r"invalid haiku\.rag configuration"):
        build_config({"embeddings": {"model": {"provider": "nope", "name": "x", "vector_dim": "many"}}})


def test_embedding_override_skips_offline():
    cfg = build_config({"embeddings": {"model": {"provider": "ollama", "name": "nomic-embed-text", "vector_dim": 768}}})
    assert cfg.embeddings.model.provider == "ollama"


def test_load_overrides(tmp_path):
    assert load_overrides(None) == {}
    with pytest.raises(GragError, match="not found"):
        load_overrides(tmp_path / "x.yaml")
    p = tmp_path / "x.yaml"
    p.write_text("- a\n")
    with pytest.raises(GragError, match="mapping"):
        load_overrides(p)
    p.write_text("search: {limit: 3}\n")
    assert load_overrides(p) == {"search": {"limit": 3}}


async def test_open_missing_db(tmp_path, config):
    with pytest.raises(GragError, match="database not found"):
        async with open_client(tmp_path / "nope.lancedb", config):
            pass
