"""Rule-engine correctness: SATISFIED vs PARTIAL vs MISSING vs NEEDS_REVIEW."""

from __future__ import annotations

from cer.engine import evaluate_all, evaluate_control
from cer.matcher import EvidenceIndex
from cer.models import Control, Evidence, Requirement, Verdict


def _verdict_map(controls, corpus):
    return {v.control_id: v for v in evaluate_all(controls, corpus)}


def test_all_requirements_met_is_satisfied():
    control = Control(
        id="X-1",
        title="Both met",
        description="",
        requirements=(
            Requirement("policy", ("access review",)),
            Requirement("log", ("reviewed logs",)),
        ),
    )
    corpus = [
        Evidence("e1", "e1.txt", "We completed the access review this quarter."),
        Evidence("e2", "e2.txt", "The team reviewed logs every week."),
    ]
    result = evaluate_control(control, EvidenceIndex(corpus))
    assert result.verdict is Verdict.SATISFIED
    assert set(result.matched_evidence_ids) == {"e1", "e2"}
    assert result.confidence > 0.7


def test_some_requirements_met_is_partial():
    control = Control(
        id="X-2",
        title="One met",
        description="",
        requirements=(
            Requirement("backup", ("backup schedule",)),
            Requirement("restore", ("restore test",)),
        ),
    )
    corpus = [Evidence("e1", "e1.txt", "A nightly backup schedule is documented.")]
    result = evaluate_control(control, EvidenceIndex(corpus))
    assert result.verdict is Verdict.PARTIAL
    unmet = [r.name for r in result.requirement_results if not r.met]
    assert unmet == ["restore"]


def test_no_requirements_met_is_missing():
    control = Control(
        id="X-3",
        title="Nothing matches",
        description="",
        requirements=(
            Requirement("badge", ("badge access",)),
            Requirement("visitor", ("visitor log",)),
        ),
    )
    corpus = [Evidence("e1", "e1.txt", "Unrelated evidence about coffee machines.")]
    result = evaluate_control(control, EvidenceIndex(corpus))
    assert result.verdict is Verdict.MISSING
    assert result.matched_evidence_ids == []
    assert result.is_gap is True


def test_missing_evidence_does_not_crash_and_is_gap():
    """A control with zero matching evidence must produce MISSING, not raise."""
    control = Control(
        id="X-4",
        title="Empty corpus",
        description="",
        requirements=(Requirement("thing", ("nonexistent phrase xyz",)),),
    )
    # Even against an EMPTY corpus the engine must return a verdict.
    result = evaluate_control(control, EvidenceIndex([]))
    assert result.verdict is Verdict.MISSING
    assert result.is_gap


def test_review_flag_forces_needs_review():
    control = Control(
        id="X-5",
        title="Flagged",
        description="",
        review_flags=("todo",),
        requirements=(
            Requirement("plan", ("incident response plan",)),
            Requirement("record", ("incident ticket",)),
        ),
    )
    corpus = [
        Evidence("e1", "e1.txt", "The incident response plan is documented."),
        Evidence("e2", "e2.txt", "An incident ticket was opened. TODO: finish it."),
    ]
    result = evaluate_control(control, EvidenceIndex(corpus))
    assert result.verdict is Verdict.NEEDS_REVIEW
    assert "todo" in result.review_flags_hit


def test_control_with_no_requirements_needs_review():
    control = Control(id="X-6", title="Empty", description="", requirements=())
    result = evaluate_control(control, EvidenceIndex([]))
    assert result.verdict is Verdict.NEEDS_REVIEW


def test_min_hits_threshold_not_reached_is_unmet():
    """min_hits=2 requires two distinct keyword hits to be 'met'."""
    control = Control(
        id="X-7",
        title="Needs two",
        description="",
        requirements=(
            Requirement("strong", ("mfa", "two-factor"), min_hits=2),
        ),
    )
    only_one = [Evidence("e1", "e1.txt", "We enforce mfa for admins.")]
    assert evaluate_control(control, EvidenceIndex(only_one)).verdict is Verdict.MISSING

    both = [Evidence("e1", "e1.txt", "We enforce mfa and two-factor for admins.")]
    assert evaluate_control(control, EvidenceIndex(both)).verdict is Verdict.SATISFIED


def test_full_catalog_expected_distribution(controls, corpus):
    """The shipped fixtures must yield the documented verdict spread."""
    vmap = _verdict_map(controls, corpus)
    assert vmap["AC-2"].verdict is Verdict.SATISFIED
    assert vmap["IA-5"].verdict is Verdict.SATISFIED
    assert vmap["SC-13"].verdict is Verdict.SATISFIED
    assert vmap["CP-9"].verdict is Verdict.PARTIAL
    assert vmap["RA-5"].verdict is Verdict.PARTIAL
    assert vmap["AT-2"].verdict is Verdict.PARTIAL
    assert vmap["IR-4"].verdict is Verdict.NEEDS_REVIEW
    assert vmap["PS-4"].verdict is Verdict.MISSING
    assert vmap["PE-3"].verdict is Verdict.MISSING

    counts = {}
    for v in vmap.values():
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    assert counts[Verdict.SATISFIED] == 5
    assert counts[Verdict.PARTIAL] == 3
    assert counts[Verdict.NEEDS_REVIEW] == 1
    assert counts[Verdict.MISSING] == 2


def _ceiling_corpus():
    return [Evidence(id="doc", source="doc.md", text="We follow WCAG 2.2 Level AA.")]


def test_a_requirement_with_no_matcher_is_not_evaluated_and_caps_the_control():
    """An unevaluated requirement stays in the denominator and lowers the max.

    Dropping it from the denominator instead would report SATISFIED on a control
    whose requirement nobody checked, which hides a real gap in the favourable
    direction.
    """
    control = Control(
        id="C-1",
        title="One requirement has no matcher",
        description="",
        requirements=(
            Requirement("level is named", ("level aa",)),
            Requirement("date is present", ()),
        ),
    )
    v = evaluate_control(control, EvidenceIndex(_ceiling_corpus()))

    assert v.verdict is Verdict.PARTIAL
    assert v.instrument_max == 1
    assert v.unevaluated_requirements == ["date is present"]
    assert "cannot exceed 1/2" in v.rationale
    # The unevaluated requirement must not be reported as evidence failing.
    assert "Unmet:" not in v.rationale


def test_attaching_a_matcher_clears_the_cap_with_nothing_to_remember():
    """The control for the test above, and the whole point of deriving the cap.

    A stored "cannot be checked" flag would keep asserting the limitation after
    a matcher was attached, and nothing would contradict it. Deriving it from
    the matcher's presence means attaching one clears it by construction.
    """
    corpus = _ceiling_corpus()
    capped = Control(
        id="C-1",
        title="capped",
        description="",
        requirements=(
            Requirement("level is named", ("level aa",)),
            Requirement("date is present", ()),
        ),
    )
    before = evaluate_control(capped, EvidenceIndex(corpus))
    assert before.instrument_max == 1, "control invalid: cap never applied"
    assert "cannot exceed" in before.rationale

    # Identical control, one matcher attached, nothing else touched.
    fixed = Control(
        id="C-1",
        title="capped",
        description="",
        requirements=(
            Requirement("level is named", ("level aa",)),
            Requirement("date is present", ("wcag",)),
        ),
    )
    after = evaluate_control(fixed, EvidenceIndex(corpus))

    assert after.instrument_max == 2
    assert after.unevaluated_requirements == []
    assert "cannot exceed" not in after.rationale
    assert after.verdict is Verdict.SATISFIED
