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


def test_no_excerpts_withholds_text_but_keeps_every_finding():
    """The publishable-findings mode must lose quotes and nothing else.

    A summary report is only worth publishing if it says exactly what the full
    one said. This asserts the verdicts, rationales, matched keywords and
    evidence ids are identical between the two, and that the only difference is
    the quoted text.
    """
    from cer.catalog import load_catalog
    from cer.engine import evaluate_all
    from cer.models import Evidence
    from cer.report import build_report

    corpus = [
        Evidence("p1", "p1.md", "We keep that email for 12 months and then delete it."),
        Evidence("p2", "p2.md", "Backups run nightly and a restore test is recorded."),
    ]
    controls = load_catalog("controls/catalog.json")
    verdicts = evaluate_all(controls, corpus)

    full = build_report(verdicts, corpus, actor="t", generated_at="2026-01-01T00:00:00Z")
    quiet = build_report(
        verdicts,
        corpus,
        actor="t",
        generated_at="2026-01-01T00:00:00Z",
        include_excerpts=False,
    )

    assert full["summary"] == quiet["summary"]
    assert full["gaps"] == quiet["gaps"]
    assert full["meta"]["excerpts_included"] is True
    assert quiet["meta"]["excerpts_included"] is False

    for a, b in zip(full["controls"], quiet["controls"], strict=True):
        assert a["verdict"] == b["verdict"]
        assert a["rationale"] == b["rationale"]
        assert a["requirements"] == b["requirements"]
        assert [e["evidence_id"] for e in a["evidence"]] == [
            e["evidence_id"] for e in b["evidence"]
        ]
        assert all(e["excerpt"] == "" for e in b["evidence"])

    # Control: the full report must actually carry text, or the assertion
    # above passes for the wrong reason on an empty corpus.
    assert any(e["excerpt"] for c in full["controls"] for e in c["evidence"])


def test_withheld_quote_is_labelled_not_blank_in_html():
    """An empty excerpt must not read as absent evidence."""
    from cer.engine import evaluate_all
    from cer.catalog import load_catalog
    from cer.models import Evidence
    from cer.report import build_report, render_html

    from cer.evidence import load_evidence

    # The repo's own sample corpus, because a corpus that matches nothing
    # renders "No matching evidence supplied" and the assertion below would
    # pass or fail for reasons that have nothing to do with withholding.
    corpus = load_evidence("evidence")
    verdicts = evaluate_all(load_catalog("controls/catalog.json"), corpus)
    quiet = build_report(
        verdicts, corpus, actor="t", generated_at="2026-01-01T00:00:00Z",
        include_excerpts=False,
    )
    html_out = render_html(quiet)
    assert "Quotation withheld by the evidence owner" in html_out
    assert "evidence quotations withheld by the evidence owner" in html_out


def test_no_excerpts_also_withholds_review_flag_terms():
    """A review flag is a string found in the evidence, so it is evidence.

    Regression: the first publishable run withheld every quotation and still
    printed the evidence owner's internal marker eleven times, because the flag
    terms travel in review_flags_hit AND are interpolated into the engine's
    rationale AND repeated in the gap worklist. All three paths are covered.
    """
    from cer.catalog import load_catalog
    from cer.engine import evaluate_all
    from cer.evidence import load_evidence
    from cer.report import build_report, render_html

    corpus = load_evidence("evidence")
    verdicts = evaluate_all(load_catalog("controls/catalog.json"), corpus)

    full = build_report(verdicts, corpus, actor="t", generated_at="2026-01-01T00:00:00Z")
    quiet = build_report(
        verdicts, corpus, actor="t", generated_at="2026-01-01T00:00:00Z",
        include_excerpts=False,
    )

    # Control: the sample corpus must actually trip a review flag, or this
    # test passes for the wrong reason.
    fired = [c for c in full["controls"] if c["review_flags_hit"]]
    assert fired, "sample corpus trips no review flag; test proves nothing"
    terms = {t for c in fired for t in c["review_flags_hit"]}

    quiet_text = json.dumps(quiet) + render_html(quiet)
    for term in terms:
        assert term not in quiet_text, f"review-flag term {term!r} leaked"

    # The finding itself must survive: same verdicts, and the flag is still
    # reported as having fired.
    assert [c["verdict"] for c in full["controls"]] == [
        c["verdict"] for c in quiet["controls"]
    ]
    quiet_fired = [c for c in quiet["controls"] if c["review_flags_hit"]]
    assert len(quiet_fired) == len(fired)
