"""Shared fixtures: point tests at the repo's controls/ and evidence/ dirs."""

from __future__ import annotations

from pathlib import Path

import pytest

from cer.catalog import load_catalog
from cer.evidence import load_evidence

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def catalog_path() -> Path:
    return REPO_ROOT / "controls" / "catalog.json"


@pytest.fixture
def evidence_dir() -> Path:
    return REPO_ROOT / "evidence"


@pytest.fixture
def controls(catalog_path):
    return load_catalog(catalog_path)


@pytest.fixture
def corpus(evidence_dir):
    return load_evidence(evidence_dir)
