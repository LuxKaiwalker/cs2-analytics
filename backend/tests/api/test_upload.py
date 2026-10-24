"""Upload validation, size limits and de-duplication."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Match, MatchStatus
from tests.conftest import SOURCE1_HEADER, FakeSupervisor, make_demo_bytes, upload


def test_valid_upload_is_accepted_and_queued(
    client: TestClient, engine: Engine, fake_supervisor: FakeSupervisor
) -> None:
    response = upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == MatchStatus.QUEUED
    assert fake_supervisor.submitted == [body["id"]], "the match must reach the worker"

    with Session(engine) as session:
        record = session.get(Match, body["id"])
        assert record is not None
        assert record.status == MatchStatus.QUEUED
        assert record.sha256 and len(record.sha256) == 64


def test_stored_filename_is_generated_not_taken_from_the_client(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    """A traversal attempt in the filename must not influence the stored path."""
    response = client.post(
        "/api/matches?filename=../../../../etc/passwd",
        content=make_demo_bytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201
    match_id = response.json()["id"]
    with Session(engine) as session:
        record = session.get(Match, match_id)
        assert record is not None
        assert record.stored_path == str(settings.demos_dir / f"{match_id}.dem")
        assert ".." not in (record.original_filename or "")
        assert "/" not in (record.original_filename or "")


def test_oversized_declared_body_is_refused_before_it_is_read(
    client: TestClient, settings: Settings
) -> None:
    """A declared Content-Length over the cap is rejected with 413."""
    payload = make_demo_bytes(settings.max_demo_bytes + 1024)
    response = upload(client, payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_oversized_chunked_body_is_refused_mid_stream(
    client: TestClient, settings: Settings
) -> None:
    """With no Content-Length the cap must still hold, enforced while streaming.

    This is the case a handler-side check cannot catch, and the reason uploads are read
    as a raw stream rather than parsed as a form.
    """
    limit = settings.max_demo_bytes

    def chunks() -> object:
        yield b"PBDEMS2\x00"
        for _ in range((limit // 8192) + 4):
            yield b"\x00" * 8192

    response = client.post(
        "/api/matches",
        content=chunks(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_partial_upload_leaves_no_file_behind(client: TestClient, settings: Settings) -> None:
    payload = make_demo_bytes(settings.max_demo_bytes + 1024)
    upload(client, payload)
    assert list(settings.tmp_dir.iterdir()) == []
    assert list(settings.demos_dir.iterdir()) == []


def test_too_small_body_is_rejected(client: TestClient) -> None:
    response = upload(client, b"PBDEMS2\x00short")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_demo"


def test_wrong_content_type_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/matches", content=make_demo_bytes(), headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_a_file_that_is_not_a_demo_is_rejected_by_content(client: TestClient) -> None:
    """The extension is irrelevant; the leading bytes decide."""
    response = upload(client, b"NOTADEMO" + b"\x00" * 200_000, filename="legit.dem")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_demo"
    assert "PBDEMS2" in response.json()["error"]["message"]


def test_a_csgo_demo_is_rejected_with_a_specific_message(client: TestClient) -> None:
    """Being told "not a CS2 demo" is far more useful than a generic rejection."""
    response = upload(client, make_demo_bytes(header=SOURCE1_HEADER))
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "source1_demo"
    assert "CS:GO" in body["message"]


def test_a_compressed_demo_is_rejected_with_guidance(client: TestClient) -> None:
    response = upload(client, b"BZh91AY&SY" + b"\x00" * 200_000)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "compressed_demo"
    assert "bzip2" in body["message"]


def test_uploading_the_same_demo_twice_returns_the_original(
    client: TestClient, settings: Settings
) -> None:
    """Content-addressed de-duplication makes a retried upload idempotent."""
    payload = make_demo_bytes()
    first = upload(client, payload)
    assert first.status_code == 201
    second = upload(client, payload)
    assert second.status_code == 409
    body = second.json()["error"]
    assert body["code"] == "duplicate_demo"
    assert body["details"]["match_id"] == first.json()["id"]
    # The rejected copy must not be left on disk.
    assert len(list(settings.demos_dir.glob("*.dem"))) == 1


def test_a_full_queue_is_reported_rather_than_silently_dropped(
    client: TestClient, engine: Engine, fake_supervisor: FakeSupervisor
) -> None:
    fake_supervisor.full = True
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "queue_full"
    with Session(engine) as session:
        record = session.scalar(select(Match))
        assert record is not None
        assert record.status == MatchStatus.FAILED
        assert record.error_code == "queue_full"


def test_exhausted_storage_budget_is_reported(
    client: TestClient, settings: Settings, monkeypatch: object
) -> None:
    import pytest

    from app.ingest import storage

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(storage, "stored_bytes", lambda _s: settings.max_total_bytes)
    response = upload(client)
    assert response.status_code == 507
    assert response.json()["error"]["code"] == "insufficient_storage"
