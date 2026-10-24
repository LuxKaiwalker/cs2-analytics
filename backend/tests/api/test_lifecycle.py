"""Processing status, failure handling and restart recovery.

These use the real supervisor with a stubbed job function, so the queueing, claiming,
failure-marking and recovery logic is genuinely exercised without parsing a demo.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Match, MatchStatus
from app.pipeline.supervisor import WorkerSupervisor
from tests.conftest import seed_completed_match, set_status


def _wait_for(engine: Engine, match_id: str, predicate, timeout: float = 20.0) -> Match:
    """Poll until ``predicate`` holds for the match, as the UI's poller would."""
    deadline = time.monotonic() + timeout
    last: Match | None = None
    while time.monotonic() < deadline:
        with Session(engine) as session:
            record = session.get(Match, match_id)
            if record is not None:
                session.expunge(record)
                last = record
                if predicate(record):
                    return record
        time.sleep(0.05)
    status = getattr(last, "status", None)
    code = getattr(last, "error_code", None)
    raise AssertionError(f"timed out; last status={status} code={code}")


def _queue_match(engine: Engine, match_id: str, stored_path: str | None) -> None:
    with Session(engine) as session:
        session.add(
            Match(
                id=match_id,
                sha256=f"{match_id:<64.64}".replace(" ", "a"),
                original_filename="x.dem",
                stored_path=stored_path,
                size_bytes=2048,
                source="upload",
                status=MatchStatus.QUEUED,
            )
        )
        session.commit()


def test_a_missing_demo_file_fails_with_a_specific_code(settings: Settings, engine: Engine) -> None:
    """The lifecycle must end in a terminal state with a machine-readable reason."""
    _queue_match(engine, "missingfile" + "0" * 20, None)
    supervisor = WorkerSupervisor(settings)
    supervisor.start()
    try:
        supervisor.submit("missingfile" + "0" * 20)
        record = _wait_for(
            engine,
            "missingfile" + "0" * 20,
            lambda r: MatchStatus(r.status).is_terminal,
        )
    finally:
        supervisor.stop()
    assert record.status == MatchStatus.FAILED
    assert record.error_code == "demo_missing"
    assert record.error_message


def test_an_unparseable_demo_fails_without_taking_the_server_down(
    settings: Settings, engine: Engine
) -> None:
    """A file that passes the magic check but is not a real demo must fail cleanly.

    This is the case the subprocess isolation exists for: a malformed binary that upsets
    the native parser kills only the worker.
    """
    match_id = "badpayload" + "0" * 22
    path = settings.demos_dir / f"{match_id}.dem"
    path.write_bytes(b"PBDEMS2\x00" + b"\xff" * 200_000)
    _queue_match(engine, match_id, str(path))

    supervisor = WorkerSupervisor(settings)
    supervisor.start()
    try:
        supervisor.submit(match_id)
        record = _wait_for(
            engine, match_id, lambda r: MatchStatus(r.status).is_terminal, timeout=60
        )
    finally:
        supervisor.stop()

    assert record.status == MatchStatus.FAILED
    assert record.error_code in {
        "invalid_demo",
        "unsupported_demo",
        "parse_failed",
        "empty_demo",
        "worker_crashed",
        "internal_error",
    }, record.error_code
    assert record.error_message
    assert "Traceback" not in (record.error_message or ""), "no internals in the message"
    assert str(settings.data_dir) not in (record.error_message or ""), "no paths leaked"


def test_a_cancelled_match_is_skipped_rather_than_parsed(
    settings: Settings, engine: Engine
) -> None:
    match_id = "cancelled" + "0" * 23
    _queue_match(engine, match_id, None)
    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        record.cancel_requested = True
        session.commit()

    supervisor = WorkerSupervisor(settings)
    supervisor.start()
    try:
        supervisor.submit(match_id)
        final = _wait_for(engine, match_id, lambda r: MatchStatus(r.status).is_terminal)
    finally:
        supervisor.stop()
    assert final.status == MatchStatus.CANCELLED


def test_interrupted_matches_are_requeued_on_restart(settings: Settings, engine: Engine) -> None:
    """A restart must not leave a match stuck claiming to be processing forever."""
    match_id = "interrupted" + "0" * 21
    _queue_match(engine, match_id, None)
    set_status(engine, match_id, MatchStatus.PROCESSING)

    supervisor = WorkerSupervisor(settings)
    assert supervisor.recover_interrupted() == 1
    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        assert record.status == MatchStatus.QUEUED
        assert record.attempts == 1


def test_a_repeatedly_interrupted_match_is_abandoned_not_retried_forever(
    settings: Settings, engine: Engine
) -> None:
    """Without the attempt counter, a crash loop would re-parse the same demo endlessly."""
    match_id = "looping" + "0" * 25
    _queue_match(engine, match_id, None)
    supervisor = WorkerSupervisor(settings)

    for _ in range(settings.max_attempts):
        supervisor.recover_interrupted()
        set_status(engine, match_id, MatchStatus.PROCESSING)
    supervisor.recover_interrupted()

    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        assert record.status == MatchStatus.FAILED
        assert record.error_code == "abandoned_after_restart"


def test_a_deleted_match_is_skipped_by_the_worker(settings: Settings, engine: Engine) -> None:
    supervisor = WorkerSupervisor(settings)
    supervisor.start()
    try:
        supervisor.submit("neverexisted" + "0" * 20)
        time.sleep(1.0)
    finally:
        supervisor.stop()
    # Nothing to assert beyond "did not raise": the supervisor must survive a vanished row.
    assert not supervisor.alive


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        (MatchStatus.UPLOADED, False),
        (MatchStatus.QUEUED, False),
        (MatchStatus.PROCESSING, False),
        (MatchStatus.COMPLETED, True),
        (MatchStatus.FAILED, True),
        (MatchStatus.CANCELLED, True),
    ],
)
def test_terminal_states_are_classified_correctly(status: MatchStatus, terminal: bool) -> None:
    """The UI stops polling on a terminal state, so this must not drift."""
    assert status.is_terminal is terminal


def test_a_completed_match_is_distinguishable_from_a_failed_one(
    engine: Engine, client: object
) -> None:
    """Empty data and a parse failure must never look the same to the UI."""
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    good = seed_completed_match(engine)
    bad = seed_completed_match(engine)
    with Session(engine) as session:
        record = session.get(Match, bad)
        assert record is not None
        record.status = MatchStatus.FAILED
        record.error_code = "invalid_demo"
        record.error_message = "The file is not a valid CS2 demo."
        session.commit()

    good_body = client.get(f"/api/matches/{good}").json()
    bad_body = client.get(f"/api/matches/{bad}").json()
    assert good_body["status"] == MatchStatus.COMPLETED
    assert good_body["error_code"] is None
    assert bad_body["status"] == MatchStatus.FAILED
    assert bad_body["error_code"] == "invalid_demo"
    assert bad_body["error_message"]
