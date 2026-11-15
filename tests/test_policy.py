from __future__ import annotations

import pytest

from governed_rag.errors import PolicyError
from governed_rag.policy import load_policy, parse_policy

GOOD = {"labels": ["public", "hr"], "groups": {"all": ["public"], "hr": ["hr"]}, "users": {"ann": ["all"], "bob": ["all", "hr"]}}


def test_example_policy(policy):
    assert policy.labels_for("analyst") == {"public"}
    assert policy.labels_for("hr_lead") == {"public", "hr"}
    assert policy.labels_for(None) == frozenset()
    assert policy.audience("hr") == {"hr_lead"}
    assert policy.audience("public") == {"analyst", "finance_mgr", "hr_lead", "counsel"}


def test_unknown_user(policy):
    with pytest.raises(PolicyError, match="unknown user 'mallory'"):
        policy.labels_for("mallory")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"labels": ["public", "h_r"]}, "invalid label 'h_r'"),  # '_' is a LIKE wildcard
        ({"labels": ["public", "hr'--"]}, "invalid label"),
        ({"labels": ["Public"]}, "invalid label"),
        ({"labels": "public"}, "list of names"),
        ({"groups": {}}, "groups must be"),
        ({"groups": {"all": ["secret"]}}, "unknown label"),
        ({"groups": {"bad name": ["public"]}}, "invalid group name"),
        ({"users": {}}, "users must be"),
        ({"users": {"ann": ["ghosts"]}}, "unknown group"),
        ({"users": {"ann'": ["all"]}}, "invalid user name"),
        ({"version": 2}, "unsupported version"),
        ({"extra": 1}, "unknown key"),
    ],
)
def test_invalid(change, match):
    with pytest.raises(PolicyError, match=match):
        parse_policy({**GOOD, **change})


def test_not_mapping():
    with pytest.raises(PolicyError, match="mapping"):
        parse_policy(["x"])


def test_load_errors(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "nope.yaml")
    p = tmp_path / "p.yaml"
    p.write_text("labels: [\n")
    with pytest.raises(PolicyError, match="invalid YAML"):
        load_policy(p)
