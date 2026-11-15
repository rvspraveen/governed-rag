from __future__ import annotations

from types import SimpleNamespace

from governed_rag.answer import REFUSAL, extractive_answer, terms


def r(content, uri="acl://public/a", title="A"):
    return SimpleNamespace(content=content, document_uri=uri, document_title=title)


def test_terms_drop_stopwords_and_fold_plurals():
    assert terms("What were the Q3 salaries?") == {"were", "q3", "salary"}


def test_refusals():
    assert extractive_answer("salaries", []).refused
    assert extractive_answer("what is the", [r("anything")]).refused  # only stopwords
    ans = extractive_answer("turbine blade warranty", [r("The cafeteria opens at 8am.")])
    assert ans.refused and ans.text == REFUSAL and ans.citations == []


def test_answer_with_citation_before_full_stop():
    ans = extractive_answer("How many turbines at Harlow Ridge?", [r("Harlow Ridge has 42 turbines. The sky is blue.")])
    assert not ans.refused
    assert ans.text == "Harlow Ridge has 42 turbines [1]."
    assert ans.citations[0].label == "public"


def test_supporting_sentence_from_lead_chunk():
    text = "We issued a litigation hold for the Vantor dispute. Counsel estimates exposure of 4 million. Lunch is at noon."
    ans = extractive_answer("What is the exposure in the Vantor dispute?", [r(text)])
    assert "exposure of 4 million [1]." in ans.text
    assert "Lunch" not in ans.text


def test_multiple_sources_numbered_in_order():
    a = r("Harlow Ridge turbines number 42.", uri="acl://public/a", title="A")
    b = r("Harlow Ridge turbines were commissioned in May", uri="acl://public/b", title="B")
    ans = extractive_answer("Harlow Ridge turbines", [a, b])
    assert [c.n for c in ans.citations] == [1, 2]
    assert ans.text.endswith("in May [2]")
