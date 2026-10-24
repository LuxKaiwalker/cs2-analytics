"""Shared fixtures.

API tests run against a real app with a real SQLite database in a temp directory, but
with the parser replaced. That keeps them fast and hermetic while still exercising the
routes, the error envelope, the worker handoff and the database — the integration test
is where the genuine parser is used.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import db as db_module
from app.config import Settings, get_settings
from app.models import Match, MatchStatus
from app.pipeline import supervisor as supervisor_module

CS2_HEADER = b"PBDEMS2\x00"
SOURCE1_HEADER = b"HL2DEMO\x00"


def make_demo_bytes(size: int = 128 * 1024, header: bytes = CS2_HEADER) -> bytes:
    """A byte string that passes content validation without being a real demo."""
    body = bytearray(header)
    body.extend(b"\x00" * max(0, size - len(header)))
    return bytes(body)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Point the whole app at a temp data directory.

    Done through the environment plus a cache clear rather than by patching modules:
    settings are read through one cached accessor, so this is the only override that
    every call site — routes, storage, the worker — is guaranteed to agree on.
    """
    monkeypatch.setenv("CS2A_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CS2A_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("CS2A_MIN_DEMO_BYTES", "1024")
    monkeypatch.setenv("CS2A_MAX_DEMO_BYTES", str(4 * 1024 * 1024))
    monkeypatch.setenv("CS2A_MAX_TOTAL_BYTES", str(64 * 1024 * 1024))
    monkeypatch.setenv("CS2A_SERVE_FRONTEND", "false")
    # Settings also read a .env file at the repo root; ignore it so a developer's local
    # configuration cannot change test outcomes.
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    get_settings.cache_clear()
    db_module.reset_engine()
    supervisor_module.reset_supervisor()
    configured = get_settings()
    configured.ensure_dirs()
    try:
        yield configured
    finally:
        db_module.reset_engine()
        supervisor_module.reset_supervisor()
        get_settings.cache_clear()


@pytest.fixture
def engine(settings: Settings) -> Engine:
    from app.persist.schema_check import init_schema

    eng = db_module.get_engine()
    init_schema(eng)
    return eng


class FakeSupervisor:
    """Records submissions instead of spawning processes.

    Route tests care that a match is queued and handed over, not that a subprocess ran.
    The real supervisor is exercised by the integration tests.
    """

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: list[str] = []
        self.depth = 0
        self.alive = True
        self.current_match_id: str | None = None
        self.full = False

    def submit(self, match_id: str) -> None:
        if self.full:
            raise supervisor_module.QueueFullError
        self.submitted.append(match_id)

    def cancel(self, match_id: str) -> bool:
        self.cancelled.append(match_id)
        return True

    def start(self) -> None:
        self.alive = True

    def stop(self, timeout: float = 5.0) -> None:
        self.alive = False

    def recover_interrupted(self) -> int:
        return 0


@pytest.fixture
def fake_supervisor() -> FakeSupervisor:
    return FakeSupervisor()


@pytest.fixture
def client(
    settings: Settings, engine: Engine, fake_supervisor: FakeSupervisor
) -> Iterator[TestClient]:
    """A test client whose worker is faked but whose database and routes are real."""
    from app.main import create_app
    from app.pipeline.supervisor import get_supervisor

    app = create_app(settings)
    app.dependency_overrides[get_supervisor] = lambda: fake_supervisor
    with TestClient(app) as test_client:
        yield test_client


def upload(
    client: TestClient, payload: bytes | None = None, *, filename: str = "match.dem"
) -> object:
    """POST a demo body the way the frontend does."""
    body = payload if payload is not None else make_demo_bytes()
    return client.post(
        f"/api/matches?filename={filename}",
        content=body,
        headers={"Content-Type": "application/octet-stream"},
    )


def seed_completed_match(engine: Engine, *, match_id: str | None = None) -> str:
    """Insert a fully analysed match, as the worker would leave it."""
    from tests.seed import write_sample_match

    return write_sample_match(engine, match_id or uuid.uuid4().hex)


def set_status(engine: Engine, match_id: str, status: MatchStatus) -> None:
    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        record.status = status
        session.commit()
