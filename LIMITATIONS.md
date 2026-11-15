# Limitations

governed-rag v0.1 is a working reference for permission-aware retrieval, not a certified access-control product. Know these before you rely on it.

## Access model

- **Document-level labels only.** One label per document. There is no paragraph-level redaction, no row-level filtering inside tables, and no "this section is public, that one isn't". Split mixed documents before ingest.
- **One label, not a label set.** A document readable by finance *and* legal needs its own label (say `finance-legal`) that both groups are granted.
- **Identity is trusted.** `--as USER` (or the identity your code sets) is taken at face value. governed-rag decides what a known user may read; it does not authenticate anyone. Put it behind your identity provider.
- **The ingester is trusted.** Labels come from front matter written by whoever runs `grag ingest`. The post-check protects reads against a bad filter or tampered metadata; it can't protect against someone deliberately labelling the salary sheet `public`. The drift report is there to catch that after the fact.
- **Policy changes apply at query time, label changes at ingest.** Editing `policy.yaml` takes effect on the next question. Changing a document's label needs a re-ingest (the URI changes, so the old copy is removed and the new one added).

## Retrieval and answers

- **The demo embedder is lexical.** `grag-hash-256` hashes words and word pairs into 256 dimensions over a loopback-only HTTP server. It is deterministic and needs no download, which is why CI uses it, but it doesn't understand meaning. For real use, set an Ollama, OpenAI or sentence-transformers embedder with `--haiku-config` (and re-ingest).
- **Answers are extractive.** The answer is the best-matching sentences from permitted chunks, with citations, or a refusal. There is no LLM generation in v0.1. Adding one doesn't weaken access control, because restricted chunks never reach the answer step, but an LLM can still misstate permitted content.
- **Refusals can be over-cautious.** A question whose best permitted match is weak is refused rather than answered from a loosely related document. In the sample run the analyst is refused on "Q3 salaries" even though a public update mentions salary reviews.

## Evals

- **The leak eval proves its cases, not every query.** 92 cases cover every restricted document against every user who may not read it, plus anonymous callers, using direct questions, bare keyword queries, prompt-injection attempts and a PII lookup. Passing means none of those leaked; it is evidence, not a proof. Add cases for your own documents.
- **Canaries catch verbatim leaks.** A leak is detected when a restricted document's canary string or ID appears in an answer or citation. A paraphrased leak of restricted content without either would be missed, though with retrieval filtered first there is nothing to paraphrase from.
- **Drift probes are a sample.** Five fixed queries show whether retrieval shifted. Overlap below `--min-overlap` is a warning, not a failure, because legitimate content changes move results too. Only ACL widening fails the build.
- **Quality numbers are for the synthetic corpus.** The committed baseline (recall 1.00, NDCG 0.93) reflects 20 questions over 24 short documents with the lexical embedder. It is a regression baseline, not a benchmark.

## Operations

- **Install size.** haiku.rag-slim brings LanceDB, docling and pydantic-ai, about 880 MB. First install takes a few minutes.
- **Python 3.12 or newer**, because haiku.rag requires it. rag-eval-gate needs 3.10 to 3.12 and an older `openai` that breaks haiku.rag imports, so it must live in a separate virtual environment.
- **Single process.** The database is a local LanceDB directory. No server mode, no multi-tenant isolation, no concurrent writers.
- **Not included:** haiku.rag's MCP server, web app, Docker images, S3 storage, and its agent/sandbox features. They are left out until a leak test covers them.
- **haiku.rag moves fast.** It is pinned exactly at 0.111.0; newer versions are untested here.
