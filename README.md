# control-evidence-review

## The problem

Before an audit or a security questionnaire, someone checks each security
control against the policies, configs and logs that are supposed to support it.
Done by hand, gaps get missed, the reasoning behind each call is not written
down, and excerpts pasted into the review can expose API keys, tokens, email
addresses or IP addresses.

## How it solves it

It reads a catalog of controls and a folder of evidence files, and gives each
control one of four verdicts: `SATISFIED`, `PARTIAL`, `MISSING` or
`NEEDS_REVIEW`. Each verdict comes with the evidence that matched, the reason
for the verdict, and a confidence value.

- **Fixed rules set the verdict.** Each control lists named requirements, and a
  requirement is met when enough of its keywords appear in the evidence. The
  same evidence always produces the same verdict.
- **Secrets and personal data are masked** in every excerpt before it reaches a
  report or the audit log.
- **A leak check rescans the output** for anything the masking should have
  caught, and fails if it finds one.
- **Every verdict is logged** to an append-only JSONL audit log.
- **An optional model can only add a note.** It never changes a verdict.

This is decision support for a human reviewer. It is not a certification
authority and makes no claim of SOC 2, HIPAA, GDPR or any other compliance. The
control identifiers (`AC-2`, `AU-6` and so on) are generic labels for
readability, not a claim of conformance to NIST 800-53 or any published
framework. All shipped data is synthetic.

## Who it helps

- Compliance and security analysts preparing control evidence before an audit.
- Small companies answering security questionnaires without a GRC tool.
- Reviewers who need verdicts they can repeat and explain, with the reasoning
  recorded.

## Technical details

- **Language and dependencies.** Python 3.11 or later, standard library only.
  pytest is needed for the tests, and the `anthropic` package only for the
  optional model note.
- **Offline by default.** No API keys and no network access.
- **Matching.** Case-insensitive, whole-word matching with multi-word phrases
  and a small suffix stemmer, so "reviewed" matches "review" and "log" does not
  match inside "blog".
- **Masking.** Six pattern families: `AWS_KEY`, `SECRET` (`api_key=...` and
  `token:...` assignments), `BEARER`, `BLOB` (strings of 24 or more base64-style
  characters), `EMAIL` and `IP`.
- **Audit log.** One JSON line per verdict, opened in append mode. `--clock`
  fixes the timestamp so a run is repeatable byte for byte.
- **Tests.** The tests cover each verdict the engine can return, the matcher,
  masking for each pattern family, the audit log, report generation, the
  loaders, the CLI end to end, and the leak check. The leak check tests plant one
  fake secret per family and require a non-zero exit naming that family, then
  remove it and require a clean exit. An empty output folder, or output with no
  `[REDACTED:...]` placeholder, is reported as a failure rather than a pass.
- **CI.** GitHub Actions on Python 3.11, 3.12 and 3.13 runs the tests, a sample
  review with a fixed clock, and the leak check on the generated reports.

## How it decides

Rules are applied in this order (`cer/engine.py`):

- A control with no requirements: `NEEDS_REVIEW`.
- No requirement met: `MISSING`. These are listed as gaps.
- All requirements met: `SATISFIED`, unless one of the control's
  `review_flags` terms (for example `todo`, `exception`, `pending`) appears in
  the matched evidence, in which case `NEEDS_REVIEW`.
- Some but not all requirements met: `PARTIAL`, with the same review-flag rule
  leading to `NEEDS_REVIEW`.

Review flags are only looked for in evidence that matched one of the control's
met requirements.

## Architecture

```
controls/catalog.json ─┐
                       ├─► catalog.load_catalog ─► [Control]
evidence/*.txt ────────┘   evidence.load_evidence ─► [Evidence]
                                                        │
                                    matcher.EvidenceIndex (normalize+stem+index)
                                                        │
                              engine.evaluate_all ─► [ControlVerdict]
                                        │                    │
                    audit.AuditLog (append-only JSONL,       │
                    injectable clock for determinism)        │
                                                             ▼
                         report.build_report ─► JSON  +  render_html ─► HTML
                                                   (redaction.redact on every excerpt)
```

