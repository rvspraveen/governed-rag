# Why retrieval has to know who is asking

[Back to the README](../README.md)

Most RAG applications index every document they can reach and answer any question they are asked. That is fine for a public knowledge base. Inside a company it is a leak: the salary sheet, the internal forecast and the litigation memo sit in the same index as the careers page, and a well-aimed question will retrieve them. Filtering the answer after generation is too late. Once restricted text is in the context window it can appear in the reply, in a citation, or in a prompt-injection echo. governed-rag puts access control inside retrieval, so a caller only ever searches documents they are allowed to read, and then it tests that claim on every commit.

## Filter at search time, then check again

The obvious hook is a single search filter: given the caller's labels, restrict the query to matching documents. One filter is not enough. A caller-supplied clause must not widen access (the test suite checks that a request with `uri LIKE 'acl://hr/%'` still returns nothing for an analyst). A bug in the filter, or metadata that disagrees with the URI, should not be a silent leak. So there are two independent layers, both registered through haiku.rag's public `haiku.rag.hooks` entry point.

Layer 1, `before_search`, adds a `uri LIKE 'acl://<label>/%'` clause for each of the caller's labels, combined with `AND` if the request already had a filter. No identity, or no labels, produces a clause that matches nothing (fail closed). Layer 2, `after_search`, drops any result whose URI label and stored `acl` metadata do not agree, or whose label the caller does not hold, and records the drop. A result survives only if both agree and the caller holds that label.

The test suite switches each layer off in turn and proves the other still blocks leaks, then switches both off and proves the leak eval goes red, including canaries in the answer. The CLI always leaves both layers on. `--haiku-config` can change the embedder or search settings but cannot remove the hook.

Identity is request-scoped. haiku.rag's hooks receive the client and the search request, not the caller, so a `ContextVar` carries the current user and labels for the asyncio task. `--as USER` is taken at face value: governed-rag decides what a known user may read; it does not authenticate anyone.

The retrieval engine underneath is [haiku.rag](https://github.com/ggozad/haiku.rag) (MIT, by Yiorgis Gozadinos), pinned exactly at `haiku.rag-slim==0.111.0` and used unmodified through its public API. governed-rag adds the policy, the hook, labelled ingest, the evals and the rest. haiku.rag ships almost daily, so upgrades only go through a pull request that has to pass the leak eval, the quality gate and the tests.

## A corpus that has something to leak

The bundled corpus is 24 short Markdown documents for a fictional company, Northwind Renewables. Eight are public. The other 16 are labelled `finance` (5), `hr` (6) or `legal` (5): salary bands, an internal EBITDA forecast, a workforce plan, a litigation hold, and so on. Every restricted document carries a unique `GRAG-CANARY-…` string in its front matter and body. The policy is small and strict: four labels, four groups, four users (`analyst` can read `public`; `finance_mgr`, `hr_lead` and `counsel` each add one restricted label). Unknown keys, undefined groups, and documents whose label is not in the policy are errors.

`grag ingest` validates the whole corpus first and writes nothing unless every check passes. Optionally, and in CI, the chunks also pass a [corpusgate](https://github.com/rvspraveen/corpusgate) contract: required fields including `acl`, unique IDs, length bounds, an allowed label set, citation metadata, and a PII warning. The deliberately broken corpus (a document with no `acl`, and one labelled `executive`) is refused with exit 1 and leaves no database behind.

## Ninety-two cases, zero leaks

The leak eval is generated from the corpus, not hand-written case by case. For each restricted document, one or more attack queries — a direct question, a bare keyword query, a prompt-injection attempt, or a PII lookup — are asked as every user who may not read that document, and as an anonymous caller. That produces 92 cases (analyst 23, anonymous 23, counsel 17, finance_mgr 16, hr_lead 13) from 23 distinct queries.

A case fails if a forbidden document is returned, if a document whose label the caller does not hold is returned, or if a restricted canary appears in the answer text. On the sample corpus the result is `leaks 0/92 cases, post-check blocks 0, refusals 76`. A post-check block with zero leaks is still a failure: it means layer 1 let something through and only layer 2 caught it.

This is evidence, not a proof. Passing means none of those 92 cases leaked. It does not mean every possible query is safe. Canaries catch verbatim leaks; a paraphrase of restricted content with neither the canary nor the document ID would be missed, though with retrieval filtered first there is nothing to paraphrase from. Add cases for your own documents.

## The rest of the chain

Access control that over-blocks is a bug too. `grag eval quality` runs 20 questions — each asked by a user who is allowed to read the gold document — through the same enforced search and writes `dataset.jsonl` and `run.jsonl` for [rag-eval-gate](https://github.com/rvspraveen/rag-eval-gate). The committed baseline has context recall 1.00, NDCG 0.93 and token-overlap faithfulness 1.00. The gate allows a drop of 0.05 on those metrics, with a hard floor of 0.90 on recall and faithfulness, and treats a 10% relative drop on `rouge_l_recall` as a warning. CI installs rag-eval-gate at `v0.1.0` in its own job, because it needs Python 3.12 or older and pins an `openai` version that breaks haiku.rag.

Quiet ACL widening is a different failure. Snapshots record every document's label and the results of five fixed probe queries. `grag drift` exits 1 when a label change makes a document readable by more people — the README works through relabelling the salary sheet as `public`, after which `analyst`, `counsel` and `finance_mgr` can read it — and only warns when probe overlap drops, because legitimate content edits move results too.

In CI the three tools run as a chain. corpusgate checks the corpus before it is ingested. The leak eval has to stay at zero after ingest. rag-eval-gate checks that answer quality has not regressed against the baseline. Together they cover data in, who is allowed to see what, and answers out.

## Limitations

These are spelled out in [LIMITATIONS.md](../LIMITATIONS.md); the short version:

- **Document-level labels only.** One label per document, not a label set, and no paragraph-level redaction. Split mixed documents before ingest.
- **Identity is trusted, and so is the ingester.** The hook enforces the labels it is given. It does not authenticate the caller, and it cannot stop someone labelling the salary sheet `public`. The drift report is there to catch that after the fact.
- **The demo embedder is lexical**, a 256-dimensional hash of words and word pairs, so the project runs from a fresh clone with no API key. It does not understand meaning. Answers are extractive sentences with citations, not LLM generation.
- **The leak eval proves its cases**, and canaries are verbatim, as described above.
- **Quality numbers are for this synthetic corpus** and this embedder, 20 questions over 24 short documents. They are a regression baseline, not a benchmark.
- **Python 3.12 or newer**, because haiku.rag requires it. The install is about 880 MB. There is no server mode and no concurrent writers.

## What is next

The first addition that would change the product is optional LLM generation behind the same hook, so restricted chunks still never reach the answer step, plus leak cases aimed at paraphrased disclosure once there is a model that can paraphrase. The second is a richer access model (more than one label per document, or section-level labels) for corpora that cannot be split cleanly. Until then, v0.1 is a working reference: pin haiku.rag, keep the leak eval at zero, and do not treat a green build as a certification.
