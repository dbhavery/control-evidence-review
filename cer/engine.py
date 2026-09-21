"""Rule engine: turn matched evidence into a per-control verdict.

Verdict rules (deterministic, no randomness):

* Evaluate each of the control's requirements. A requirement is *met* when at
  least ``min_hits`` distinct keywords match somewhere in the corpus.
* If NO requirement is met  -> MISSING            (confidence high, it's clearly a gap)
* If ALL requirements are met -> SATISFIED, UNLESS a review-flag term appears in
  the matched evidence, in which case -> NEEDS_REVIEW.
* If SOME but not all are met -> PARTIAL.
* NEEDS_REVIEW also fires when a single requirement scrapes by on exactly one
  weak keyword hit and the control asked for more scrutiny via review_flags.

Confidence = fraction of requirements met, nudged by evidence breadth. It is a
support signal for the human reviewer, not a probability claim.
"""

from __future__ import annotations

from .matcher import EvidenceIndex
from .models import (
    Control,
    ControlVerdict,
    Evidence,
    RequirementResult,
    Verdict,
)


def evaluate_control(
    control: Control, index: EvidenceIndex
) -> ControlVerdict:
    """Evaluate one control against the indexed evidence corpus."""
    req_results: list[RequirementResult] = []
    all_matched_evidence: set[str] = set()

    for req in control.requirements:
        # A requirement with nothing matchable attached is not evaluated. It is
        # NOT quietly dropped from the denominator either: a required component
        # nobody checked is still unverified, and reducing the denominator would
        # report SATISFIED on a control with an unchecked requirement, which is
        # the upward direction that hides a real gap.
        checkable = bool(req.keywords)
        matched_keywords: list[str] = []
        matched_ev: set[str] = set()
        for kw in req.keywords:
            hits = index.matches(kw)
            if hits:
                matched_keywords.append(kw)
                matched_ev.update(hits)
        met = checkable and len(matched_keywords) >= req.min_hits
        req_results.append(
            RequirementResult(
                name=req.name,
                met=met,
                matched_keywords=matched_keywords,
                matched_evidence_ids=sorted(matched_ev),
                checkable=checkable,
            )
        )
        if met:
            all_matched_evidence.update(matched_ev)

    total = len(req_results)
    met_count = sum(1 for r in req_results if r.met)

    # Detect review-flag terms inside the evidence that actually matched.
    review_hits = _review_flags_hit(control, all_matched_evidence, index)

    verdict, confidence, rationale = _decide(
        total=total,
        met_count=met_count,
        req_results=req_results,
        review_hits=review_hits,
    )

    return ControlVerdict(
        control_id=control.id,
        title=control.title,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
        requirement_results=req_results,
        matched_evidence_ids=sorted(all_matched_evidence),
        review_flags_hit=review_hits,
    )


def _review_flags_hit(
    control: Control, matched_evidence: set[str], index: EvidenceIndex
) -> list[str]:
    if not control.review_flags or not matched_evidence:
        return []
    # Restrict the flag scan to evidence that matched this control.
    subset = [ev for ev in index.corpus if ev.id in matched_evidence]
    sub_index = EvidenceIndex(subset)
    hits: list[str] = []
    for flag in control.review_flags:
        if sub_index.matches(flag):
            hits.append(flag)
    return hits


def _decide(
    total: int,
    met_count: int,
    req_results: list[RequirementResult],
    review_hits: list[str],
) -> tuple[Verdict, float, str]:
    if total == 0:
        return (
            Verdict.NEEDS_REVIEW,
            0.0,
            "Control defines no requirements; cannot be evaluated automatically.",
        )

    coverage = met_count / total

    if met_count == 0:
        return (
            Verdict.MISSING,
            0.9,
            "No supplied evidence matched any requirement of this control.",
        )

    if met_count == total:
        if review_hits:
            return (
                Verdict.NEEDS_REVIEW,
                0.6,
                "All requirements matched, but evidence contains review-flag "
                f"term(s) {review_hits} that require a human decision.",
            )
        # Full coverage; confidence scaled by how many keywords corroborated it.
        breadth = _breadth(req_results)
        confidence = min(0.99, 0.75 + 0.25 * breadth)
        return (
            Verdict.SATISFIED,
            confidence,
            "Every requirement is supported by at least one evidence snippet.",
        )

    # Partial coverage.
    if review_hits:
        rationale = (
            f"{met_count}/{total} requirements met and review-flag term(s) "
            f"{review_hits} present — needs a human decision."
        )
        return (Verdict.NEEDS_REVIEW, 0.5, rationale)

    # "Nothing matched" and "never checked" are different findings and must not
    # share a line. One is a statement about the evidence, the other about the
    # instrument, and a reader who cannot tell them apart reads a tool limit as
    # a gap in the evidence.
    unmet = [r.name for r in req_results if not r.met and r.checkable]
    unevaluated = [r.name for r in req_results if not r.checkable]
    parts = [f"{met_count}/{total} requirements met."]
    if unmet:
        parts.append(f"Unmet: {unmet}.")
    if unevaluated:
        parts.append(
            f"Not evaluated, no matcher attached: {unevaluated}. "
            f"This control cannot exceed {total - len(unevaluated)}/{total} "
            "until one is."
        )
    parts.append("Treated as a partial gap.")
    return (Verdict.PARTIAL, round(0.4 + 0.3 * coverage, 3), " ".join(parts))


def _breadth(req_results: list[RequirementResult]) -> float:
    """0..1 signal for how many keywords corroborated the met requirements."""
    met = [r for r in req_results if r.met]
    if not met:
        return 0.0
    per_req = [min(1.0, len(r.matched_keywords) / 2.0) for r in met]
    return sum(per_req) / len(per_req)


def evaluate_all(
    controls: list[Control], corpus: list[Evidence]
) -> list[ControlVerdict]:
    """Evaluate every control against the corpus, preserving control order."""
    index = EvidenceIndex(corpus)
    return [evaluate_control(c, index) for c in controls]
