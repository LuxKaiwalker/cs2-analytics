"""Identify a demo by its content, not its filename.

A ``.dem`` extension proves nothing, so the leading bytes are checked instead. The point
is not only to reject junk but to reject it *informatively*: someone uploading a CS:GO
demo or a bz2-compressed one deserves to be told which it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: CS2 (Source 2) demos. ``PBDEMS2`` plus a NUL.
CS2_MAGIC = b"PBDEMS2\x00"
#: CS:GO / Source 1 demos. Recognised only so the error can say so.
SOURCE1_MAGIC = b"HL2DEMO\x00"
#: Valve distributes matchmaking demos bzip2-compressed.
BZIP2_MAGIC = b"BZh"
GZIP_MAGIC = b"\x1f\x8b"

#: Bytes needed to classify a file.
PROBE_BYTES = 8


class DemoKind(StrEnum):
    CS2 = "cs2"
    SOURCE1 = "source1"
    BZIP2 = "bzip2"
    GZIP = "gzip"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Detection:
    kind: DemoKind
    code: str | None
    """Machine error code when the content is not directly usable."""
    message: str | None

    @property
    def ok(self) -> bool:
        return self.kind is DemoKind.CS2

    @property
    def compressed(self) -> bool:
        return self.kind in (DemoKind.BZIP2, DemoKind.GZIP)


def detect(head: bytes) -> Detection:
    """Classify a file from its first bytes."""
    if head.startswith(CS2_MAGIC):
        return Detection(DemoKind.CS2, None, None)
    if head.startswith(SOURCE1_MAGIC):
        return Detection(
            DemoKind.SOURCE1,
            "source1_demo",
            "This is a CS:GO (Source 1) demo. Only Counter-Strike 2 demos are supported.",
        )
    if head.startswith(BZIP2_MAGIC):
        return Detection(
            DemoKind.BZIP2,
            "compressed_demo",
            "This file is bzip2-compressed. Decompress it to a .dem file first.",
        )
    if head.startswith(GZIP_MAGIC):
        return Detection(
            DemoKind.GZIP,
            "compressed_demo",
            "This file is gzip-compressed. Decompress it to a .dem file first.",
        )
    return Detection(
        DemoKind.UNKNOWN,
        "invalid_demo",
        "The file is not a CS2 demo. Expected a .dem file beginning with 'PBDEMS2'.",
    )
