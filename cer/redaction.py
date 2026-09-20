"""Redaction pass for synthetic secrets / PII.

Every evidence excerpt is passed through :func:`redact` before it is written to
a report or the audit log, so raw tokens/emails/IPs never leave the tool. The
patterns target the *synthetic* secret shapes baked into the fixtures; this is a
demonstration of a real masking pass, not a claim of exhaustive DLP coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Order matters: more specific / higher-entropy patterns first so a token is not
# partially eaten by a broader rule. Each entry is (label, compiled regex).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS-style access key id.
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Generic "secret = value" / "token: value" / "password=..." assignments.
    (
        "SECRET",
        re.compile(
            r"\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b"
            r"\s*[:=]\s*['\"]?([^\s'\"]{6,})",
            re.IGNORECASE,
        ),
    ),
    # Bearer tokens.
    ("BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{10,}")),
    # Long high-entropy hex/base64-ish blobs (>= 24 chars).
    ("BLOB", re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")),
    # Email addresses.
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # IPv4 addresses.
    (
        "IP",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
        ),
    ),
]


# Shape of a mask that :func:`redact` leaves behind, e.g. ``[REDACTED:EMAIL]``.
# A leak check must treat these as proof that redaction fired, not as a secret:
# the SECRET rule would otherwise re-match its own placeholder.
PLACEHOLDER_RE = re.compile(r"\[REDACTED:[A-Z_]+\]")


def pattern_labels() -> tuple[str, ...]:
    """Every pattern family this module redacts, in match order.

    Public so a leak check can prove it covers all of them instead of
    re-listing a subset that silently drifts out of date.
    """
    return tuple(label for label, _ in _PATTERNS)


def iter_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """The (label, compiled regex) pairs used by :func:`redact`."""
    return tuple(_PATTERNS)


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str) -> RedactionResult:
    """Mask synthetic secrets/PII in ``text``.

    Returns the redacted text plus a per-label count of how many spans were
    masked, so callers/tests can assert that redaction actually fired.
    """
    counts: dict[str, int] = {}

    def _mask_for(label: str, match: re.Match[str]) -> str:
        counts[label] = counts.get(label, 0) + 1
        # For the "SECRET" rule we keep the key name and mask only the value
        # (group 1) so the reader still knows *what* was present.
        if label == "SECRET" and match.groups():
            value = match.group(1)
            return match.group(0).replace(value, f"[REDACTED:{label}]")
        return f"[REDACTED:{label}]"

    redacted = text
    for label, pattern in _PATTERNS:
        redacted = pattern.sub(lambda m, _l=label: _mask_for(_l, m), redacted)

    return RedactionResult(text=redacted, counts=counts)


def redact_text(text: str) -> str:
    """Convenience wrapper returning only the masked string."""
    return redact(text).text
