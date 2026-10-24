"""The child-process entrypoint: parse one demo and persist its analytics.

Runs in its own process, for three independent reasons any one of which would be
sufficient:

* **Latency.** It is not established that the parser's native core releases the GIL. A
  parse that held it would stall the event loop and every status poll with it.
* **Cancellation.** A Python thread cannot be killed, so "delete a match while it is
  processing" would be unimplementable in-thread. A process can be terminated.
* **Isolation.** The input is an untrusted binary file by design. A malformed demo that
  aborts inside the native parser takes this process down and nothing else.

A fourth, measured benefit: the child's memory returns to the OS when it exits, which
matters on a machine where the parse peaks at roughly 2.3x the demo's size.

The child owns its own database engine and writes its own stage transitions, so progress
survives a supervisor restart and needs no IPC plumbing.
"""

from __future__ import annotations

import logging
import os
import resource
import time
from datetime import UTC, datetime

from app.analytics.compute import compute
from app.config import Settings, get_settings
from app.models import Match, MatchStatus, ProcessingStage
from app.parsing import errors as parse_errors
from app.parsing.awpy_parser import get_parser
from app.persist.writer import persist_match

logger = logging.getLogger(__name__)


def _apply_memory_limit(settings: Settings) -> None:
    """Cap the child's address space.

    Converts an out-of-memory situation into a clean ``MemoryError`` we can report,
    instead of inviting the kernel's OOM killer to pick a victim — which on a desktop
    may well be something the user cares about more than this parse.
    """
    limit = settings.worker_mem_limit_mb * 1024 * 1024
    try:
        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
    except (ValueError, OSError):
        logger.warning("could not apply a memory limit to the parse worker", exc_info=True)


def _peak_rss_mb() -> int:
    """Peak resident memory of this process, in MiB."""
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def run_job(match_id: str) -> None:
    """Process one match. Intended as a subprocess target; never raises to the caller."""
    logging.basicConfig(
        level=os.environ.get("CS2A_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [worker] %(name)s: %(message)s",
    )
    settings = get_settings()
    _apply_memory_limit(settings)

    # A fresh engine: this process must not inherit connections or pools.
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import create_db_engine  # noqa: PLC0415

    engine = create_db_engine(settings)
    started = time.perf_counter()

    def set_stage(stage: ProcessingStage) -> None:
        with Session(engine) as session:
            record = session.get(Match, match_id)
            if record is None:
                return
            record.status = MatchStatus.PROCESSING
            record.stage = stage
            record.stage_started_at = datetime.now(UTC)
            session.commit()

    def fail(code: str, message: str, detail: str | None = None) -> None:
        logger.error("match %s failed (%s): %s", match_id, code, detail or message)
        with Session(engine) as session:
            record = session.get(Match, match_id)
            if record is None:
                return
            record.status = MatchStatus.FAILED
            record.stage = None
            record.stage_started_at = None
            record.error_code = code
            record.error_message = message
            record.peak_rss_mb = _peak_rss_mb()
            record.parse_seconds = round(time.perf_counter() - started, 2)
            session.commit()

    try:
        with Session(engine) as session:
            record = session.get(Match, match_id)
            if record is None:
                logger.error("match %s vanished before processing", match_id)
                return
            stored_path = record.stored_path
        if not stored_path:
            fail("demo_missing", "The stored demo file is missing.")
            return

        set_stage(ProcessingStage.PARSING)
        normalized = get_parser().parse(stored_path)

        set_stage(ProcessingStage.COMPUTING)
        analytics = compute(normalized)

        set_stage(ProcessingStage.PERSISTING)
        elapsed = round(time.perf_counter() - started, 2)
        with Session(engine) as session:
            persist_match(
                session,
                match_id,
                normalized,
                analytics,
                peak_rss_mb=_peak_rss_mb(),
                parse_seconds=elapsed,
            )
            session.commit()
        logger.info(
            "match %s completed in %.2fs (peak RSS %d MB, %d rounds, %d players)",
            match_id,
            elapsed,
            _peak_rss_mb(),
            analytics.round_count,
            len(analytics.players),
        )
    except parse_errors.DemoParseError as exc:
        # Expected, user-facing failures: a bad or unsupported demo.
        fail(exc.code, exc.user_message, exc.detail)
    except MemoryError:
        fail(
            "out_of_memory",
            "The demo was too large to process within the worker's memory limit. "
            "Raise CS2A_WORKER_MEM_LIMIT_MB to allow more.",
        )
    except Exception as exc:
        logger.exception("unexpected failure processing match %s", match_id)
        fail("internal_error", "Processing failed unexpectedly.", f"{type(exc).__name__}: {exc}")
    finally:
        engine.dispose()
