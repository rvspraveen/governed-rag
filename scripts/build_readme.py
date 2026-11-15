"""Render README.md from README.template.md using real command output.

    python scripts/build_readme.py

Runs every README command in a scratch copy of examples/ and evals/, checks each
exit code, and pastes the output in. The README never shows made-up results.
"""

from __future__ import annotations

import os
import re
import shutil

# Runs this repo's own CLI with fixed arguments.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}
P = ["-p", "examples/policy.yaml"]


def grag(cwd: Path, args: list[str], expected: int) -> str:
    cmd = [sys.executable, "-m", "governed_rag", *args]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=ENV, check=False)  # noqa: S603  # nosec B603
    if p.returncode != expected:
        raise SystemExit(f"grag {' '.join(args)}: expected exit {expected}, got {p.returncode}\n{p.stdout}\n{p.stderr}")
    text = (p.stdout + p.stderr).replace(str(cwd) + os.sep, "")
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join([f"$ grag {' '.join(args)}", *lines])


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        w = Path(tmp)
        shutil.copytree(ROOT / "examples", w / "examples")
        shutil.copytree(ROOT / "evals", w / "evals")
        c = ["-c", "examples/contract.yaml"]
        parts = {
            "BAD_INGEST": grag(w, ["ingest", "examples/corpus_bad", *c, *P], 1),
            "INGEST": grag(w, ["ingest", "examples/corpus", *c, *P], 0),
        }
        q = "What were Q3 salaries?"
        parts["ASK"] = "\n\n".join(
            [
                grag(w, ["ask", q, *P], 0),
                grag(w, ["ask", q, "--as", "analyst", *P], 0),
                grag(w, ["ask", q, "--as", "hr_lead", *P], 0),
            ]
        ).replace(f"ask {q} ", f'ask "{q}" ')
        parts["LEAK"] = grag(w, ["eval", "leak", "--corpus", "examples/corpus", *P], 0)

        # Drift: someone relabels the HR salary doc as public.
        probes = ["--probes", "evals/probes.yaml"]
        snap = grag(w, ["snapshot", *probes, "-o", "before.json", *P], 0)
        doc = w / "examples" / "corpus" / "q3-salaries.md"
        doc.write_text(doc.read_text(encoding="utf-8").replace("acl: hr\n", "acl: public\n"), encoding="utf-8")
        reingest = grag(w, ["ingest", "examples/corpus", *P], 0)
        snap2 = grag(w, ["snapshot", *probes, "-o", "after.json", *P], 0)
        drift = grag(w, ["drift", "--before", "before.json", "--after", "after.json", *P], 1)
        parts["DRIFT"] = "\n".join([snap, "$ sed -i 's/^acl: hr$/acl: public/' examples/corpus/q3-salaries.md", reingest, snap2, drift])

    out = (ROOT / "README.template.md").read_text(encoding="utf-8")
    for key, value in parts.items():
        out = out.replace("{{" + key + "}}", value)
    if leftover := re.findall(r"\{\{[A-Z_]+\}\}", out):
        raise SystemExit(f"unfilled placeholders: {leftover}")
    (ROOT / "README.md").write_text(out, encoding="utf-8")
    print("README.md rendered")


if __name__ == "__main__":
    main()
