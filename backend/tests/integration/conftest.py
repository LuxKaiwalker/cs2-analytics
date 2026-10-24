"""Fixtures for tests that need a genuine CS2 demo.

Demos are never downloaded implicitly. A plain ``pytest`` run skips these tests with a
message saying how to fetch one, because the files are hundreds of megabytes and contain
real player names and Steam IDs.

The suite is **parameterized over whatever fixtures are present on disk**, so dropping in
another demo extends coverage without touching a test. Each demo is parsed once per
session and cached: parsing a 438 MB file per test would dominate the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app import fixtures
from app.analytics.compute import MatchAnalytics, compute
from app.config import get_settings
from app.parsing.model import NormalizedMatch

FETCH_HINT = "run 'python -m app.cli fetch-fixture --list' to see the available demos"


@dataclass(frozen=True, slots=True)
class DemoCase:
    """A downloaded demo plus everything derived from it."""

    entry: fixtures.Fixture
    path: Path
    normalized: NormalizedMatch
    analytics: MatchAnalytics

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def ground_truth_players(self) -> list[dict[str, Any]]:
        return list((self.entry.ground_truth or {}).get("players", []))

    def expected_scores(self) -> list[int] | None:
        """The published final score, highest first, or ``None`` if not recorded."""
        if not self.entry.result:
            return None
        try:
            return sorted((int(part) for part in self.entry.result.split("-")), reverse=True)
        except ValueError:
            return None


def _manifest() -> list[fixtures.Fixture]:
    settings = get_settings()
    cached = settings.fixtures_dir / "manifest.json"
    try:
        return fixtures.load_manifest(cached if cached.exists() else None)
    except OSError:
        return []


def _present() -> list[fixtures.Fixture]:
    """Manifest entries whose demo is actually downloaded, smallest first."""
    settings = get_settings()
    return sorted(
        (entry for entry in _manifest() if (settings.fixtures_dir / entry.asset).is_file()),
        key=lambda entry: entry.size,
    )


#: Resolved at collection time so each demo becomes its own visible test case.
PRESENT_FIXTURES = _present()

_CACHE: dict[str, DemoCase] = {}


def _load(entry: fixtures.Fixture) -> DemoCase:
    """Parse and analyse a demo once, then reuse it for every test in the session."""
    if entry.name not in _CACHE:
        from app.parsing.awpy_parser import get_parser

        path = get_settings().fixtures_dir / entry.asset
        normalized = get_parser().parse(str(path))
        _CACHE[entry.name] = DemoCase(
            entry=entry,
            path=path,
            normalized=normalized,
            analytics=compute(normalized),
        )
    return _CACHE[entry.name]


@pytest.fixture(
    params=PRESENT_FIXTURES or [None],
    ids=[entry.name for entry in PRESENT_FIXTURES] or ["no-fixture-downloaded"],
    scope="session",
)
def case(request: pytest.FixtureRequest) -> DemoCase:
    """Every downloaded demo, as a separate test case."""
    entry = request.param
    if entry is None:
        pytest.skip(f"no demo fixture is downloaded; {FETCH_HINT}")
    return _load(entry)


@pytest.fixture(scope="session")
def scored_case(case: DemoCase) -> DemoCase:
    """A demo whose manifest records a published scoreboard to check against."""
    if not case.ground_truth_players:
        pytest.skip(f"{case.name} has no published ground-truth scoreboard")
    return case
