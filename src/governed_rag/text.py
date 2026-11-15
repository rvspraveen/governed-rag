"""Shared text normalisation."""

from __future__ import annotations

import re

WORD = re.compile(r"[a-z0-9]+")


def stem(w: str) -> str:
    """Tiny plural folding: salaries -> salary, turbines -> turbine."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text.lower())]
