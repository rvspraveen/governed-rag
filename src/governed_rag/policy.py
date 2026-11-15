"""Access policy: users -> groups -> ACL labels.

Labels are restricted to lowercase letters, digits and hyphens. They are used
inside SQL LIKE patterns by the pre-filter, so `_` and `%` (LIKE wildcards) and
quotes are rejected by construction rather than escaped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import PolicyError

LABEL_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Policy:
    labels: frozenset[str]
    groups: dict[str, frozenset[str]]
    users: dict[str, frozenset[str]]  # user -> groups

    def labels_for(self, user: str | None) -> frozenset[str]:
        """Labels a user may read. `None` (anonymous) may read nothing."""
        if user is None:
            return frozenset()
        if user not in self.users:
            raise PolicyError(f"unknown user {user!r}; known users: {', '.join(sorted(self.users))}")
        out: set[str] = set()
        for g in self.users[user]:
            out |= self.groups[g]
        return frozenset(out)

    def audience(self, label: str) -> frozenset[str]:
        """Users who can read documents carrying `label`."""
        return frozenset(u for u in self.users if label in self.labels_for(u))


def _names(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PolicyError(f"{where}: expected a list of names")
    return value


def parse_policy(data: object, source: str = "policy") -> Policy:
    if not isinstance(data, dict):
        raise PolicyError(f"{source}: expected a mapping")
    unknown = set(data) - {"version", "labels", "groups", "users"}
    if unknown:
        raise PolicyError(f"{source}: unknown key(s): {', '.join(sorted(unknown))}")
    if data.get("version", 1) != 1:
        raise PolicyError(f"{source}: unsupported version {data.get('version')!r}")

    labels = _names(data.get("labels"), f"{source}: labels")
    for lab in labels:
        if not LABEL_RE.match(lab):
            raise PolicyError(f"{source}: invalid label {lab!r} (lowercase letters, digits and '-', max 32 chars)")
    label_set = frozenset(labels)

    raw_groups = data.get("groups")
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise PolicyError(f"{source}: groups must be a non-empty mapping")
    groups: dict[str, frozenset[str]] = {}
    for g, labs in raw_groups.items():
        if not isinstance(g, str) or not NAME_RE.match(g):
            raise PolicyError(f"{source}: invalid group name {g!r}")
        labs = _names(labs, f"{source}: groups.{g}")
        bad = sorted(set(labs) - label_set)
        if bad:
            raise PolicyError(f"{source}: group {g!r} grants unknown label(s): {', '.join(bad)}")
        groups[g] = frozenset(labs)

    raw_users = data.get("users")
    if not isinstance(raw_users, dict) or not raw_users:
        raise PolicyError(f"{source}: users must be a non-empty mapping")
    users: dict[str, frozenset[str]] = {}
    for u, gs in raw_users.items():
        if not isinstance(u, str) or not NAME_RE.match(u):
            raise PolicyError(f"{source}: invalid user name {u!r}")
        gs = _names(gs, f"{source}: users.{u}")
        bad = sorted(set(gs) - set(groups))
        if bad:
            raise PolicyError(f"{source}: user {u!r} is in unknown group(s): {', '.join(bad)}")
        users[u] = frozenset(gs)
    return Policy(labels=label_set, groups=groups, users=users)


def load_policy(path: str | Path) -> Policy:
    p = Path(path)
    if not p.is_file():
        raise PolicyError(f"policy file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PolicyError(f"{p}: invalid YAML ({e})") from e
    return parse_policy(data, str(p))
