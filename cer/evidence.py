"""Load synthetic evidence snippets from a directory.

Each ``.txt`` / ``.md`` file in the evidence directory becomes one ``Evidence``
snippet. The file stem is used as the evidence id, so filenames should be
stable and descriptive (e.g. ``account-review-log.txt`` -> id
``account-review-log``). Files are read in sorted order for determinism.
"""

from __future__ import annotations

from pathlib import Path

from .models import Evidence

_SUFFIXES = {".txt", ".md", ".log", ".conf", ".cfg"}


def load_evidence(directory: str | Path) -> list[Evidence]:
    """Read every supported file in ``directory`` into an ``Evidence`` list."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Evidence directory not found: {directory}")

    corpus: list[Evidence] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in _SUFFIXES:
            corpus.append(
                Evidence(
                    id=path.stem,
                    source=path.name,
                    text=path.read_text(encoding="utf-8"),
                )
            )
    if not corpus:
        raise ValueError(f"No evidence files found in: {directory}")
    return corpus