| Module | Responsibility |
|--------|----------------|
| `cer/models.py` | Dataclasses and the closed `Verdict` enum |
| `cer/catalog.py` | Load and validate the control catalog JSON |
| `cer/evidence.py` | Load the evidence directory into snippets |
| `cer/matcher.py` | Normalize, stem and match phrases |
| `cer/engine.py` | Rule engine: per-control verdict, rationale and confidence |
| `cer/redaction.py` | Mask secrets and personal data before output |
| `cer/leakcheck.py` | Scan generated files for anything the masking should have caught |
| `cer/audit.py` | Append-only JSONL audit log with an injectable clock |
| `cer/report.py` | JSON report and self-contained HTML report |
| `cer/llm.py` | Optional, env-gated model note (never required) |
| `cer/cli.py` | `cer review` entry point |

## Install

```bash
git clone https://github.com/dbhavery/control-evidence-review.git
cd control-evidence-review
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash
#                        source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"           # installs pytest; the core needs nothing
```

## Run a review

```bash
python -m cer.cli review \
  --catalog controls/catalog.json \
  --evidence evidence \
  --out reports \
  --actor reviewer@example.com \
  --clock 2026-07-01T12:00:00Z      # omit --clock to use live UTC time
```

Expected summary from the shipped fixtures:

```
SUMMARY  satisfied=5  partial=3  needs_review=1  missing=2
GAPS (6): CP-9, IR-4, RA-5, AT-2, PS-4, PE-3
```

The run writes three files:

- `reports/review.json`: machine-readable report
- `reports/review.html`: self-contained HTML report (inline CSS, no CDN)
- `reports/audit.jsonl`: append-only audit log, one line per verdict

## Open the HTML report

```bash
# Windows
start reports/review.html
# macOS: open reports/review.html   |   Linux: xdg-open reports/review.html
```

## View the audit log

```bash
cat reports/audit.jsonl              # one JSON object per line, append-only
```

Each line carries `schema_version`, `timestamp`, `actor`, `control_id`,
`verdict`, `confidence`, `evidence_ids` and `rationale`.

## Run the leak check

```bash
python -m cer.leakcheck reports --expect-redacted --allow reviewer@example.com
```

It checks the same pattern list `cer/redaction.py` masks with, so it cannot
cover fewer families than the redactor. `--allow` exempts one exact value (here
the actor id, which the audit log records on purpose).

## Run the tests

```bash
python -m pytest -q
```

## Optional model note (off by default)

The default flow uses no model and no API key. To add a natural-language
reviewer note on top of the rule-based verdicts:

```bash
export CER_LLM=1
export ANTHROPIC_API_KEY=...        # your key; never stored in the repo
pip install ".[llm]"
python -m cer.cli review --catalog controls/catalog.json --evidence evidence
```

If `CER_LLM` is set without a key or without the `anthropic` package, the tool
stops with an error message instead of producing a placeholder note. The
verdict is always the rule engine's; the model only appends a note.

## Fixtures

- `controls/catalog.json`: 11 generic controls, each with named requirements
  and keyword sets. Some controls carry `review_flags` (for example `todo`)
  that lead to `NEEDS_REVIEW`.
- `evidence/`: 14 synthetic snippets. Some fully satisfy a control, some
  satisfy only one requirement (`PARTIAL`), and two controls (`PS-4`, `PE-3`)
  have no matching evidence (`MISSING`). Several snippets contain fake secrets
  (emails, IPs, `api_key=...`, bearer tokens, an AWS-style key) to show the
  masking.

Nothing here is real. Do not point this at production data as it is: the
masking targets the patterns listed above and does not claim full data loss
prevention coverage.

## License

MIT. See `LICENSE`.
