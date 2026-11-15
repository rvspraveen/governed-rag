# Changelog

## 0.1.0 (2026-11-12)

First release.

- Two-layer access control for haiku.rag through its public hook API: label pre-filter plus post-check, fail closed without identity.
- Strictly validated access policy (users, groups, labels).
- `grag ingest`: labelled Markdown corpus, all-or-nothing validation, optional corpusgate gate, sync with add/update/remove.
- `grag ask`: extractive cited answers or refusal, JSON output, SHA-256 audit log.
- `grag eval leak` (92 canary cases) and `grag eval quality` (rag-eval-gate export, committed baseline).
- `grag snapshot` / `grag drift`: fail on ACL widening, warn on retrieval drift.
- Offline hashing embedder for CI and demos; no API key needed.
- Synthetic Northwind Renewables corpus and generator.
- CI (Python 3.12 to 3.14), dogfood, quality gate, CodeQL, Dependabot, composite GitHub Action.
