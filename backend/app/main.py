"""The FastAPI application.

Assembles routes, error handling and the background worker. Two things here are load-
bearing rather than boilerplate:

* **A Content-Length guard runs before the body is read.** It is the only place an
  oversized upload can be refused without consuming resources; the streaming cap in the
  storage layer handles chunked bodies that declare no length.
* **The frontend is served from the same origin**, so there is no CORS middleware at all.
  In development Vite proxies ``/api``; in production the built assets are mounted here.
  Uploaded demos live in the data directory, which is never mounted.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import events, health, maps, matches, metrics
from app.config import Settings, get_settings
from app.db import get_engine
from app.errors import error_body, register_error_handlers
from app.persist.schema_check import init_schema
from app.pipeline.supervisor import get_supervisor

logger = logging.getLogger(__name__)

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("CS2A_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare storage, schema and worker; recover anything a restart interrupted."""
    settings: Settings = get_settings()
    settings.ensure_dirs()
    init_schema(get_engine())

    supervisor = get_supervisor()
    supervisor.start()
    # A restart leaves rows claiming to be mid-parse. They are re-queued with an attempt
    # counter so a demo that reliably crashes the worker is abandoned instead of looping.
    supervisor.recover_interrupted()

    # Radar assets download on first use; warming here keeps that off the request path.
    with suppress(Exception):
        from app.maps.data import available_maps  # noqa: PLC0415

        logger.info("radar assets available for %d maps", len(available_maps(settings)))

    logger.info("ready — data directory %s", settings.data_dir)
    try:
        yield
    finally:
        supervisor.stop()
        logger.info("shut down")
    _ = app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application."""
    configure_logging()
    settings = settings or get_settings()

    app = FastAPI(
        title="CS2 Match Analytics",
        version="0.1.0",
        description=(
            "Post-match analytics for Counter-Strike 2 demos. Upload a .dem file, the "
            "server parses it and computes per-player, per-round and per-event "
            "statistics. Metric definitions are published at /api/metrics."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def limit_body_size(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuse an over-long declared body before any of it is read.

        This is the only layer that can prevent the resource use rather than merely
        report it after the fact.
        """
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_demo_bytes:
            return JSONResponse(
                status_code=413,
                content=error_body(
                    "file_too_large",
                    f"The request body exceeds the "
                    f"{settings.max_demo_bytes // (1024 * 1024)} MiB limit.",
                    {"limit_bytes": settings.max_demo_bytes, "received_bytes": int(declared)},
                ),
            )
        return await call_next(request)

    app.include_router(health.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(maps.router, prefix="/api")
    app.include_router(matches.router, prefix="/api")
    app.include_router(events.router, prefix="/api")

    if settings.serve_frontend and _FRONTEND_DIST.is_dir():
        _mount_frontend(app)
    elif settings.serve_frontend:
        logger.warning(
            "CS2A_SERVE_FRONTEND is set but %s does not exist; run 'npm run build' first",
            _FRONTEND_DIST,
        )

    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built single-page app, with client-side routes falling back to index."""
    assets = _FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = _FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        candidate = (_FRONTEND_DIST / full_path).resolve()
        # Confine resolution to the build directory: the path comes from the URL.
        if full_path and candidate.is_file() and candidate.is_relative_to(_FRONTEND_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving frontend from %s", _FRONTEND_DIST)


app = create_app()
