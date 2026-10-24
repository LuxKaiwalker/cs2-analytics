"""Queue demos and supervise one parse subprocess at a time.

The database is the source of truth for status; the in-memory queue only decides order.
That split is what makes restart recovery possible: whatever the queue held is
reconstructed from rows marked ``queued`` or ``processing``.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_engine
from app.models import Match, MatchStatus
from app.pipeline.job import run_job

logger = logging.getLogger(__name__)

_TERMINATE_GRACE_S = 10.0
_POLL_INTERVAL_S = 0.25


class QueueFullError(Exception):
    """The queue is at its configured depth."""


class WorkerSupervisor:
    """A single daemon thread that runs queued matches one at a time.

    One at a time is a deliberate choice, not a limitation: parsing is CPU- and
    memory-bound, and the measured peak is roughly 2.3x the demo's size. Running several
    concurrently on a machine with a few spare gigabytes would trade a modest throughput
    gain for the real risk of an out-of-memory kill.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current: tuple[str, mp.process.BaseProcess] | None = None
        # `spawn`, never `fork`: forking a process that owns an event loop, a connection
        # pool and open SQLite handles duplicates all of them into the child, which is a
        # classic source of corrupted state and deadlocks.
        self._ctx = mp.get_context("spawn")

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="parse-supervisor", daemon=True)
        self._thread.start()
        logger.info("parse supervisor started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            current = self._current
        if current is not None:
            self._kill(current[1])

    def submit(self, match_id: str) -> None:
        """Enqueue a match, refusing when the backlog is at its limit."""
        if self._queue.qsize() >= self._settings.queue_max_depth:
            raise QueueFullError
        self._queue.put(match_id)

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_match_id(self) -> str | None:
        with self._lock:
            return self._current[0] if self._current else None

    def cancel(self, match_id: str) -> bool:
        """Kill the job for ``match_id`` if it is the one running.

        Queued-but-not-started jobs are skipped when they reach the front, by checking
        the ``cancel_requested`` flag the API has already set.
        """
        with self._lock:
            if self._current and self._current[0] == match_id:
                logger.info("cancelling in-flight match %s", match_id)
                self._kill(self._current[1])
                return True
        return False

    def recover_interrupted(self) -> int:
        """Re-enqueue matches left mid-flight by a restart.

        Each recovery increments an attempt counter and anything past the limit is
        failed. Without that counter, a demo that crashes the worker would be retried
        forever on every restart.
        """
        requeued = 0
        with Session(self._engine()) as session:
            stale = session.scalars(
                select(Match)
                .where(Match.status.in_([MatchStatus.QUEUED, MatchStatus.PROCESSING]))
                .order_by(Match.created_at)
            ).all()
            for record in stale:
                record.attempts += 1
                if record.attempts > self._settings.max_attempts:
                    record.status = MatchStatus.FAILED
                    record.stage = None
                    record.error_code = "abandoned_after_restart"
                    record.error_message = (
                        "Processing was interrupted repeatedly and has been abandoned. "
                        "Delete the match and upload it again to retry."
                    )
                    logger.warning(
                        "abandoning match %s after %d attempts", record.id, record.attempts
                    )
                    continue
                record.status = MatchStatus.QUEUED
                record.stage = None
                record.stage_started_at = None
                self._queue.put(record.id)
                requeued += 1
            session.commit()
        if requeued:
            logger.info("re-enqueued %d interrupted match(es) after restart", requeued)
        return requeued

    # ----------------------------------------------------------------- internals
    def _engine(self) -> Engine:
        return get_engine()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                match_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._run(match_id)
            except Exception:
                logger.exception("supervisor failed handling match %s", match_id)
            finally:
                self._queue.task_done()

    def _run(self, match_id: str) -> None:
        if self._claim(match_id) is False:
            return
        process = self._ctx.Process(
            target=run_job, args=(match_id,), name=f"parse-{match_id[:8]}", daemon=True
        )
        process.start()
        with self._lock:
            self._current = (match_id, process)
        try:
            self._await(match_id, process)
        finally:
            with self._lock:
                self._current = None

    def _claim(self, match_id: str) -> bool:
        """Mark the match as processing, or skip it if it was cancelled or deleted."""
        with Session(self._engine()) as session:
            record = session.get(Match, match_id)
            if record is None:
                logger.info("match %s no longer exists; skipping", match_id)
                return False
            if record.cancel_requested:
                record.status = MatchStatus.CANCELLED
                record.stage = None
                session.commit()
                logger.info("match %s was cancelled before it started", match_id)
                return False
            record.status = MatchStatus.PROCESSING
            record.stage_started_at = datetime.now(UTC)
            session.commit()
        return True

    def _await(self, match_id: str, process: mp.process.BaseProcess) -> None:
        """Wait for the child, enforcing the timeout and honouring cancellation."""
        deadline = time.monotonic() + self._settings.parse_timeout_s
        while process.is_alive():
            if self._stop.is_set():
                self._kill(process)
                return
            if time.monotonic() > deadline:
                logger.error("match %s exceeded the parse timeout", match_id)
                self._kill(process)
                self._mark_failed(
                    match_id,
                    "timeout",
                    "Processing took too long and was stopped. Raise "
                    "CS2A_PARSE_TIMEOUT_S to allow longer parses.",
                )
                return
            process.join(timeout=_POLL_INTERVAL_S)

        if process.exitcode not in (0, None):
            # A nonzero exit without a failure row means the child died hard — a native
            # crash or an external kill — so the status is set here instead.
            self._mark_failed(
                match_id,
                "worker_crashed",
                "The demo could not be processed; the parser exited unexpectedly.",
                exitcode=process.exitcode,
            )
        self._settle(match_id)

    def _kill(self, process: mp.process.BaseProcess) -> None:
        process.terminate()
        process.join(timeout=_TERMINATE_GRACE_S)
        if process.is_alive():
            process.kill()
            process.join(timeout=_TERMINATE_GRACE_S)

    def _mark_failed(
        self, match_id: str, code: str, message: str, exitcode: int | None = None
    ) -> None:
        with Session(self._engine()) as session:
            record = session.get(Match, match_id)
            if record is None or record.status == MatchStatus.COMPLETED:
                return
            # The child reports its own failures with a precise code; do not overwrite one.
            if record.status == MatchStatus.FAILED and record.error_code:
                return
            record.status = MatchStatus.FAILED
            record.stage = None
            record.stage_started_at = None
            record.error_code = code
            record.error_message = message
            session.commit()
        if exitcode is not None:
            logger.error("match %s worker exited with code %s", match_id, exitcode)

    def _settle(self, match_id: str) -> None:
        """Resolve a job left in a non-terminal state, including a cancellation."""
        with Session(self._engine()) as session:
            record = session.get(Match, match_id)
            if record is None:
                return
            if record.cancel_requested and not MatchStatus(record.status).is_terminal:
                record.status = MatchStatus.CANCELLED
                record.stage = None
                session.commit()
                return
            if not MatchStatus(record.status).is_terminal:
                record.status = MatchStatus.FAILED
                record.stage = None
                record.error_code = record.error_code or "worker_stopped"
                record.error_message = (
                    record.error_message or "Processing stopped before it completed."
                )
                session.commit()


_supervisor: WorkerSupervisor | None = None


def get_supervisor() -> WorkerSupervisor:
    """The process-wide supervisor."""
    global _supervisor
    if _supervisor is None:
        _supervisor = WorkerSupervisor()
    return _supervisor


def reset_supervisor() -> None:
    """Drop the cached supervisor. Used by tests."""
    global _supervisor
    if _supervisor is not None:
        _supervisor.stop()
    _supervisor = None
