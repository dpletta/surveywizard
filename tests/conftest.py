"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REDCAP_FIXTURES = FIXTURES / "redcap"
QUALTRICS_FIXTURES = FIXTURES / "qualtrics"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def redcap_fixtures() -> Path:
    return REDCAP_FIXTURES


@pytest.fixture(scope="session")
def qualtrics_fixtures() -> Path:
    return QUALTRICS_FIXTURES


@pytest.fixture(scope="session")
def redcap_example_xml() -> Path:
    path = REDCAP_FIXTURES / "example_project.xml"
    if not path.exists():
        pytest.skip(f"REDCap fixture not present: {path}")
    return path


@pytest.fixture(scope="session")
def qsf_samples(qualtrics_fixtures: Path) -> list[Path]:
    samples = sorted(qualtrics_fixtures.glob("*.qsf"))
    if not samples:
        pytest.skip("No QSF fixtures present")
    return samples
