"""Audit log: append-only behavior, schema, deterministic clock."""

from __future__ import annotations

import json

from cer.audit import AuditLog, fixed_clock, validate_record
from cer.engine import evaluate_all


def test_append_only_accumulates(tmp_path, controls, corpus):
    verdicts = evaluate_all(controls, corpus)
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path, clock=fixed_clock("2026-07-01T00:00:00Z"))

    log.record_all(verdicts, actor="a@example.com")
    first = log.read_all()
    assert len(first) == len(verdicts)

    # A second run appends; it does not truncate the earlier run.
    log.record_all(verdicts, actor="b@example.com")
    second = log.read_all()
    assert len(second) == 2 * len(verdicts)
    assert second[: len(verdicts)] == first


def test_deterministic_timestamp(tmp_path, controls, corpus):
    verdicts = evaluate_all(controls, corpus)
    log = AuditLog(tmp_path / "a.jsonl", clock=fixed_clock("2026-01-02T03:04:05Z"))
    log.record_all(verdicts, actor="r@example.com")
    for rec in log.read_all():
        assert rec["timestamp"] == "2026-01-02T03:04:05Z"


def test_every_record_has_schema(tmp_path, controls, corpus):
    verdicts = evaluate_all(controls, corpus)
    log = AuditLog(tmp_path / "a.jsonl", clock=fixed_clock("2026-07-01T12:00:00Z"))
    log.record_all(verdicts, actor="r@example.com")
    for rec in log.read_all():
        validate_record(rec)  # raises on any missing/invalid field
        assert rec["schema_version"] == 1
        assert isinstance(rec["evidence_ids"], list)


def test_each_line_is_standalone_json(tmp_path, controls, corpus):
    verdicts = evaluate_all(controls, corpus)
    path = tmp_path / "a.jsonl"
    log = AuditLog(path, clock=fixed_clock("2026-07-01T12:00:00Z"))
    log.record_all(verdicts, actor="r@example.com")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(verdicts)
    for ln in lines:
        json.loads(ln)  # each line parses independently


def test_validate_record_rejects_bad_verdict():
    bad = {
        "schema_version": 1,
        "timestamp": "t",
        "actor": "a",
        "control_id": "X-1",
        "verdict": "TOTALLY_FINE",
        "confidence": 1.0,
        "evidence_ids": [],
        "rationale": "r",
    }
    try:
        validate_record(bad)
    except ValueError as exc:
        assert "Invalid verdict" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for bad verdict")
