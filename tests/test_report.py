"""Report generation: valid JSON, valid self-contained HTML, redacted excerpts."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from cer.engine import evaluate_all
from cer.report import build_report, render_html, write_html, write_json


def _report(controls, corpus):
    verdicts = evaluate_all(controls, corpus)
    return build_report(
        verdicts, corpus, actor="reviewer@example.com",
        generated_at="2026-07-01T12:00:00Z",
    )


def test_report_summary_counts(controls, corpus):
    report = _report(controls, corpus)
    s = report["summary"]
    assert s["satisfied"] == 5
    assert s["partial"] == 3
    assert s["needs_review"] == 1
    assert s["missing"] == 2
    # Summary total equals the number of controls.
    assert sum(s.values()) == report["meta"]["control_count"]


def test_gaps_list_contains_non_satisfied(controls, corpus):
    report = _report(controls, corpus)
    gap_ids = {g["control_id"] for g in report["gaps"]}
    assert {"CP-9", "RA-5", "AT-2", "IR-4", "PS-4", "PE-3"} == gap_ids


def test_json_roundtrips(tmp_path, controls, corpus):
    report = _report(controls, corpus)
    path = write_json(report, tmp_path / "review.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["summary"] == report["summary"]
    assert len(loaded["controls"]) == report["meta"]["control_count"]


def test_report_excerpts_are_redacted(controls, corpus):
    report = _report(controls, corpus)
    blob = json.dumps(report)
    # None of the synthetic secrets may appear anywhere in the report payload.
    for secret in (
        "alice.admin@example.com",
        "sandbox-demo-not-a-real-key-0001",
        "AKIAIOSFODNN7EXAMPLE",
        "abcdEFGH1234ijklMNOP5678",
        "10.42.13.7",
    ):
        assert secret not in blob
    assert "[REDACTED:" in blob


class _Validator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags = 0

    def handle_starttag(self, tag, attrs):
        self.tags += 1


def test_html_is_wellformed_and_selfcontained(controls, corpus):
    report = _report(controls, corpus)
    html = render_html(report)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html.strip()[-10:]
    # No external resources: no CDN links, no remote scripts/styles.
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html.lower()
    # Parses without raising.
    parser = _Validator()
    parser.feed(html)
    assert parser.tags > 20


def test_html_shows_verdicts_and_disclaimer(controls, corpus):
    report = _report(controls, corpus)
    html = render_html(report)
    assert "NOT a certification" in html
    for cid in ("AC-2", "PS-4", "IR-4"):
        assert cid in html
    for verdict in ("SATISFIED", "PARTIAL", "MISSING", "NEEDS_REVIEW"):
        assert verdict in html


def test_write_html_creates_file(tmp_path, controls, corpus):
    report = _report(controls, corpus)
    path = write_html(report, tmp_path / "review.html")
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
