"""Optional LLM-assisted enrichment — OFF by default, env-gated, no keys in code.

The deterministic rule engine is always the source of truth for the verdict.
When explicitly enabled, this module can add a natural-language reviewer note to
each verdict's rationale. It is gated entirely behind environment variables and
never runs in the default sample flow, so the tool is fully usable with no API
key and no network access.

Enable with::

    CER_LLM=1  and  ANTHROPIC_API_KEY=<key>   (requires the `anthropic` package)

If enabled but not configured, :func:`enrich` raises a clear error rather than
silently faking output.
"""

from __future__ import annotations

import os

from .models import ControlVerdict


def llm_enabled() -> bool:
    return os.environ.get("CER_LLM", "").strip() in {"1", "true", "yes"}


def enrich(verdicts: list[ControlVerdict]) -> list[ControlVerdict]:
    """Append an LLM reviewer note to each verdict's rationale.

    Raises if enabled without the required key/package. This function makes a
    real API call only when fully configured; there is no stub/fake output.
    """
    if not llm_enabled():
        return verdicts

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "CER_LLM is set but ANTHROPIC_API_KEY is missing. "
            "Unset CER_LLM to run in deterministic mode."
        )
    try:
        import anthropic  # noqa: F401  (imported for its side effect: availability check)
    except ImportError as exc:  # pragma: no cover - exercised only with opt-in deps
        raise RuntimeError(
            "CER_LLM is set but the 'anthropic' package is not installed. "
            "Run `pip install anthropic` or unset CER_LLM."
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)  # pragma: no cover
    model = os.environ.get("CER_LLM_MODEL", "claude-opus-4-8")  # pragma: no cover
    for v in verdicts:  # pragma: no cover - network path, not run in tests/CI
        prompt = (
            "You are assisting a human control reviewer. Given this deterministic "
            f"verdict, write ONE short reviewer note (<=30 words). Do not change the "
            f"verdict. Control {v.control_id} '{v.title}': verdict={v.verdict.value}, "
            f"rationale={v.rationale}"
        )
        resp = client.messages.create(
            model=model,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        note = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
        if note:
            v.rationale = f"{v.rationale}  [LLM note: {note}]"
    return verdicts
