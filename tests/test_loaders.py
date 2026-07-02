"""Catalog + evidence loaders and the CLI end-to-end path."""

from __future__ import annotations

import json

import pytest

from cer.catalog import load_catalog
from cer.cli import main
from cer.evidence import load_evidence


def test_catalog_loads_all_controls(catalog_path):
    controls = load_catalog(catalog_path)
    assert len(controls) == 11
    ids = {c.id for c in controls}
    assert "AC-2" in ids and "PE-3" in ids
    # Every control has at least one requirement.
    assert all(c.requirements for c in controls)


def test_catalog_rejects_duplicate_ids(tmp_path):
    bad = tmp_path / "dup.json"
    bad.write_text(
        json.dumps(
            {
                "controls": [
                    {"id": "A-1", "title": "x", "requirements": [
                        {"name": "r", "keywords": ["k"]}]},
                    {"id": "A-1", "title": "y", "requirements": [
                        {"name": "r", "keywords": ["k"]}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate control id"):
        load_catalog(bad)


def test_evidence_loads_directory(evidence_dir):
    corpus = load_evidence(evidence_dir)
    assert len(corpus) == 14
    ids = {e.id for e in corpus}
    assert "logging-config" in ids
    assert all(e.text for e in corpus)


def test_evidence_missing_dir_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        load_evidence(tmp_path / "does-not-exist")


def test_cli_review_end_to_end(tmp_path, catalog_path, evidence_dir):
    out = tmp_path / "out"
    rc = main(
        [
            "review",
            "--catalog", str(catalog_path),
            "--evidence", str(evidence_dir),
            "--out", str(out),
            "--actor", "reviewer@example.com",
            "--clock", "2026-07-01T12:00:00Z",
        ]
    )
    assert rc == 0
    assert (out / "review.json").exists()
    assert (out / "review.html").exists()
    assert (out / "audit.jsonl").exists()

    report = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert report["summary"]["missing"] == 2
    # Audit log has one line per control.
    lines = [
        ln for ln in (out / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) == 11


def test_cli_bad_catalog_returns_error_code(tmp_path, evidence_dir):
    rc = main(
        [
            "review",
            "--catalog", str(tmp_path / "nope.json"),
            "--evidence", str(evidence_dir),
            "--out", str(tmp_path / "o"),
        ]
    )
    assert rc == 2
