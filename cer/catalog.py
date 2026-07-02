"""Load the control catalog from JSON.

The catalog is a generic set of control statements with identifiers. The
identifiers (AC-2, AU-6, ...) are labels for readability only and are NOT a
claim of conformance to any published control framework.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Control, Requirement


def load_catalog(path: str | Path) -> list[Control]:
    """Parse a catalog JSON file into ``Control`` objects.

    Expected shape::

        {"controls": [
            {"id": "AC-2", "title": "...", "description": "...",
             "review_flags": ["exception"],
             "requirements": [
                {"name": "...", "keywords": ["...", "..."], "min_hits": 1}
             ]}
        ]}
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    controls: list[Control] = []
    seen_ids: set[str] = set()

    for raw in data.get("controls", []):
        cid = raw["id"]
        if cid in seen_ids:
            raise ValueError(f"Duplicate control id in catalog: {cid}")
        seen_ids.add(cid)

        requirements = tuple(
            Requirement(
                name=r["name"],
                keywords=tuple(r["keywords"]),
                min_hits=int(r.get("min_hits", 1)),
            )
            for r in raw.get("requirements", [])
        )
        controls.append(
            Control(
                id=cid,
                title=raw["title"],
                description=raw.get("description", ""),
                requirements=requirements,
                review_flags=tuple(raw.get("review_flags", [])),
            )
        )

    if not controls:
        raise ValueError(f"No controls found in catalog: {path}")
    return controls
