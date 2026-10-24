"""Fixtures for tests that need a genuine CS2 demo.

The demo is never downloaded implicitly. A plain ``pytest`` run skips these tests with a
message telling you how to fetch it, because the file is 84 MB and contains real player
names and Steam IDs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import fixtures
from app.config import Settings, get_settings

#: The fixture these tests assert against, chosen because its manifest entry carries a
#: published csstats.gg scoreboard we can check our own numbers against.
FIXTURE_NAME = "valve-de_mirage-472514809"

_HINT = (
    f"the real demo fixture is missing; run "
    f"'python -m app.cli fetch-fixture --name {FIXTURE_NAME}' to download it"
)


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    """The project's own settings, so the already-downloaded fixture is found."""
    return get_settings()


@pytest.fixture(scope="session")
def fixture_entry(real_settings: Settings) -> fixtures.Fixture:
    manifest = real_settings.fixtures_dir / "manifest.json"
    try:
        entries = fixtures.load_manifest(manifest if manifest.exists() else None)
    except OSError:
        pytest.skip("the fixture manifest is unavailable (offline?)")
    entry = next((e for e in entries if e.name == FIXTURE_NAME), None)
    if entry is None:
        pytest.skip(f"{FIXTURE_NAME} is not in the fixture manifest")
    return entry


@pytest.fixture(scope="session")
def demo_path(real_settings: Settings, fixture_entry: fixtures.Fixture) -> Path:
    path = real_settings.fixtures_dir / fixture_entry.asset
    if not path.is_file():
        pytest.skip(_HINT)
    return path


@pytest.fixture(scope="session")
def ground_truth(fixture_entry: fixtures.Fixture) -> dict:
    """The published per-player scoreboard from csstats.gg."""
    truth = fixture_entry.ground_truth
    if not truth or not truth.get("players"):
        pytest.skip("this fixture has no published ground-truth scoreboard")
    return truth


@pytest.fixture(scope="session")
def normalized(demo_path: Path) -> object:
    from app.parsing.awpy_parser import get_parser

    return get_parser().parse(str(demo_path))


@pytest.fixture(scope="session")
def analytics(normalized: object) -> object:
    from app.analytics.compute import compute

    return compute(normalized)  # type: ignore[arg-type]
