"""Development tooling: fetch the public CS2 demo fixtures used by integration tests.

Awpy publishes real demos as GitHub release assets in ``pnxenopoulos/awpy-fixtures``,
indexed by a ``manifest.json`` that also carries a **ground-truth scoreboard** scraped
from csstats.gg. That lets the integration test check our analytics against a third
party rather than only against awpy itself.

Downloads are explicit (``python -m app.cli fetch-fixture``) and never implicit: a
plain ``pytest`` run skips the demo-backed tests when the file is absent. Fixtures
land in ``data/fixtures/`` and are gitignored — demos contain real player names and
Steam IDs.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_URL = "https://raw.githubusercontent.com/pnxenopoulos/awpy-fixtures/main/manifest.json"
_USER_AGENT = "cs2-analytics-fixtures"
_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class Fixture:
    """One entry from the awpy-fixtures manifest."""

    name: str
    asset: str
    url: str
    sha256: str
    size: int
    map_name: str
    source: str
    result: str | None
    notes: str | None
    match_url: str | None
    ground_truth: dict[str, Any] | None

    @classmethod
    def from_manifest(cls, entry: dict[str, Any]) -> Fixture:
        return cls(
            name=entry["name"],
            asset=entry["asset"],
            url=entry["url"],
            sha256=entry["sha256"],
            size=int(entry.get("size", 0)),
            map_name=entry.get("map", ""),
            source=entry.get("source", ""),
            result=entry.get("result"),
            notes=entry.get("notes"),
            match_url=entry.get("match_url"),
            ground_truth=entry.get("ground_truth"),
        )


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data: bytes = response.read()
    return data


def load_manifest(cache_path: Path | None = None) -> list[Fixture]:
    """Fetch (and optionally cache) the fixture manifest."""
    if cache_path is not None and cache_path.exists():
        payload = json.loads(cache_path.read_text())
    else:
        payload = json.loads(_get(MANIFEST_URL))
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, indent=2))
    return [Fixture.from_manifest(e) for e in payload.get("fixtures", [])]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def smallest(fixtures: list[Fixture]) -> Fixture:
    """The cheapest fixture to download — what the default integration test uses."""
    return min(fixtures, key=lambda f: f.size or float("inf"))


def ensure(fixture: Fixture, dest_dir: Path, *, progress: Any = None) -> Path:
    """Download ``fixture`` into ``dest_dir`` unless a checksum-verified copy exists.

    Raises:
        ValueError: if the downloaded bytes do not match the manifest checksum.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fixture.asset
    if dest.exists() and sha256_file(dest) == fixture.sha256:
        return dest
    dest.unlink(missing_ok=True)

    partial = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    written = 0
    request = urllib.request.Request(fixture.url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,  # noqa: S310
            partial.open("wb") as handle,
        ):
            while chunk := response.read(_CHUNK):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(written, fixture.size)
        actual = digest.hexdigest()
        if actual != fixture.sha256:
            msg = f"checksum mismatch for {fixture.asset}: expected {fixture.sha256}, got {actual}"
            raise ValueError(msg)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def find_local(dest_dir: Path) -> Path | None:
    """Any already-downloaded fixture, preferring the smallest. ``None`` if none."""
    candidates = sorted(dest_dir.glob("*.dem"), key=lambda p: p.stat().st_size)
    return candidates[0] if candidates else None
