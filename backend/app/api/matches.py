"""Match lifecycle: upload, import, list, inspect, delete."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import errors
from app.config import Settings, get_settings
from app.db import get_db
from app.ingest import fetch, storage
from app.models import Match, MatchPlayer, MatchRound, MatchRoundPlayer, MatchStatus
from app.pipeline.supervisor import QueueFullError, WorkerSupervisor, get_supervisor
from app.schemas import (
    ImportRequest,
    MatchCreatedOut,
    MatchDetailOut,
    MatchListOut,
    MatchSummaryOut,
    PlayerStatsOut,
    RoundOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/matches", tags=["matches"])

_OCTET_STREAM = "application/octet-stream"


def _new_id() -> str:
    return uuid.uuid4().hex


def _translate_storage_error(exc: Exception) -> errors.ApiError:
    """Map an ingestion failure onto the right status code and machine code."""
    if isinstance(exc, storage.UploadTooLargeError):
        return errors.payload_too_large(exc.limit, exc.received)
    if isinstance(exc, storage.UploadTooSmallError):
        return errors.invalid_request(
            "invalid_demo",
            f"The file is only {exc.received} bytes, which is too small to be a CS2 demo.",
        )
    if isinstance(exc, storage.UploadRejectedError):
        return errors.invalid_request(exc.code, exc.user_message)
    if isinstance(exc, storage.StorageFullError):
        return errors.insufficient_storage(str(exc))
    if isinstance(exc, fetch.ImportRejectedError):
        return errors.invalid_request(exc.code, exc.user_message)
    if isinstance(exc, fetch.ImportFailedError):
        return errors.invalid_request("download_failed", exc.user_message)
    logger.exception("unexpected ingestion failure")
    return errors.ApiError(
        "internal_error",
        "The demo could not be stored.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _existing_by_hash(session: Session, sha256: str) -> Match | None:
    return session.scalar(select(Match).where(Match.sha256 == sha256))


def _enqueue(
    session: Session,
    supervisor: WorkerSupervisor,
    record: Match,
) -> None:
    """Persist the record as queued and hand it to the supervisor."""
    record.status = MatchStatus.QUEUED
    session.add(record)
    session.commit()
    try:
        supervisor.submit(record.id)
    except QueueFullError as exc:
        record.status = MatchStatus.FAILED
        record.error_code = "queue_full"
        record.error_message = "The processing queue was full when this demo was accepted."
        session.commit()
        raise errors.queue_full(supervisor.depth) from exc


@router.post(
    "",
    response_model=MatchCreatedOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "This demo has already been uploaded"},
        413: {"description": "The demo exceeds the configured size limit"},
        415: {"description": "Send the demo as application/octet-stream"},
        422: {"description": "The file is not a valid CS2 demo"},
        507: {"description": "Out of storage"},
    },
)
async def upload_match(
    request: Request,
    filename: str | None = Query(default=None, max_length=255),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    supervisor: WorkerSupervisor = Depends(get_supervisor),
) -> MatchCreatedOut:
    """Accept a demo as a raw request body and queue it for processing.

    The body is deliberately **not** multipart. A multipart handler only runs after the
    framework has already spooled the entire body to disk, so a size check there reports
    the problem without preventing it. Reading the raw stream lets the cap be enforced
    mid-transfer and the partial file deleted at once.
    """
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type != _OCTET_STREAM:
        raise errors.unsupported_media_type(content_type)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_demo_bytes:
        # The middleware normally catches this first; kept as a direct guard too.
        raise errors.payload_too_large(settings.max_demo_bytes, int(declared))

    try:
        storage.check_capacity(settings, int(declared) if declared and declared.isdigit() else None)
    except storage.StorageFullError as exc:
        raise errors.insufficient_storage(str(exc)) from exc

    match_id = _new_id()
    display = filename or request.headers.get("x-filename")
    try:
        stored = await storage.store_stream(
            settings, match_id, request.stream(), display_name=display
        )
    except Exception as exc:
        raise _translate_storage_error(exc) from exc

    duplicate = _existing_by_hash(session, stored.sha256)
    if duplicate is not None:
        # Content-addressed de-duplication makes uploads idempotent: a retried or
        # re-dragged file returns the original match instead of parsing it twice.
        storage.delete_demo(stored.path)
        raise errors.duplicate_match(duplicate.id)

    record = Match(
        id=match_id,
        sha256=stored.sha256,
        original_filename=stored.display_name,
        stored_path=str(stored.path),
        size_bytes=stored.size_bytes,
        source="upload",
        status=MatchStatus.UPLOADED,
    )
    _enqueue(session, supervisor, record)
    logger.info(
        "accepted upload %s (%s, %d bytes)", match_id, stored.display_name, stored.size_bytes
    )
    return MatchCreatedOut(id=record.id, status=record.status)


@router.post(
    "/import",
    response_model=MatchCreatedOut,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"description": "The URL was rejected or could not be downloaded"}},
)
def import_match(
    payload: ImportRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    supervisor: WorkerSupervisor = Depends(get_supervisor),
) -> MatchCreatedOut:
    """Download a demo from a public URL and queue it.

    The URL is validated, resolved and pinned before any request is made — see
    :mod:`app.ingest.fetch` for the guards and the documented residual risks.
    """
    if not settings.allow_url_import:
        raise errors.invalid_request(
            "url_import_disabled", "Importing from a URL is disabled on this server."
        )
    try:
        storage.check_capacity(settings)
    except storage.StorageFullError as exc:
        raise errors.insufficient_storage(str(exc)) from exc

    match_id = _new_id()
    try:
        stored = fetch.fetch_demo(str(payload.url), settings, match_id)
    except Exception as exc:
        raise _translate_storage_error(exc) from exc

    duplicate = _existing_by_hash(session, stored.sha256)
    if duplicate is not None:
        storage.delete_demo(stored.path)
        raise errors.duplicate_match(duplicate.id)

    record = Match(
        id=match_id,
        sha256=stored.sha256,
        original_filename=storage.safe_display_name(payload.filename or stored.display_name),
        stored_path=str(stored.path),
        size_bytes=stored.size_bytes,
        source="url",
        source_url=str(payload.url),
        status=MatchStatus.UPLOADED,
    )
    _enqueue(session, supervisor, record)
    return MatchCreatedOut(id=record.id, status=record.status)


@router.get("", response_model=MatchListOut)
def list_matches(
    match_status: str | None = Query(default=None, alias="status"),
    map_name: str | None = Query(default=None, alias="map"),
    search: str | None = Query(default=None, max_length=100, alias="q"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    session: Session = Depends(get_db),
) -> MatchListOut:
    """List matches, newest first."""
    conditions = []
    if match_status:
        allowed = {str(s) for s in MatchStatus}
        if match_status not in allowed:
            raise errors.invalid_request(
                "invalid_status",
                f"Unknown status; expected one of {sorted(allowed)}.",
            )
        conditions.append(Match.status == match_status)
    if map_name:
        conditions.append(Match.map_name == map_name)
    if search:
        pattern = f"%{search}%"
        conditions.append(Match.original_filename.ilike(pattern) | Match.map_name.ilike(pattern))

    total = session.scalar(select(func.count()).select_from(Match).where(*conditions)) or 0
    rows = session.scalars(
        select(Match)
        .where(*conditions)
        .order_by(Match.created_at.desc(), Match.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return MatchListOut(
        items=[MatchSummaryOut.from_model(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _require_match(session: Session, match_id: str) -> Match:
    record = session.get(Match, match_id)
    if record is None:
        raise errors.not_found()
    return record


@router.get("/{match_id}", response_model=MatchDetailOut)
def get_match(match_id: str, session: Session = Depends(get_db)) -> MatchDetailOut:
    """Metadata, processing status, dataset availability and anomalies.

    This is the polling endpoint. ``status`` plus ``stage`` tells the UI whether the
    match is waiting, parsing, done or failed, and ``availability`` tells it which
    metrics this demo can support at all.
    """
    return MatchDetailOut.from_model(_require_match(session, match_id))


@router.get("/{match_id}/players", response_model=list[PlayerStatsOut])
def get_players(match_id: str, session: Session = Depends(get_db)) -> list[PlayerStatsOut]:
    """The scoreboard, highest kills first."""
    _require_match(session, match_id)
    rows = session.scalars(
        select(MatchPlayer)
        .where(MatchPlayer.match_id == match_id)
        .order_by(MatchPlayer.kills.desc(), MatchPlayer.adr.desc())
    ).all()
    return [PlayerStatsOut.from_model(r) for r in rows]


@router.get("/{match_id}/rounds", response_model=list[RoundOut])
def get_rounds(match_id: str, session: Session = Depends(get_db)) -> list[RoundOut]:
    """Round summaries with each round's per-player contributions inlined."""
    _require_match(session, match_id)
    rounds = session.scalars(
        select(MatchRound).where(MatchRound.match_id == match_id).order_by(MatchRound.round_num)
    ).all()
    players = session.scalars(
        select(MatchRoundPlayer)
        .where(MatchRoundPlayer.match_id == match_id)
        .order_by(
            MatchRoundPlayer.round_num,
            MatchRoundPlayer.kills.desc(),
            MatchRoundPlayer.damage.desc(),
        )
    ).all()
    by_round: dict[int, list[MatchRoundPlayer]] = {}
    for row in players:
        by_round.setdefault(row.round_num, []).append(row)
    return [RoundOut.from_model(r, by_round.get(r.round_num, [])) for r in rounds]


@router.delete("/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_match(
    match_id: str,
    session: Session = Depends(get_db),
    supervisor: WorkerSupervisor = Depends(get_supervisor),
) -> Response:
    """Delete a match, its analytics and its stored demo file.

    A match that is mid-parse is cancelled first: the worker runs in its own process
    precisely so it can be terminated here rather than left running against rows that no
    longer exist.
    """
    record = _require_match(session, match_id)
    stored_path = record.stored_path

    if not MatchStatus(record.status).is_terminal:
        record.cancel_requested = True
        session.commit()
        supervisor.cancel(match_id)

    session.delete(record)
    session.commit()
    storage.delete_demo(stored_path)
    logger.info("deleted match %s", match_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
