"""Keyword / phrase matching over the evidence corpus.

Deterministic, no external services. Matching is case-insensitive and
whitespace-normalized, and supports multi-word phrases (e.g. "access review")
in addition to single tokens. This is the "semantic-ish" layer: we normalize,
handle simple plural/verb variants via stemming of the last token, and match on
word boundaries so "log" does not match inside "blog".
"""

from __future__ import annotations

import re

from .models import Evidence

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase and collapse all non-alphanumeric runs to single spaces."""
    return " ".join(_WORD_SPLIT.split(text.lower())).strip()


def _stem(token: str) -> str:
    """Very small suffix stemmer so 'reviews'/'reviewed' match 'review'.

    Intentionally conservative — only trims common English inflections. This is
    not a linguistic stemmer; it just widens obvious variants deterministically.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def _stem_phrase(phrase: str) -> str:
    """Stem EVERY token, because the index stems every token.

    This used to stem only the last one, which made the stemmed path dead for
    any phrase whose earlier tokens the stemmer alters. ``EvidenceIndex``
    builds its stemmed view with ``_stem`` applied to each token, so a policy
    reading "within one business day" is indexed as "within one busines day".
    A keyword of "business days" stemmed only on the last token stayed
    "business day" and matched neither the literal text (plural vs singular)
    nor the stemmed text ("business" vs "busines"). The requirement came back
    unmet against a document that plainly satisfied it.

    That is the worst failure this file can have. A false positive is caught by
    reading the matched excerpt; a false negative shows up as MISSING with no
    evidence to read, which looks exactly like a real gap.
    """
    tokens = [_stem(t) for t in normalize(phrase).split()]
    return " ".join(tokens)


class EvidenceIndex:
    """Precomputed normalized + stemmed view of every evidence snippet."""

    def __init__(self, corpus: list[Evidence]) -> None:
        self.corpus = corpus
        self._normalized: dict[str, str] = {}
        self._stemmed: dict[str, str] = {}
        for ev in corpus:
            norm = normalize(ev.text)
            self._normalized[ev.id] = norm
            self._stemmed[ev.id] = " ".join(_stem(t) for t in norm.split())

    def matches(self, keyword: str) -> list[str]:
        """Return the ids of evidence snippets that contain ``keyword``.

        A hit requires a whole-word (or whole-phrase) boundary match, tried
        first on the literal normalized text, then on the stemmed variant.
        """
        norm_kw = normalize(keyword)
        if not norm_kw:
            return []
        stem_kw = _stem_phrase(keyword)
        hits: list[str] = []
        for ev in self.corpus:
            if _phrase_in(norm_kw, self._normalized[ev.id]) or _phrase_in(
                stem_kw, self._stemmed[ev.id]
            ):
                hits.append(ev.id)
        return hits


def _phrase_in(needle: str, haystack: str) -> bool:
    """Whole-word/phrase containment on normalized (space-delimited) strings."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
