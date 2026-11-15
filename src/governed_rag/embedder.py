"""A deterministic, offline hashing embedder served on 127.0.0.1.

haiku.rag has no public hook for a custom embedder, but its `openai` provider
accepts a `base_url`. This module serves an OpenAI-compatible /v1/embeddings
endpoint on a loopback port so CI and the demo need no API key and no model
download. Quality is lexical (feature hashing of words and word pairs). Use a
real embedder for anything beyond demos; see the README.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .text import words

DIM = 256
MODEL = "grag-hash-256"
MAX_BODY = 8 * 1024 * 1024


def _tokens(text: str) -> list[str]:
    ws = words(text)
    return ws + [f"{a}_{b}" for a, b in itertools.pairwise(ws)]


def embed(text: str, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    for tok in _tokens(text):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        v[h % dim] += 1.0 if (h >> 32) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        v[0] = 1.0
        return v
    return [x / norm for x in v]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # keep CLI output clean
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/embeddings":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._send(413, {"error": "bad length"})
            return
        try:
            req = json.loads(self.rfile.read(length))
            inp = req["input"]
            texts = [inp] if isinstance(inp, str) else list(inp)
            if not all(isinstance(t, str) for t in texts):
                raise ValueError("input must be strings")
        except (ValueError, KeyError, TypeError):
            self._send(400, {"error": "bad request"})
            return
        data = [{"object": "embedding", "index": i, "embedding": embed(t)} for i, t in enumerate(texts)]
        self._send(200, {"object": "list", "model": req.get("model", MODEL), "data": data, "usage": {"prompt_tokens": 0, "total_tokens": 0}})


class OfflineEmbedder:
    """Starts the loopback server once per process."""

    _lock = threading.Lock()
    _server: ThreadingHTTPServer | None = None

    @classmethod
    def base_url(cls) -> str:
        with cls._lock:
            if cls._server is None:
                server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
                server.daemon_threads = True
                threading.Thread(target=server.serve_forever, name="grag-embedder", daemon=True).start()
                cls._server = server
            host, port = cls._server.server_address[:2]
            return f"http://{host}:{port}/v1"
