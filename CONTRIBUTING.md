# Contributing

Small, focused PRs are easiest to review. Anything touching `hook.py`, `acl.py`, `identity.py` or `engine.py` needs a test that fails without the change.

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.12 to 3.14
pip install -e ".[dev]" "corpusgate @ git+https://github.com/rvspraveen/corpusgate@v0.2.0"
ruff check . && ruff format --check .
pytest                     # coverage must stay >= 90%
bandit -q -r src
grag ingest examples/corpus -c examples/contract.yaml -p examples/policy.yaml
grag eval leak --corpus examples/corpus -p examples/policy.yaml   # must stay at 0 leaks
```

**Changing the sample corpus or eval cases**
Edit `examples/make_corpus.py` and run it. It rewrites `examples/corpus*`, `evals/leak_cases.yaml`, `evals/quality_cases.yaml` and `evals/probes.yaml`. CI fails if the committed files differ from the generator. Keep everything fictional: 555-01xx phone numbers and example.com addresses only.

If answers change, refresh the quality baseline in a separate rag-eval-gate environment (Python 3.12):

```bash
grag eval quality --corpus examples/corpus --out-dir out -p examples/policy.yaml
reg score -d out/dataset.jsonl -r out/run.jsonl -o out/scores.json
reg baseline promote out/scores.json -o evals/quality_baseline.json --note "why it changed"
```

Then run `python scripts/build_readme.py` so the README output matches.

**Upgrading haiku.rag**
It is pinned exactly. Bump it in its own PR; the tests, the leak eval and the quality gate must all pass unchanged.
