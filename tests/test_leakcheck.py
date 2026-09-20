"""The CI leak check must be able to FAIL, per pattern family.

A secret scan with no test that it detects anything is how the old three-literal
grep survived: one of its three strings (``sk_live_``) appeared nowhere but
inside the grep itself, so a third of the check could never fire.

Every test here plants an obviously fake secret, proves the check fails the
build, then removes it and proves the check passes. ``SAMPLES`` is asserted
against :func:`cer.redaction.pattern_labels`, so adding a family to the redactor
without extending this proof breaks the suite instead of quietly widening the
gap between what is masked and what is verified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cer.cli import main as cli_main
from cer.leakcheck import main as leakcheck_main
from cer.leakcheck import scan_text
from cer.redaction import pattern_labels, redact_text

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# One obviously fake secret per pattern family in cer.redaction. Documentation
# ranges and example domains only: none of these is a usable credential.
SAMPLES: dict[str, str] = {
    "AWS_KEY": "AKIAFAKEFAKEFAKE0000",
    "SECRET": "api_key=NOT-A-REAL-KEY-000000",
    "BEARER": "Bearer NOTaREALtokenFAKE0000",
    "BLOB": "NOTaREALblobFAKE000000000000",
    "EMAIL": "nobody.fake@example.invalid",
    "IP": "203.0.113.9",
}

# A line of already-redacted output. The SECRET rule matches its own
# placeholder, so a scanner that does not account for that fires on clean input.
REDACTED_LINE = 'syslog tcp("[REDACTED:IP]") api_key=[REDACTED:SECRET]'


def _write_report(directory: Path, leaked: str, actor: str | None = None) -> Path:
    """Write a minimal report containing redacted output plus ``leaked``."""
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"excerpt": REDACTED_LINE, "leaked": leaked}
    if actor is not None:
        payload["actor"] = actor
    path = directory / "review.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_samples_cover_every_redaction_family():
    """The proof below must exercise every family the redactor masks."""
    assert set(SAMPLES) == set(pattern_labels())


@pytest.mark.parametrize("label", sorted(SAMPLES))
def test_planted_secret_fails_the_check(tmp_path, label, capsys):
    _write_report(tmp_path / label, SAMPLES[label])
    rc = leakcheck_main([str(tmp_path / label), "--expect-redacted"])
    err = capsys.readouterr().err
    assert rc == 1, f"{label} planted but the check passed"
    assert label in err
    assert f"Pattern families hit: {label}" in err


@pytest.mark.parametrize("label", sorted(SAMPLES))
def test_removing_the_secret_passes_the_check(tmp_path, label, capsys):
    # Same file, same fixture, with the planted value run through the redactor.
    _write_report(tmp_path / label, redact_text(SAMPLES[label]))
    rc = leakcheck_main([str(tmp_path / label), "--expect-redacted"])
    out = capsys.readouterr().out
    assert rc == 0, f"{label} redacted but the check still failed"
    assert "Leak check passed" in out


def test_redaction_placeholders_alone_do_not_trip_the_check(tmp_path, capsys):
    _write_report(tmp_path / "clean", "[REDACTED:SECRET]")
    assert leakcheck_main([str(tmp_path / "clean"), "--expect-redacted"]) == 0
    assert "passed" in capsys.readouterr().out


def test_empty_directory_is_an_error_not_a_pass(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    rc = leakcheck_main([str(tmp_path / "empty"), "--expect-redacted"])
    assert rc == 2
    assert "no text files to scan" in capsys.readouterr().err


def test_missing_directory_is_an_error(tmp_path, capsys):
    rc = leakcheck_main([str(tmp_path / "nope"), "--expect-redacted"])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


def test_output_with_no_redaction_placeholder_fails(tmp_path, capsys):
    target = tmp_path / "unmasked"
    target.mkdir()
    report = target / "review.json"
    report.write_text('{"excerpt": "nothing masked"}', encoding="utf-8")
    rc = leakcheck_main([str(target), "--expect-redacted"])
    assert rc == 1
    assert "redaction never fired" in capsys.readouterr().err


def test_allow_exempts_only_the_exact_literal(tmp_path, capsys):
    target = tmp_path / "allow"
    _write_report(target, "someone.else@example.invalid", actor="ci@example.com")
    # The actor id is recorded on purpose and is allowed...
    rc = leakcheck_main([str(target), "--expect-redacted", "--allow", "ci@example.com"])
    err = capsys.readouterr().err
    # ...but another address in the same family still fails the build.
    assert rc == 1
    assert "someone.else@example.invalid" in err

    _write_report(target, "[REDACTED:EMAIL]", actor="ci@example.com")
    rc = leakcheck_main([str(target), "--expect-redacted", "--allow", "ci@example.com"])
    assert rc == 0


def test_findings_report_line_numbers(tmp_path):
    text = "\n".join(["clean line", REDACTED_LINE, SAMPLES["IP"]])
    hits = scan_text(text)
    assert hits == [(3, "IP", SAMPLES["IP"])]


def test_non_text_files_are_reported_as_skipped(tmp_path, capsys):
    target = tmp_path / "mixed"
    _write_report(target, "[REDACTED:EMAIL]")
    (target / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert leakcheck_main([str(target), "--expect-redacted"]) == 0
    assert "skipped non-text file" in capsys.readouterr().out


def test_real_review_output_passes_the_check(tmp_path, capsys):
    """End-to-end control: the actual pipeline output must survive the check."""
    out_dir = tmp_path / "reports"
    rc = cli_main(
        [
            "review",
            "--catalog",
            str(REPO_ROOT / "controls" / "catalog.json"),
            "--evidence",
            str(REPO_ROOT / "evidence"),
            "--out",
            str(out_dir),
            "--actor",
            "ci@example.com",
            "--clock",
            "2026-07-01T12:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    assert (
        leakcheck_main(
            [str(out_dir), "--expect-redacted", "--allow", "ci@example.com"]
        )
        == 0
    )


def test_ci_workflow_runs_the_leak_check():
    """Guard the fix: the workflow must invoke this check, not a literal grep."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "cer.leakcheck" in workflow
    assert "--expect-redacted" in workflow
    # The dead literal that could never fire must not come back.
    assert "sk_live_" not in workflow
