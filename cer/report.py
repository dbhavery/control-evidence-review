"""Build the review report: a JSON object and a self-contained dark HTML page.

The HTML is fully inline (no CDN, no external CSS/JS) so it renders offline.
Every evidence excerpt shown in the report is passed through the redaction pass
first, so synthetic secrets/PII never appear in the rendered output.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .models import ControlVerdict, Evidence, Verdict
from .redaction import redact

_VERDICT_ORDER = [
    Verdict.SATISFIED,
    Verdict.PARTIAL,
    Verdict.NEEDS_REVIEW,
    Verdict.MISSING,
]

_VERDICT_COLOR = {
    Verdict.SATISFIED: "#3fb950",
    Verdict.PARTIAL: "#d29922",
    Verdict.NEEDS_REVIEW: "#58a6ff",
    Verdict.MISSING: "#f85149",
}

_EXCERPT_LEN = 240


def _excerpt(text: str) -> str:
    """First ``_EXCERPT_LEN`` chars of redacted evidence, whitespace-collapsed."""
    redacted = redact(text).text
    collapsed = " ".join(redacted.split())
    if len(collapsed) > _EXCERPT_LEN:
        # Cut on a word boundary so a "[REDACTED:...]" token is never split.
        head = collapsed[:_EXCERPT_LEN]
        cut = head.rfind(" ")
        if cut > 0:
            head = head[:cut]
        collapsed = head.rstrip() + " ..."
    return collapsed


def build_report(
    verdicts: list[ControlVerdict],
    corpus: list[Evidence],
    actor: str,
    generated_at: str,
) -> dict:
    """Assemble the machine-readable report structure."""
    by_id = {ev.id: ev for ev in corpus}
    counts = Counter(v.verdict for v in verdicts)

    controls_out = []
    for v in verdicts:
        excerpts = [
            {
                "evidence_id": eid,
                "source": by_id[eid].source if eid in by_id else eid,
                "excerpt": _excerpt(by_id[eid].text) if eid in by_id else "",
            }
            for eid in v.matched_evidence_ids
        ]
        d = v.to_dict()
        d["evidence"] = excerpts
        controls_out.append(d)

    gaps = [
        {
            "control_id": v.control_id,
            "title": v.title,
            "verdict": v.verdict.value,
            "rationale": v.rationale,
        }
        for v in verdicts
        if v.is_gap
    ]

    return {
        "meta": {
            "actor": actor,
            "generated_at": generated_at,
            "framing": (
                "Policy/control evidence review — decision support for a human "
                "reviewer. NOT a certification of SOC 2, HIPAA, GDPR, or any "
                "framework."
            ),
            "evidence_count": len(corpus),
            "control_count": len(verdicts),
        },
        "summary": {
            "satisfied": counts.get(Verdict.SATISFIED, 0),
            "partial": counts.get(Verdict.PARTIAL, 0),
            "needs_review": counts.get(Verdict.NEEDS_REVIEW, 0),
            "missing": counts.get(Verdict.MISSING, 0),
        },
        "controls": controls_out,
        "gaps": gaps,
    }


def write_json(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _bar(summary: dict) -> str:
    total = max(1, sum(summary.values()))
    segments = [
        ("satisfied", _VERDICT_COLOR[Verdict.SATISFIED]),
        ("partial", _VERDICT_COLOR[Verdict.PARTIAL]),
        ("needs_review", _VERDICT_COLOR[Verdict.NEEDS_REVIEW]),
        ("missing", _VERDICT_COLOR[Verdict.MISSING]),
    ]
    cells = []
    for key, color in segments:
        pct = 100 * summary.get(key, 0) / total
        if pct > 0:
            cells.append(
                f'<div class="seg" style="width:{pct:.2f}%;background:{color}" '
                f'title="{key}: {summary.get(key, 0)}"></div>'
            )
    return "".join(cells)


def render_html(report: dict) -> str:
    """Render the full self-contained HTML report as a string."""
    summary = report["summary"]
    meta = report["meta"]

    stat_cards = "".join(
        f'<div class="stat" style="border-color:{color}">'
        f'<div class="num" style="color:{color}">{summary.get(key, 0)}</div>'
        f'<div class="lbl">{label}</div></div>'
        for key, label, color in [
            ("satisfied", "Satisfied", _VERDICT_COLOR[Verdict.SATISFIED]),
            ("partial", "Partial", _VERDICT_COLOR[Verdict.PARTIAL]),
            ("needs_review", "Needs review", _VERDICT_COLOR[Verdict.NEEDS_REVIEW]),
            ("missing", "Missing", _VERDICT_COLOR[Verdict.MISSING]),
        ]
    )

    control_blocks = []
    verdict_rank = {v.value: i for i, v in enumerate(_VERDICT_ORDER)}
    for c in sorted(
        report["controls"], key=lambda c: verdict_rank.get(c["verdict"], 99)
    ):
        color = _VERDICT_COLOR[Verdict(c["verdict"])]
        reqs = "".join(
            f'<li class="{"met" if r["met"] else "unmet"}">'
            f'{"✓" if r["met"] else "✗"} {html.escape(r["name"])}'
            + (
                f' <span class="kw">[{html.escape(", ".join(r["matched_keywords"]))}]</span>'
                if r["matched_keywords"]
                else ""
            )
            + "</li>"
            for r in c["requirements"]
        )
        if c["evidence"]:
            ev = "".join(
                f'<div class="ev"><span class="evid">{html.escape(e["evidence_id"])}</span>'
                f'<span class="evtext">{html.escape(e["excerpt"])}</span></div>'
                for e in c["evidence"]
            )
        else:
            ev = '<div class="ev none">No matching evidence supplied.</div>'

        flags = ""
        if c["review_flags_hit"]:
            flags = (
                '<div class="flags">Review flags: '
                + html.escape(", ".join(c["review_flags_hit"]))
                + "</div>"
            )

        control_blocks.append(
            f"""
      <div class="control">
        <div class="chead">
          <span class="cid">{html.escape(c["control_id"])}</span>
          <span class="ctitle">{html.escape(c["title"])}</span>
          <span class="badge" style="background:{color}">{c["verdict"]}</span>
          <span class="conf">conf {c["confidence"]:.2f}</span>
        </div>
        <div class="rationale">{html.escape(c["rationale"])}</div>
        {flags}
        <ul class="reqs">{reqs}</ul>
        <div class="evidence">{ev}</div>
      </div>"""
        )

    gap_rows = "".join(
        f'<tr><td class="mono">{html.escape(g["control_id"])}</td>'
        f'<td>{html.escape(g["title"])}</td>'
        f'<td><span class="gv" style="color:{_VERDICT_COLOR[Verdict(g["verdict"])]}">'
        f'{g["verdict"]}</span></td>'
        f'<td>{html.escape(g["rationale"])}</td></tr>'
        for g in report["gaps"]
    ) or '<tr><td colspan="4" class="none">No gaps — every control satisfied.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Control Evidence Review</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0d1117; color:#c9d1d9;
    font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .disclaimer {{ background:#161b22; border:1px solid #30363d; border-left:3px solid #58a6ff;
    padding:12px 16px; border-radius:6px; color:#8b949e; font-size:13px; margin:16px 0 24px; }}
  .meta {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .meta code {{ color:#c9d1d9; }}
  .stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px; }}
  .stat {{ flex:1; min-width:120px; background:#161b22; border:1px solid #30363d;
    border-top-width:3px; border-radius:6px; padding:14px 16px; }}
  .stat .num {{ font-size:30px; font-weight:700; }}
  .stat .lbl {{ color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .barwrap {{ display:flex; height:10px; border-radius:5px; overflow:hidden; margin:8px 0 32px;
    border:1px solid #30363d; }}
  .seg {{ height:100%; }}
  h2 {{ font-size:16px; margin:28px 0 12px; color:#e6edf3; border-bottom:1px solid #21262d; padding-bottom:6px; }}
  .control {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
    padding:16px 18px; margin-bottom:14px; }}
  .chead {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .cid {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#58a6ff; font-weight:700; }}
  .ctitle {{ font-weight:600; flex:1; }}
  .badge {{ color:#0d1117; font-weight:700; font-size:11px; padding:3px 8px; border-radius:12px; letter-spacing:.03em; }}
  .conf {{ color:#8b949e; font-size:12px; font-family:ui-monospace,monospace; }}
  .rationale {{ color:#8b949e; font-size:13px; margin:8px 0; }}
  .flags {{ color:#d29922; font-size:12px; margin:6px 0; }}
  ul.reqs {{ list-style:none; margin:10px 0; padding:0; font-size:13px; }}
  ul.reqs li {{ padding:2px 0; }}
  ul.reqs li.met {{ color:#3fb950; }}
  ul.reqs li.unmet {{ color:#f85149; }}
  .kw {{ color:#8b949e; font-family:ui-monospace,monospace; font-size:11px; }}
  .evidence {{ margin-top:8px; }}
  .ev {{ background:#0d1117; border:1px solid #21262d; border-radius:6px;
    padding:8px 10px; margin:6px 0; font-size:12px; }}
  .ev.none {{ color:#8b949e; font-style:italic; }}
  .evid {{ display:inline-block; font-family:ui-monospace,monospace; color:#58a6ff;
    margin-right:8px; }}
  .evtext {{ color:#adbac7; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; background:#161b22;
    border:1px solid #30363d; border-radius:8px; overflow:hidden; }}
  th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid #21262d; vertical-align:top; }}
  th {{ color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
  td.mono {{ font-family:ui-monospace,monospace; color:#58a6ff; }}
  .gv {{ font-weight:700; }}
  .none {{ color:#8b949e; font-style:italic; text-align:center; }}
  footer {{ color:#484f58; font-size:12px; margin-top:36px; text-align:center; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Control Evidence Review</h1>
    <div class="disclaimer">{html.escape(meta["framing"])}</div>
    <div class="meta">
      Reviewer: <code>{html.escape(meta["actor"])}</code> &middot;
      Generated: <code>{html.escape(meta["generated_at"])}</code> &middot;
      Controls: <code>{meta["control_count"]}</code> &middot;
      Evidence snippets: <code>{meta["evidence_count"]}</code>
    </div>
    <div class="stats">{stat_cards}</div>
    <div class="barwrap">{_bar(summary)}</div>

    <h2>Controls</h2>
    {"".join(control_blocks)}

    <h2>Gaps &mdash; reviewer worklist</h2>
    <table>
      <tr><th>Control</th><th>Title</th><th>Verdict</th><th>Rationale</th></tr>
      {gap_rows}
    </table>

    <footer>Generated by control-evidence-review &middot; evidence excerpts redacted &middot; decision support only</footer>
  </div>
</body>
</html>
"""


def write_html(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path
