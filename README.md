# Control / Policy Evidence Review

A local Python CLI that maps **control statements** to **supplied evidence** and
produces a **per-control verdict** — `SATISFIED`, `PARTIAL`, `MISSING`, or
`NEEDS_REVIEW` — with the matched evidence, a rationale, and a confidence signal.

> **Framing (read this).** This is a **policy/control evidence review** aid —
> **decision support for a human reviewer**. It is **not** a certification
> authority and makes **no** claim of SOC 2, HIPAA, GDPR, or any other
> compliance. The control identifiers (`AC-2`, `AU-6`, …) are **generic labels**
> for readability, not a claim of conformance to NIST 800-53 or any published
> framework. All shipped data is **synthetic** and redaction-safe.

The tool runs fully offline with **no API keys** and **no runtime dependencies**
(pure Python standard library, 3.11+). An optional, env-gated LLM enrichment
mode exists but is never required.

---

## Start here (for reviewers)

    pip install -e ".[dev]"
    python -m cer.cli review --catalog controls/catalog.json --evidence evidence --out reports --actor reviewer@example.com

Then open `reports/review.html` (per-control verdicts with redacted evidence), tail `reports/audit.jsonl` (append-only audit log), and read `tests/` (40 tests) — including the redaction and MISSING-evidence tests.

## What it does

1. **Ingests** a control catalog (JSON) and an evidence corpus (a directory of
   synthetic `.txt` / `.md` / `.conf` snippets).
2. **Matches** each control's requirements against the evidence with a real,
   deterministic rule engine (normalized keyword/phrase matching + light
   stemming + word-boundary safety). Each control declares named
   sub-requirements; a requirement is *met* when its keywords are found.
3. **Decides** a verdict per control:
   - all requirements met → `SATISFIED`
   - some met → `PARTIAL`
   - none met → `MISSING` (listed as a gap; never crashes)
   - review-flag term present (e.g. `TODO`, `exception`, `pending`) →
     `NEEDS_REVIEW`
4. **Redacts** synthetic secrets/PII (emails, IPs, API keys, bearer tokens,
   AWS-style keys, `secret=…` assignments) from every excerpt before it reaches
   a report or the audit log.
5. **Writes** three artifacts:
   - `reports/review.json` — machine-readable report
   - `reports/review.html` — self-contained dark HTML report (inline CSS, no CDN)
   - `reports/audit.jsonl` — append-only JSONL audit trail, one line per verdict

## Architecture (60-second read)

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
| `cer/models.py` | Dataclasses + the closed `Verdict` enum |
| `cer/catalog.py` | Load/validate the control catalog JSON |
| `cer/evidence.py` | Load the evidence directory into snippets |
| `cer/matcher.py` | Deterministic normalize + stem + phrase matching |
| `cer/engine.py` | Rule engine → per-control verdict + rationale + confidence |
| `cer/redaction.py` | Mask synthetic secrets/PII before output |
| `cer/audit.py` | Append-only JSONL audit log, injectable clock |
| `cer/report.py` | Build JSON report + self-contained HTML |
| `cer/llm.py` | Optional, env-gated LLM reviewer note (never required) |
| `cer/cli.py` | `cer review` entry point |

**Why deterministic first:** review needs reproducibility. The same evidence
produces the same verdict, byte-for-byte, and — with `--clock` — a byte-stable
audit log. The optional LLM layer can only *annotate*; it can never change a
verdict.

---

## Install

```bash
git clone <local-repo>            # local only — no remote is configured
cd control-evidence-review
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash
#                        source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"           # installs pytest; core needs nothing
```

The core tool has **zero** runtime dependencies; `pip install pytest` is enough
to run the tests, or skip install entirely and run modules directly.

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

Each line carries: `schema_version`, `timestamp`, `actor`, `control_id`,
`verdict`, `confidence`, `evidence_ids`, `rationale`.

## Run the tests

```bash
python -m pytest -q
```

---

## Optional LLM mode (off by default)

The default flow uses **no** model and **no** API key. To add a natural-language
reviewer note on top of the deterministic verdicts:

```bash
export CER_LLM=1
export ANTHROPIC_API_KEY=...        # your key; never stored in the repo
pip install ".[llm]"
python -m cer.cli review --catalog controls/catalog.json --evidence evidence
```

If `CER_LLM` is set without a key or the `anthropic` package, the tool fails with
a clear message rather than faking output. The verdict itself is always the
deterministic engine's — the LLM only appends a note.

---

## Fixtures

- `controls/catalog.json` — 11 generic controls, each with named requirements
  and keyword sets. Some controls carry `review_flags` (e.g. `todo`) that force
  `NEEDS_REVIEW`.
- `evidence/` — 14 synthetic snippets. Some fully satisfy a control, some
  satisfy only one requirement (→ `PARTIAL`), and two controls (`PS-4`, `PE-3`)
  have **no** matching evidence (→ `MISSING`). Several snippets contain
  **baked-in synthetic secrets** (fake emails, IPs, `api_key=…`, bearer tokens,
  an AWS-style key) purely to demonstrate the redaction pass.

**Nothing here is real.** Do not point this at production data as-is; the
redaction pass targets the demonstrated synthetic shapes and is not a claim of
exhaustive DLP coverage.

## Tests

`python -m pytest -q` runs 40 tests across the rule engine, matcher, redaction,
audit log, report generation, loaders, and the CLI end-to-end path.

## License

MIT — see `LICENSE`.
