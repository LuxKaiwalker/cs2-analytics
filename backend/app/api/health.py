"""Liveness and capacity reporting."""

from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import session_scope
from app.ingest import storage
from app.models import SCHEMA_VERSION
from app.parsing.awpy_parser import get_parser
from app.pipeline.supervisor import get_supervisor
from app.schemas import HealthOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Report whether the service can actually accept and process work."""
    settings = get_settings()
    supervisor = get_supervisor()

    database_ok = True
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("database health check failed")
        database_ok = False

    try:
        free = shutil.disk_usage(settings.data_dir).free
    except OSError:
        free = None

    parser_version: str | None
    try:
        parser_version = get_parser().version()
    except Exception:
        logger.exception("parser version unavailable")
        parser_version = None

    healthy = database_ok and supervisor.alive and parser_version is not None
    return HealthOut(
        status="ok" if healthy else "degraded",
        database=database_ok,
        worker_alive=supervisor.alive,
        queue_depth=supervisor.depth,
        processing_match_id=supervisor.current_match_id,
        disk_free_bytes=free,
        demo_bytes_stored=storage.stored_bytes(settings),
        max_demo_bytes=settings.max_demo_bytes,
        parser="awpy",
        parser_version=parser_version,
        schema_version=SCHEMA_VERSION,
    )
