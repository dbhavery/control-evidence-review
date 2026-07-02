"""Core data models for control/evidence review.

Plain dataclasses, stdlib only. Verdict is an enum so the rest of the code
cannot invent an out-of-spec verdict string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    """The only four verdicts a control can receive.

    Subclassing ``str`` keeps JSON serialization trivial (``verdict.value``)
    while still giving us a closed set the rule engine must choose from.
    """

    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class Requirement:
    """One named sub-requirement of a control.

    A requirement is considered *met* when at least ``min_hits`` distinct
    keywords/phrases from ``keywords`` are found in the evidence corpus.
    """

    name: str
    keywords: tuple[str, ...]
    min_hits: int = 1


@dataclass(frozen=True)
class Control:
    """A single control statement to review evidence against.

    ``id`` values such as ``AC-2`` are generic control identifiers used as
    labels only. They are NOT a claim of conformance to NIST 800-53, SOC 2,
    or any published framework.
    """

    id: str
    title: str
    description: str
    requirements: tuple[Requirement, ...]
    # Terms that, when present in matched evidence, force human review even if
    # keyword coverage looks complete (e.g. "exception", "TODO", "pending").
    review_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    """A synthetic evidence snippet supplied for review."""

    id: str
    source: str
    text: str


@dataclass
class RequirementResult:
    """Outcome of evaluating one requirement against the evidence corpus."""

    name: str
    met: bool
    matched_keywords: list[str] = field(default_factory=list)
    matched_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class ControlVerdict:
    """The full, explainable result for one control."""

    control_id: str
    title: str
    verdict: Verdict
    confidence: float
    rationale: str
    requirement_results: list[RequirementResult] = field(default_factory=list)
    matched_evidence_ids: list[str] = field(default_factory=list)
    review_flags_hit: list[str] = field(default_factory=list)

    @property
    def is_gap(self) -> bool:
        """A gap is anything not fully satisfied — the reviewer's worklist."""
        return self.verdict is not Verdict.SATISFIED

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "title": self.title,
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "matched_evidence_ids": list(self.matched_evidence_ids),
            "review_flags_hit": list(self.review_flags_hit),
            "requirements": [
                {
                    "name": r.name,
                    "met": r.met,
                    "matched_keywords": list(r.matched_keywords),
                    "matched_evidence_ids": list(r.matched_evidence_ids),
                }
                for r in self.requirement_results
            ],
        }
