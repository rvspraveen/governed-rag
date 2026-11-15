from __future__ import annotations

import pytest

from governed_rag.acl import DENY_FILTER, label_of, make_uri, prefilter


def test_uri_roundtrip():
    uri = make_uri("hr", "q3-salaries")
    assert uri == "acl://hr/q3-salaries"
    assert label_of(uri) == "hr"


@pytest.mark.parametrize(("label", "doc"), [("h_r", "x"), ("hr", "X"), ("hr'", "x"), ("hr", "a/b")])
def test_make_uri_rejects(label, doc):
    with pytest.raises(ValueError, match="invalid"):
        make_uri(label, doc)


@pytest.mark.parametrize("uri", [None, "", "file:///x", "acl://hr", "acl://hr/", "acl://H R/x"])
def test_label_of_invalid(uri):
    assert label_of(uri) is None


def test_prefilter():
    assert prefilter(frozenset()) == DENY_FILTER
    assert prefilter(frozenset({"public", "hr"})) == "(uri LIKE 'acl://hr/%' OR uri LIKE 'acl://public/%')"


def test_prefilter_drops_unsafe_labels():
    # Defence in depth: the policy already rejects these.
    assert prefilter(frozenset({"x' OR '1'='1", "a_b"})) == DENY_FILTER
    assert prefilter(frozenset({"hr", "x%"})) == "(uri LIKE 'acl://hr/%')"
