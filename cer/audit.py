"""Append-only JSONL audit log of every verdict decision.

Determinism: the timestamp source is an injectable ``clock`` callable. Sample /
test runs pass a fixed clock so the log is byte-reproducible; real runs default
to UTC wall-clock time.

Append-only: entries are only ever appended (mode ``"a"``) and each line is one
self-contained JSON object. We never rewrite earlier lines.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .models import ControlVerdict

Clock = Callable[[], str]


def utc_clock() -> str:
    """Default clock: current UTC time, ISO-8601 with a trailing 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fixed_clock(timestamp: str) -> Clock:
    """Build a clock that always returns ``timestamp`` (for deterministic runs)."""

    def _clock() -> str:
        return timestamp

    return _clock


# Every audit record carries this schema version so downstream consumers can
# detect format changes.
SCHEMA_VERSION = 1

# Required keys in every audit record (validated by tests).
AUDIT_FIELDS = (
    "schema_version",
    "timestamp",
    "actor",
    "control_id",
    "verdict",
    "confidence",
    "evidence_ids",
    "rationale",
)


class AuditLog:
    """Append-only writer/reader for the JSONL audit trail."""

    def __init__(self, path: str | Path, clock: Clock | None = None) -> None:
        self.path = Path(path)
        self.clock = clock or utc_clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, verdict: ControlVerdict, actor: str) -> dict:
        """Append one verdict decision and return the written record."""
        entry = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": self.clock(),
            "actor": actor,
            "control_id": verdict.control_id,
            "verdict": verdict.verdict.value,
            "confidence": round(verdict.confidence, 3),
            "evidence_ids": list(verdict.matched_evidence_ids),
            "rationale": verdict.rationale,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        return entry

    def record_all(self, verdicts: list[ControlVerdict], actor: str) -> list[dict]:
        return [self.record(v, actor) for v in verdicts]

    def read_all(self) -> list[dict]:
        """Read every record back. Blank lines are skipped."""
        if not self.path.exists():
            return []
        records: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records


def validate_record(record: dict) -> None:
    """Raise ``ValueError`` if ``record`` is missing a required audit field."""
    missing = [f for f in AUDIT_FIELDS if f not in record]
    if missing:
        raise ValueError(f"Audit record missing fields: {missing}")
    if record["verdict"] not in {
        "SATISFIED",
        "PARTIAL",
        "MISSING",
        "NEEDS_REVIEW",
    }:
        raise ValueError(f"Invalid verdict in audit record: {record['verdict']}")
