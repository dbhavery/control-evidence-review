"""Command-line entry point for the control/evidence review workflow.

Usage (deterministic sample mode, no API keys)::

    python -m cer.cli review \
        --catalog controls/catalog.json \
        --evidence evidence \
        --out reports \
        --actor reviewer@example.com \
        --clock 2026-07-01T12:00:00Z

Outputs:
  reports/review.json   machine-readable report
  reports/review.html   self-contained dark HTML report
  reports/audit.jsonl   append-only audit log (one line per verdict)

The tool is decision support for a human reviewer. It does NOT certify SOC 2,
HIPAA, GDPR, or any framework.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import AuditLog, fixed_clock, utc_clock
from .catalog import load_catalog
from .engine import evaluate_all
from .evidence import load_evidence
from .llm import enrich, llm_enabled
from .models import Verdict
from .report import build_report, write_html, write_json

_VERDICT_GLYPH = {
    Verdict.SATISFIED: "[OK ]",
    Verdict.PARTIAL: "[~~ ]",
    Verdict.NEEDS_REVIEW: "[?? ]",
    Verdict.MISSING: "[XX ]",
}


def run_review(args: argparse.Namespace) -> int:
    controls = load_catalog(args.catalog)
    corpus = load_evidence(args.evidence)

    verdicts = evaluate_all(controls, corpus)
    if llm_enabled():
        verdicts = enrich(verdicts)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    clock = fixed_clock(args.clock) if args.clock else utc_clock
    generated_at = clock()

    # Audit log — append-only. Deterministic timestamp when --clock supplied.
    audit = AuditLog(out_dir / "audit.jsonl", clock=clock)
    audit.record_all(verdicts, actor=args.actor)

    report = build_report(
        verdicts, corpus, actor=args.actor, generated_at=generated_at
    )
    json_path = write_json(report, out_dir / "review.json")
    html_path = write_html(report, out_dir / "review.html")

    _print_summary(verdicts, report, json_path, html_path, out_dir)
    return 0


def _print_summary(verdicts, report, json_path, html_path, out_dir) -> None:
    s = report["summary"]
    print("Control Evidence Review — decision support, NOT certification")
    print("=" * 60)
    for v in verdicts:
        glyph = _VERDICT_GLYPH[v.verdict]
        ev = ",".join(v.matched_evidence_ids) or "-"
        print(
            f"{glyph} {v.control_id:<6} {v.verdict.value:<12} "
            f"conf={v.confidence:.2f}  evidence={ev}"
        )
    print("-" * 60)
    print(
        f"SUMMARY  satisfied={s['satisfied']}  partial={s['partial']}  "
        f"needs_review={s['needs_review']}  missing={s['missing']}"
    )
    if report["gaps"]:
        print(f"GAPS ({len(report['gaps'])}): " + ", ".join(
            g["control_id"] for g in report["gaps"]
        ))
    print("-" * 60)
    print(f"JSON report : {json_path}")
    print(f"HTML report : {html_path}")
    print(f"Audit log   : {out_dir / 'audit.jsonl'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cer",
        description=(
            "Policy/control evidence review — maps control statements to "
            "supplied evidence and produces per-control verdicts. Decision "
            "support for a human reviewer, not a certification authority."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rev = sub.add_parser("review", help="Run a control/evidence review.")
    rev.add_argument("--catalog", required=True, help="Path to controls catalog JSON.")
    rev.add_argument("--evidence", required=True, help="Path to evidence directory.")
    rev.add_argument("--out", default="reports", help="Output directory.")
    rev.add_argument(
        "--actor", default="reviewer@local", help="Reviewer/actor id for the audit log."
    )
    rev.add_argument(
        "--clock",
        default="",
        help="Fixed ISO-8601 timestamp for deterministic runs (e.g. "
        "2026-07-01T12:00:00Z). Omit to use live UTC time.",
    )
    rev.set_defaults(func=run_review)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
