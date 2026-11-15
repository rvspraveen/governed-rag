"""Command line interface: `grag`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__
from .drift import diff, snapshot
from .engine import DEFAULT_DB, build_config, load_overrides, open_client
from .errors import GragError
from .evals import export_quality, leak_eval
from .ingest import ingest
from .policy import load_policy
from .service import governed_ask


def _console(stderr: bool = False) -> Console:
    probe = Console(stderr=stderr)
    return probe if probe.is_terminal else Console(stderr=stderr, width=120)


def _cfg(a: argparse.Namespace) -> Any:
    return build_config(load_overrides(a.haiku_config))


def _read_json(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise GragError(f"file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GragError(f"{p}: invalid JSON ({e.msg})") from e


# ------------------------------------------------------------------ commands


async def cmd_ingest(a: argparse.Namespace) -> int:
    out = _console()
    res = await ingest(a.corpus, load_policy(a.policy), a.db, _cfg(a), contract=a.contract)
    if res.problems:
        out.print(f"[bold red]ingest refused:[/] {len(res.problems)} problem(s) in {a.corpus}; nothing was written")
        for p in res.problems:
            out.print(f"  - {escape(p)}")
        return 1
    if res.contract is not None:
        c = res.contract
        colour = "green" if c.passed else "red"
        out.print(f"[{colour}]contract {'passed' if c.passed else 'FAILED'}[/] ({res.chunks} chunks, {len(c.errors)} errors, {len(c.warnings)} warnings)")
        for e in c.errors:
            out.print(f"  error: {escape(e)}")
        for w in c.warnings:
            out.print(f"  warn:  {escape(w)}")
        if not c.passed:
            out.print("[bold red]ingest refused:[/] nothing was written")
            return 1
    out.print(
        f"[green]ingested[/] {res.docs} docs / {res.chunks} chunks into {a.db}: "
        f"{len(res.added)} added, {len(res.updated)} updated, {len(res.unchanged)} unchanged, {len(res.removed)} removed"
    )
    return 0


async def cmd_ask(a: argparse.Namespace) -> int:
    policy = load_policy(a.policy)
    async with open_client(a.db, _cfg(a), read_only=True) as client:
        res = await governed_ask(client, policy, a.user, a.question, limit=a.limit, audit_path=a.audit, log_query=a.log_query)
    if a.json:
        payload = {
            "user": res.user,
            "labels": sorted(res.labels),
            "answer": res.answer.text,
            "refused": res.answer.refused,
            "citations": [c.__dict__ for c in res.answer.citations],
            "retrieved": res.doc_uris,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    out = _console()
    who = res.user or "anonymous"
    out.print(f"[dim]as {who} (can read: {', '.join(sorted(res.labels)) or 'nothing'})[/]")
    out.print(escape(res.answer.text))
    for c in res.answer.citations:
        out.print(f"  [{c.n}] {escape(c.title)}  [dim]{escape(c.uri)}[/]")
    return 0


async def cmd_leak(a: argparse.Namespace) -> int:
    policy = load_policy(a.policy)
    async with open_client(a.db, _cfg(a), read_only=True) as client:
        rep = await leak_eval(client, policy, a.cases, a.corpus, limit=a.limit)
    out = _console()
    ok = rep.passed()
    colour = "green" if ok else "red"
    out.print(
        f"[bold {colour}]leak eval {'PASS' if ok else 'FAIL'}[/]: leaks {rep.leaks}/{rep.cases} cases, "
        f"post-check blocks {rep.postcheck_blocked}, refusals {rep.refused}"
    )
    out.print("[dim]cases by caller: " + ", ".join(f"{u} {n}" for u, n in sorted(rep.by_user.items())) + "[/]")
    if rep.findings:
        t = Table(show_edge=False)
        for col in ("case", "as", "query", "leaked", "why"):
            t.add_column(col)
        for f in rep.findings[:25]:
            t.add_row(str(f.case), f.user or "anonymous", escape(f.query[:60]), escape(", ".join(f.leaked)), f.reason)
        out.print(t)
    if rep.postcheck_blocked:
        out.print("[red]the post-check dropped results the pre-filter let through: investigate the filter[/]")
    return 0 if ok else 1


async def cmd_quality(a: argparse.Namespace) -> int:
    policy = load_policy(a.policy)
    async with open_client(a.db, _cfg(a), read_only=True) as client:
        n = await export_quality(client, policy, a.cases, a.corpus, a.out_dir, limit=a.limit)
    _console(stderr=True).print(f"wrote {n} items to {a.out_dir}/dataset.jsonl and run.jsonl (score them with `reg gate`)")
    return 0


async def cmd_snapshot(a: argparse.Namespace) -> int:
    policy = load_policy(a.policy)
    async with open_client(a.db, _cfg(a), read_only=True) as client:
        snap = await snapshot(client, policy, a.probes, k=a.k)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _console(stderr=True).print(f"snapshot of {len(snap['docs'])} docs and {len(snap['probes'])} probes -> {a.out}")
    return 0


async def cmd_drift(a: argparse.Namespace) -> int:
    rep = diff(_read_json(a.before), _read_json(a.after), load_policy(a.policy), min_overlap=a.min_overlap)
    out = _console()
    fail = bool(rep.widened) and not a.allow_widening
    out.print(
        f"[bold {'red' if fail else 'green'}]drift {'FAIL' if fail else 'OK'}[/]: {len(rep.added)} added, {len(rep.removed)} removed, "
        f"{len(rep.changed)} changed, {len(rep.acl_changes)} ACL changes ({len(rep.widened)} widened)"
    )
    for name, items in (("added", rep.added), ("removed", rep.removed), ("changed", rep.changed)):
        if items:
            out.print(f"  {name}: {', '.join(items)}")
    for c in rep.acl_changes:
        extra = f" [red]now readable by {', '.join(c.new_readers)}[/]" if c.widened else " (narrowed or same audience)"
        out.print(f"  acl {c.doc_id}: {c.before} -> {c.after}{extra}")
    for user, query, j in rep.probe_overlap:
        mark = "[yellow]low[/]" if j < rep.min_overlap else "ok"
        who = escape(f"[{user or 'anonymous'}]")
        out.print(f"  probe {who} {escape(repr(query))}: top-k overlap {j:.2f} {mark}")
    return 1 if fail else 0


# -------------------------------------------------------------------- parser


def _common(p: argparse.ArgumentParser, policy: bool = True, db: bool = True) -> None:
    if policy:
        p.add_argument("--policy", "-p", default="policy.yaml", help="access policy YAML (default: policy.yaml)")
    if db:
        p.add_argument("--db", default=str(DEFAULT_DB), help=f"database path (default: {DEFAULT_DB})")
        p.add_argument("--haiku-config", help="YAML overrides for haiku.rag (e.g. a real embedder); hooks cannot be overridden")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="grag", description="Permission-aware RAG on haiku.rag, with leak and drift evals.")
    p.add_argument("--version", action="version", version=f"governed-rag {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="validate a Markdown corpus and sync it into the index")
    s.add_argument("corpus")
    s.add_argument("--contract", "-c", help="corpusgate YAML to enforce before writing")
    _common(s)
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("ask", help="ask a question as a user; answers cite only documents that user may read")
    s.add_argument("question")
    s.add_argument("--as", dest="user", help="user from the policy (omit for anonymous, which can read nothing)")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--audit", default=".grag/audit.jsonl", help="audit log path (JSONL)")
    s.add_argument("--log-query", action="store_true", help="store the raw query in the audit log (default: SHA-256 only)")
    s.add_argument("--json", action="store_true")
    _common(s)
    s.set_defaults(func=cmd_ask)

    ev = sub.add_parser("eval", help="leak and quality evals")
    evs = ev.add_subparsers(dest="ecmd", required=True)
    s = evs.add_parser("leak", help="adversarial access cases; exit 1 on any leak")
    s.add_argument("--cases", default="evals/leak_cases.yaml")
    s.add_argument("--corpus", required=True, help="corpus dir (for canary strings)")
    s.add_argument("--limit", type=int, default=10)
    _common(s)
    s.set_defaults(func=cmd_leak)
    s = evs.add_parser("quality", help="export dataset.jsonl + run.jsonl for rag-eval-gate")
    s.add_argument("--cases", default="evals/quality_cases.yaml")
    s.add_argument("--corpus", required=True)
    s.add_argument("--out-dir", "-o", required=True)
    s.add_argument("--limit", type=int, default=3)
    _common(s)
    s.set_defaults(func=cmd_quality)

    s = sub.add_parser("snapshot", help="record documents, ACLs and probe results")
    s.add_argument("--probes", help="probes YAML")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--out", "-o", required=True)
    _common(s)
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("drift", help="compare two snapshots; exit 1 if any document became readable by more users")
    s.add_argument("--before", required=True)
    s.add_argument("--after", required=True)
    s.add_argument("--min-overlap", type=float, default=0.6)
    s.add_argument("--allow-widening", action="store_true")
    _common(s, db=False)
    s.set_defaults(func=cmd_drift)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    try:
        return int(asyncio.run(args.func(args)))
    except GragError as e:
        _console(stderr=True).print(f"[red]error:[/] {escape(str(e))}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
