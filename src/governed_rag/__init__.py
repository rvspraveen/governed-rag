"""governed-rag: permission-aware RAG on haiku.rag, with leak and drift evals."""

import os

# haiku.rag uses logfire for tracing; it only exports when LOGFIRE_TOKEN is set.
# Silence the "not configured" warning so CLI output stays readable.
os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")

__version__ = "0.1.0"

UPSTREAM = "haiku.rag-slim"
