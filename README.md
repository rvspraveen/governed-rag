# governed-rag

**Permission-aware RAG on [haiku.rag](https://github.com/ggozad/haiku.rag).** Every user gets answers cited only from documents they are allowed to read. A leak eval in CI has to stay at zero, and a drift report fails the build when a document quietly becomes readable by more people.

[![CI](https://github.com/rvspraveen/governed-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/rvspraveen/governed-rag/actions/workflows/ci.yml)
![Python 3.12 to 3.14](https://img.shields.io/badge/python-3.12%20to%203.14-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Most RAG demos index everything and let anyone ask anything. In a company that means the salary sheet, the board minutes and the litigation memo are one clever question away from every employee. governed-rag puts access control inside retrieval, so restricted text never reaches the answer step, and then tests that claim on every commit.

- **Two independent enforcement layers.** A search filter limits retrieval to the caller's labels, and a post-check drops any result whose label disagrees with the caller's rights. No identity means no documents (fail closed).
- **Leak eval as a merge gate.** 92 adversarial cases (direct questions, keyword queries, prompt injection) ask for restricted content as the wrong user. Every restricted document carries a canary string; one canary in one answer fails the build.
- **Contract-checked ingest.** Chunks pass a [corpusgate](https://github.com/rvspraveen/corpusgate) contract before anything is written, so a document without an access label never gets indexed.
- **Drift report.** Snapshots record every document's label and the results of fixed probe queries. `grag drift` exits 1 when an ACL widens and warns when retrieval shifts.
- **Audit log.** One JSONL line per question: who asked, which labels applied, which documents were cited, and a SHA-256 of the query (raw text only with `--log-query`).
- **No API key, no model download.** The demo uses a local hashing embedder and extractive answers with citations. Point it at a real embedder with `--haiku-config` when you're ready.

## Run it

```bash
git clone https://github.com/rvspraveen/governed-rag && cd governed-rag
python -m venv .venv && source .venv/bin/activate        # Python 3.12 to 3.14
pip install -e . "corpusgate @ git+https://github.com/rvspraveen/corpusgate@v0.2.0"
```

The install pulls haiku.rag-slim and its LanceDB/docling stack (about 880 MB), so it takes a few minutes the first time. The commands below then take about 30 seconds in total.

A deliberately broken corpus is refused before anything is written (exit 1):

```text
$ grag ingest examples/corpus_bad -c examples/contract.yaml -p examples/policy.yaml
ingest refused: 2 problem(s) in examples/corpus_bad; nothing was written
  - board-minutes.md: missing 'acl' in front matter
  - exec-comp.md: acl 'executive' is not a label in the policy (finance, hr, legal, public)
```

The real sample corpus (24 documents for the fictional Northwind Renewables) passes its contract and is indexed. The one warning is a planted `example.com` address:

```text
$ grag ingest examples/corpus -c examples/contract.yaml -p examples/policy.yaml
contract passed (24 chunks, 0 errors, 1 warnings)
  warn:  pii_patterns / pii_patterns:text:email: observed 1, limit 0
ingested 24 docs / 24 chunks into .grag/db.lancedb: 24 added, 0 updated, 0 unchanged, 0 removed
```

The same question, asked by three different people:

```text
$ grag ask "What were Q3 salaries?" -p examples/policy.yaml
as anonymous (can read: nothing)
I can't answer that from documents you have access to.

$ grag ask "What were Q3 salaries?" --as analyst -p examples/policy.yaml
as analyst (can read: public)
I can't answer that from documents you have access to.

$ grag ask "What were Q3 salaries?" --as hr_lead -p examples/policy.yaml
as hr_lead (can read: hr, public)
Q3 2026 salary bands: analysts earn 95,000 dollars, senior analysts 118,000 dollars and managers 140,000 dollars [1].
  [1] Q3 2026 salary bands  acl://hr/q3-salaries
```

The leak eval tries every restricted document against every user who may not read it, plus anonymous callers:

```text
$ grag eval leak --corpus examples/corpus -p examples/policy.yaml
leak eval PASS: leaks 0/92 cases, post-check blocks 0, refusals 76
cases by caller: analyst 23, anonymous 23, counsel 17, finance_mgr 16, hr_lead 13
```

Someone relabels the HR salary sheet as public. Nothing errors, every test still passes, and three more people can now read salaries. The drift report catches it (exit 1):

```text
$ grag snapshot --probes evals/probes.yaml -o before.json -p examples/policy.yaml
snapshot of 24 docs and 5 probes -> before.json
$ sed -i 's/^acl: hr$/acl: public/' examples/corpus/q3-salaries.md
$ grag ingest examples/corpus -p examples/policy.yaml
ingested 24 docs / 24 chunks into .grag/db.lancedb: 1 added, 0 updated, 23 unchanged, 1 removed
$ grag snapshot --probes evals/probes.yaml -o after.json -p examples/policy.yaml
snapshot of 24 docs and 5 probes -> after.json
$ grag drift --before before.json --after after.json -p examples/policy.yaml
drift FAIL: 0 added, 0 removed, 0 changed, 1 ACL changes (1 widened)
  acl q3-salaries: hr -> public now readable by analyst, counsel, finance_mgr
  probe [analyst] 'Q3 salaries': top-k overlap 0.67 ok
  probe [analyst] 'Harlow Ridge capacity': top-k overlap 0.67 ok
  probe [finance_mgr] 'EBITDA forecast': top-k overlap 1.00 ok
  probe [hr_lead] 'salary bands': top-k overlap 0.67 ok
  probe [counsel] 'Vantor Turbines': top-k overlap 1.00 ok
```

All of the output above is pasted by `scripts/build_readme.py` from real runs, and CI fails if it goes stale.

## How enforcement works

```text
grag ask --as analyst "..."
   │
   ├─ identity: user -> groups -> labels  (policy.yaml; no user = no labels, unknown user = error)
   │
   ├─ haiku.rag search
   │     ├─ before_search hook ── adds  uri LIKE 'acl://public/%'   (layer 1: pre-filter)
   │     ├─ hybrid vector + full-text search in LanceDB
   │     └─ after_search hook ─── re-checks label in URI AND stored metadata  (layer 2: post-check)
   │
   ├─ extractive answer, citing only surviving chunks  (or a refusal)
   └─ audit log line
```

Each document's label is stored twice: in its URI (`acl://hr/q3-salaries`), which the pre-filter matches on, and in its metadata, which the post-check compares against. A result survives only if both agree and the caller holds that label. The test suite switches off each layer in turn and proves the other still blocks every leak case, then switches off both and proves the leak eval goes red.

The hook is registered through haiku.rag's public `haiku.rag.hooks` entry point and is always on in the CLI. `--haiku-config` can change the embedder or search settings but can't remove the hook.

## Access policy

```yaml
version: 1
labels: [public, finance, hr, legal]
groups:
  everyone: [public]
  finance: [finance]
  people-team: [hr]
  legal: [legal]
users:
  analyst: [everyone]
  finance_mgr: [everyone, finance]
  hr_lead: [everyone, people-team]
  counsel: [everyone, legal]
```

Documents are Markdown files with front matter (`acl`, `title`, `owner`). The policy is validated strictly: unknown keys, undefined groups or labels, and documents with labels outside the policy are all errors (exit 2 for a bad policy, exit 1 for a bad corpus).

## Quality gate with rag-eval-gate

Access control that over-blocks is a bug too. `grag eval quality` runs 20 questions through the same enforced search and writes `dataset.jsonl` and `run.jsonl` in the format [rag-eval-gate](https://github.com/rvspraveen/rag-eval-gate) scores. The committed baseline (`evals/quality_baseline.json`) has context recall 1.00, NDCG 0.93 and faithfulness 1.00.

```bash
grag eval quality --corpus examples/corpus --out-dir out -p examples/policy.yaml
reg gate -d out/dataset.jsonl -r out/run.jsonl -b evals/quality_baseline.json -g evals/quality_gate.yaml
```

rag-eval-gate needs Python 3.10 to 3.12 and pins an older `openai` that breaks haiku.rag, so install it in **its own virtual environment**. CI does exactly that.

## Use it in your own CI

```yaml
- uses: rvspraveen/governed-rag@v0.1.0
  with:
    corpus: docs/
    policy: policy.yaml
    leak-cases: evals/leak_cases.yaml
    contract: contract.yaml          # optional
```

The action ingests the corpus, runs the leak eval and fails the job on any leak. Write leak cases for your own restricted documents, or start from `examples/make_corpus.py`, which generates them from canaries.

## Commands

| Command | What it does | Exit codes |
|---|---|---|
| `grag ingest CORPUS [-c contract.yaml]` | Validate labels and contract, then sync (add, update, remove) into the index | 0 ok, 1 corpus/contract failed, 2 usage |
| `grag ask QUESTION [--as USER] [--json]` | Cited answer or refusal, plus an audit line | 0, 2 |
| `grag eval leak --corpus DIR` | Adversarial leak cases | 0 no leaks, 1 leak or post-check block, 2 |
| `grag eval quality --corpus DIR --out-dir DIR` | Export for rag-eval-gate | 0, 2 |
| `grag snapshot -o FILE` | Record labels, content hashes and probe results | 0, 2 |
| `grag drift --before A --after B` | Compare snapshots | 0, 1 ACL widened, 2 |

A post-check block during the leak eval counts as a failure even with zero leaks: it means layer 1 let something through and only layer 2 caught it.

## What's haiku.rag, what's ours

**haiku.rag** (MIT, by Yiorgis Gozadinos) provides document storage in LanceDB, hybrid vector and full-text search, the hook system, and the client API. It is pinned at `haiku.rag-slim==0.111.0` and used unmodified through its public API.

**governed-rag** adds the policy model and validation, the two-layer ACL hook, request-scoped identity, labelled ingest with sync and the contract gate, the offline embedder, extractive cited answers, the audit log, the leak and quality evals, snapshots and drift, the CLI, the GitHub Action, and the synthetic corpus.

haiku.rag ships almost daily, so the pin is exact. Upgrades go through a PR that has to pass the leak eval, the quality gate and the test suite.

## Limitations

Document-level labels only, a lexical demo embedder, and a leak eval that proves the bundled cases rather than every query. Read [LIMITATIONS.md](LIMITATIONS.md) before relying on this.

## Credits

- [haiku.rag](https://github.com/ggozad/haiku.rag) by Yiorgis Gozadinos, MIT. The retrieval engine underneath everything here.
- [corpusgate](https://github.com/rvspraveen/corpusgate) (built on [wimsey](https://github.com/benrutter/wimsey)) and [rag-eval-gate](https://github.com/rvspraveen/rag-eval-gate) (built on [continuous-eval](https://github.com/relari-ai/continuous-eval)), used as CI gates.

See [NOTICE](NOTICE). governed-rag is MIT licensed.
