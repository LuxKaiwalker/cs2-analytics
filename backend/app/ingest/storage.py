"""Stream an upload to disk under a generated name, with a hard size cap.

Why the upload route takes a raw body rather than a multipart form: by the time a handler
for a multipart request runs, the framework has *already* spooled the whole body to disk.
A size check there reports the problem but does not prevent it — a 10 GB post still costs
10 GB of disk before any of our code is consulted. Consuming the raw request stream lets
the cap be enforced mid-transfer and the partial file deleted immediately.

Three further properties this layer guarantees:

* **Generated names.** The stored filename is the match's own UUID. A client-supplied
  filename is kept for display only and never used to build a path, so path traversal is
  structurally impossible rather than merely filtered.
* **Same-filesystem staging.** Temporary files live beside the final directory, so
  promotion is an atomic rename and never a copy that could half-finish.
* **Content checks.** The leading bytes decide whether the file is a CS2 demo; the
  extension is not trusted.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.ingest import magic

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_DISPLAY_NAME = 120
#: Headroom kept free on the data volume so a full disk fails cleanly.
_DISK_HEADROOM_BYTES = 256 * 1024 * 1024


class UploadTooLargeError(Exception):
    """The body exceeded the configured cap. Raised mid-stream, before completion."""

    def __init__(self, received: int, limit: int) -> None:
        super().__init__(f"upload exceeded {limit} bytes")
        self.received = received
        self.limit = limit


class UploadTooSmallError(Exception):
    """The body is too small to be a demo."""

    def __init__(self, received: int, minimum: int) -> None:
        super().__init__(f"upload of {received} bytes is below the {minimum} byte minimum")
        self.received = received
        self.minimum = minimum


class UploadRejectedError(Exception):
    """The content is not a usable CS2 demo."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message


class StorageFullError(Exception):
    """The data volume or the configured budget has no room for this demo."""


@dataclass(frozen=True, slots=True)
class StoredDemo:
    """A validated demo on disk."""

    path: Path
    size_bytes: int
    sha256: str
    display_name: str


def safe_display_name(raw: str | None) -> str:
    """Sanitize a client-supplied filename for display.

    Used only as a label — storage paths are generated — so this is defence in depth
    against the name reaching a log, a header or the UI with something nasty in it.
    """
    if not raw:
        return "demo.dem"
    name = Path(raw).name
    name = _UNSAFE.sub("_", name).strip("._") or "demo.dem"
    if not name.lower().endswith(".dem"):
        name = f"{name}.dem"
    return name[:_MAX_DISPLAY_NAME]


def stored_bytes(settings: Settings) -> int:
    """Total size of demos already kept, for the configured storage budget."""
    if not settings.demos_dir.exists():
        return 0
    return sum(p.stat().st_size for p in settings.demos_dir.glob("*.dem") if p.is_file())


def check_capacity(settings: Settings, incoming_bytes: int | None = None) -> None:
    """Raise :class:`StorageFullError` when there is no room for another demo.

    Checked up front with the declared size when available, so an obviously impossible
    upload is refused before any bytes are written.
    """
    settings.ensure_dirs()
    planned = incoming_bytes or settings.max_demo_bytes
    usage = shutil.disk_usage(settings.data_dir)
    if usage.free < planned + _DISK_HEADROOM_BYTES:
        msg = "Not enough free disk space to store this demo."
        raise StorageFullError(msg)
    if stored_bytes(settings) + planned > settings.max_total_bytes:
        msg = (
            "The configured storage budget for demos is exhausted. Delete a match or "
            "raise CS2A_MAX_TOTAL_BYTES."
        )
        raise StorageFullError(msg)


class _Sink:
    """Writes chunks to a staging file while hashing and enforcing the cap."""

    def __init__(self, settings: Settings, match_id: str) -> None:
        settings.ensure_dirs()
        self._settings = settings
        self._final = settings.demos_dir / f"{match_id}.dem"
        self._staging = settings.tmp_dir / f"{match_id}.part"
        self._digest = hashlib.sha256()
        self._written = 0
        self._head = b""
        self._handle = self._staging.open("wb")

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._written += len(chunk)
        if self._written > self._settings.max_demo_bytes:
            raise UploadTooLargeError(self._written, self._settings.max_demo_bytes)
        if len(self._head) < magic.PROBE_BYTES:
            self._head += chunk[: magic.PROBE_BYTES - len(self._head)]
        self._digest.update(chunk)
        self._handle.write(chunk)

    def abandon(self) -> None:
        self._handle.close()
        self._staging.unlink(missing_ok=True)

    def _validate(self) -> None:
        """Reject anything that is not a usable CS2 demo, by content not by name."""
        if self._written < self._settings.min_demo_bytes:
            raise UploadTooSmallError(self._written, self._settings.min_demo_bytes)
        detection = magic.detect(self._head)
        if not detection.ok:
            raise UploadRejectedError(
                detection.code or "invalid_demo",
                detection.message or "Unsupported file.",
            )

    def finish(self, display_name: str) -> StoredDemo:
        """Validate the content, then atomically promote the staging file."""
        self._handle.close()
        try:
            self._validate()
            # Same filesystem by construction, so this is atomic.
            self._staging.replace(self._final)
        except Exception:
            self._staging.unlink(missing_ok=True)
            raise
        return StoredDemo(
            path=self._final,
            size_bytes=self._written,
            sha256=self._digest.hexdigest(),
            display_name=display_name,
        )


async def store_stream(
    settings: Settings,
    match_id: str,
    chunks: AsyncIterator[bytes],
    *,
    display_name: str | None = None,
) -> StoredDemo:
    """Consume an async byte stream into validated storage."""
    sink = _Sink(settings, match_id)
    try:
        async for chunk in chunks:
            sink.write(chunk)
    except Exception:
        sink.abandon()
        raise
    return sink.finish(safe_display_name(display_name))


def store_iter(
    settings: Settings,
    match_id: str,
    chunks: Iterator[bytes],
    *,
    display_name: str | None = None,
) -> StoredDemo:
    """Synchronous counterpart, used by the URL importer and the CLI."""
    sink = _Sink(settings, match_id)
    try:
        for chunk in chunks:
            sink.write(chunk)
    except Exception:
        sink.abandon()
        raise
    return sink.finish(safe_display_name(display_name))


def delete_demo(path: str | Path | None) -> None:
    """Remove a stored demo, tolerating one that is already gone."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not delete stored demo", exc_info=True)
