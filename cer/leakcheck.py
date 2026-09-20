"""Fail-closed scan for unredacted secrets in generated artifacts.

CI runs this over ``reports/`` after a sample review. It exists because a
hand-written ``grep`` of a few literal strings cannot keep up with
:mod:`cer.redaction`: this module iterates the *same* pattern list the redactor
uses, so every family the redactor masks is a family the check can catch, and
adding a family to the redactor extends the check for free.

Two ways this check refuses to pass vacuously:

* Scanning zero files is an error, not a pass. An empty or missing output
  directory means the pipeline never ran.
* ``--expect-redacted`` requires at least one ``[REDACTED:LABEL]`` placeholder,
  so a run that silently produced no masked spans fails instead of looking
  clean.

Placeholders left behind by the redactor are blanked before scanning (the
``SECRET`` rule matches its own ``api_key=[REDACTED:SECRET]`` output, which is
evidence that redaction worked, not a leak). Blanking is length-preserving so
reported line numbers stay accurate.

Usage::

    python -m cer.leakcheck reports --expect-redacted --allow ci@example.com

Exit codes: 0 clean, 1 a secret was found, 2 nothing to scan / bad usage.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .redaction import PLACEHOLDER_RE, iter_patterns

# Suffixes that are read as text. Anything else in the output directory is
# skipped and reported, so a new binary artifact cannot hide a leak unnoticed.
TEXT_SUFFIXES = frozenset(
    {".json", ".jsonl", ".html", ".htm", ".txt", ".md", ".csv", ".log", ".conf"}
)


@dataclass(frozen=True)
class Finding:
    """One unredacted secret span found in a scanned file."""

    path: Path
    line: int
    label: str
    span: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.label}: {self.span}"


# Filler that stands in for a redaction placeholder while scanning. A double
# quote is excluded from every value character class in cer.redaction, so it
# terminates a match instead of being skipped: blanking with spaces would let
# ``api_key=<spaces>`` run on and capture the next token as the "value".
_FILLER = '"'


def _blank_placeholders(text: str) -> str:
    """Replace every ``[REDACTED:X]`` with inert filler of the same length."""
    return PLACEHOLDER_RE.sub(lambda m: _FILLER * len(m.group(0)), text)


def scan_text(
    text: str, allow: frozenset[str] = frozenset()
) -> list[tuple[int, str, str]]:
    """Return ``(line, label, span)`` for every unredacted secret in ``text``.

    ``allow`` holds exact literal strings that are present on purpose (the
    reviewer/actor id the CLI was invoked with, for example). Only an exact
    match of the offending span is exempt; any other value in the same family
    still fails.
    """
    scrubbed = _blank_placeholders(text)
    hits: list[tuple[int, str, str]] = []
    for label, pattern in iter_patterns():
        for match in pattern.finditer(scrubbed):
            span = match.group(0)
            # The SECRET rule keeps the key name and masks only the value, so
            # the value is what has to be allowed or reported.
            value = match.group(1) if label == "SECRET" and match.groups() else span
            if span in allow or value in allow:
                continue
            line = scrubbed.count("\n", 0, match.start()) + 1
            hits.append((line, label, span))
    return sorted(hits)


def scan_paths(
    root: Path, allow: frozenset[str] = frozenset()
) -> tuple[list[Finding], list[Path], list[Path]]:
    """Scan every text file under ``root``.

    Returns ``(findings, scanned, skipped)``.
    """
    findings: list[Finding] = []
    scanned: list[Path] = []
    skipped: list[Path] = []
    if root.is_file():
        targets = [root]
    else:
        targets = sorted(p for p in root.rglob("*") if p.is_file())
    for path in targets:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(path)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        scanned.append(path)
        for line, label, span in scan_text(text, allow):
            findings.append(Finding(path=path, line=line, label=label, span=span))
    return findings, scanned, skipped


def has_placeholder(paths: list[Path]) -> bool:
    """True if any scanned file still shows a redaction placeholder."""
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if PLACEHOLDER_RE.search(text):
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cer.leakcheck",
        description=(
            "Scan generated artifacts for secrets that cer.redaction should "
            "have masked. Exits non-zero if any pattern family fires."
        ),
    )
    parser.add_argument("path", help="File or directory to scan.")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="LITERAL",
        help=(
            "Exact string that is present on purpose (e.g. the --actor id "
            "recorded in the audit log). Repeatable. Exact matches only."
        ),
    )
    parser.add_argument(
        "--expect-redacted",
        action="store_true",
        help=(
            "Also fail when no [REDACTED:...] placeholder is present, so an "
            "empty or broken run cannot pass as clean."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.path)
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return 2

    findings, scanned, skipped = scan_paths(root, frozenset(args.allow))

    if not scanned:
        print(f"error: no text files to scan under {root}", file=sys.stderr)
        return 2

    for path in skipped:
        print(f"note: skipped non-text file {path}")

    if findings:
        print(f"FAIL: {len(findings)} unredacted secret(s) found:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding.format()}", file=sys.stderr)
        families = sorted({f.label for f in findings})
        print(f"Pattern families hit: {', '.join(families)}", file=sys.stderr)
        return 1

    if args.expect_redacted and not has_placeholder(scanned):
        print(
            "FAIL: no [REDACTED:...] placeholder in any scanned file; "
            "redaction never fired, so a clean scan proves nothing.",
            file=sys.stderr,
        )
        return 1

    labels = ", ".join(label for label, _ in iter_patterns())
    print(f"Leak check passed: {len(scanned)} file(s), families checked: {labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
