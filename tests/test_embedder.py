from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

import pytest

from governed_rag.embedder import DIM, OfflineEmbedder, embed


def test_embed_properties():
    a = embed("Q3 salary bands for analysts")
    assert len(a) == DIM
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert a == embed("Q3 salary bands for analysts")
    assert embed("salaries") == embed("salary")  # plural folding
    assert embed("") == [1.0] + [0.0] * (DIM - 1)


def _post(url: str, body: bytes):
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"}, method="POST")  # noqa: S310
    return urllib.request.urlopen(req, timeout=5)  # noqa: S310  # loopback test server


def test_server_roundtrip():
    base = OfflineEmbedder.base_url()
    assert base.startswith("http://127.0.0.1:")
    assert OfflineEmbedder.base_url() == base  # one server per process
    with _post(base + "/embeddings", json.dumps({"model": "m", "input": ["a b", "c"]}).encode()) as r:
        data = json.loads(r.read())
    assert [d["index"] for d in data["data"]] == [0, 1]
    assert data["data"][0]["embedding"] == embed("a b")
    with _post(base + "/embeddings", json.dumps({"input": "solo"}).encode()) as r:
        assert len(json.loads(r.read())["data"]) == 1


@pytest.mark.parametrize(
    ("path", "body", "code"),
    [("/nope", b"{}", 404), ("/embeddings", b"not json", 400), ("/embeddings", b'{"input": [1]}', 400), ("/embeddings", b"", 413)],
)
def test_server_errors(path, body, code):
    base = OfflineEmbedder.base_url()
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + path, body)
    assert e.value.code == code
