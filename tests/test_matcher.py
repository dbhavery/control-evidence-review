"""Matcher: normalization, phrase matching, stemming, word boundaries."""

from __future__ import annotations

from cer.matcher import EvidenceIndex, normalize
from cer.models import Evidence


def _index(text: str) -> EvidenceIndex:
    return EvidenceIndex([Evidence("e1", "e1.txt", text)])


def test_normalize_collapses_punctuation():
    assert normalize("Access-Review,  DONE!") == "access review done"


def test_phrase_match_is_case_insensitive():
    idx = _index("We ran a Quarterly Access Review last month.")
    assert idx.matches("access review") == ["e1"]
    assert idx.matches("ACCESS REVIEW") == ["e1"]


def test_word_boundary_prevents_substring_match():
    idx = _index("The blog post mentions catalogs.")
    # "log" must not match inside "blog"; "catalog" not inside "catalogs" wrongly.
    assert idx.matches("log") == []


def test_stemming_matches_inflections():
    idx = _index("The team reviewed the logs and reviews them weekly.")
    # keyword 'review' should match 'reviewed'/'reviews' via the stemmer.
    assert idx.matches("review") == ["e1"]


def test_stemming_applies_to_every_token_not_just_the_last():
    """Regression: a phrase whose EARLIER token the stemmer alters must match.

    Found 2026-09-20 on a real corpus. The evidence read "we answer within one
    business day"; the keyword was "business days". The index stems every
    token, so the text was held as "busines day", while the keyword stemmed
    only its last token and stayed "business day". It matched neither the
    literal text (plural vs singular) nor the stemmed text, and the control
    came back MISSING against a document that satisfied it.
    """
    idx = _index("Support hours: we answer within one business day, and usually sooner.")
    assert idx.matches("business days") == ["e1"]
    assert idx.matches("business day") == ["e1"]


def test_stemming_does_not_match_an_unrelated_phrase():
    """Control for the test above: widening recall must not match anything.

    Without this, stemming every token could pass by matching too much, and a
    green suite would prove nothing.
    """
    idx = _index("Support hours: we answer within one business day, and usually sooner.")
    assert idx.matches("business premises") == []
    assert idx.matches("calendar days") == []


def test_no_match_returns_empty():
    idx = _index("Totally unrelated content about gardening.")
    assert idx.matches("encryption at rest") == []


def test_multiple_snippets_return_all_hits():
    idx = EvidenceIndex(
        [
            Evidence("a", "a.txt", "encryption at rest with aes-256"),
            Evidence("b", "b.txt", "no crypto here"),
            Evidence("c", "c.txt", "we use encryption at rest too"),
        ]
    )
    assert idx.matches("encryption at rest") == ["a", "c"]
