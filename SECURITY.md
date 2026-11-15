# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately using GitHub's **Report a vulnerability** button (Security tab), not a public issue. We aim to reply within 5 working days. An access-control bypass (any way to get a restricted document's text or ID to a user without its label) is treated as critical.

## Threat model

| Threat | Mitigation | Tested by |
|---|---|---|
| User asks for content they may not read | Pre-filter limits search to the caller's labels | `test_enforcement.py`, leak eval |
| Pre-filter bug or bypass | Post-check re-validates every result (URI label = metadata label = allowed label); any block fails the leak eval | `test_postcheck_alone_blocks_and_records`, `test_prefilter_off_counts_as_defect` |
| Tampered metadata (URI and metadata disagree) | Result dropped and recorded | `test_tampered_metadata_is_dropped` |
| No identity / hook missing | Deny-all filter; missing hook fails closed | `test_missing_hook_fails_closed` |
| Identity bleeding between concurrent requests | Request-scoped `contextvars` identity | `test_concurrent_identities_do_not_mix` |
| Config override removes the hook | A `hooks` override is rejected, and the hook is set after other overrides are merged | `test_hook_always_enforced` |
| SQL injection through labels | Labels must match `^[a-z][a-z0-9-]{0,31}$` before they reach a filter | `test_acl.py` |
| Unlabelled or mislabelled document indexed | Ingest refuses the whole batch before writing; optional data contract | `test_ingest.py`, dogfood job |
| Label silently widened | `grag drift` exits 1 | `test_evals_drift.py`, README run |

**Out of scope:** authentication (identity is supplied by the caller), a malicious ingester (see LIMITATIONS.md), and haiku.rag features not used here (MCP, web app, S3, agents).

## Other notes

- **Privacy:** the audit log stores a SHA-256 of each question unless `--log-query` is passed.
- **Network:** the demo embedder binds to `127.0.0.1` only and caps request bodies at 8 MB. Nothing else is contacted unless you configure a remote embedder.
- **Telemetry:** haiku.rag can send traces through Logfire; governed-rag sets `LOGFIRE_IGNORE_NO_CONFIG=1` and never configures it, so nothing is sent.
- YAML is read with `yaml.safe_load`; policies and front matter are validated strictly.
- CI runs bandit, pip-audit and CodeQL, and pins third-party actions to commit SHAs with read-only default permissions.
