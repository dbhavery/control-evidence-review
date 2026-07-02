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
