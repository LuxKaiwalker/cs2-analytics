"""Radar images and coordinate transforms for the spatial view.

The parser project publishes the same radar images and transform table the game uses, so
positions can be plotted on a real map rather than an invented one. Three rules follow
from the "do not mislead" requirement:

* A map we have no transform or image for is reported **unavailable with a reason**. The
  UI then says so instead of drawing coordinates onto something plausible but wrong.
* The map name is validated against the published list before it reaches any path
  function, because it arrives from the URL.
* Image dimensions are read from the PNG header rather than assumed, so the client's
  pixel maths is anchored to the actual file.

Downloads happen on first use and are cached under the app's own data directory, never
the user's home. Assets are warmed at startup so no request pays for a download.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR_OFFSET = 16
_IHDR_SIZE = 8


@dataclass(frozen=True, slots=True)
class MapLevel:
    """One radar image: the default level, or the lower level of a multi-level map."""

    id: str
    path: Path
    altitude_min: float | None = None
    altitude_max: float | None = None


@dataclass(frozen=True, slots=True)
class MapAssets:
    """Everything needed to draw world positions onto a radar image."""

    map_name: str
    available: bool
    pos_x: float | None = None
    pos_y: float | None = None
    scale: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    levels: tuple[MapLevel, ...] = ()
    reason: str | None = None


def _configure(settings: Settings) -> Any:
    """Point the asset cache at our data directory, then hand back the data module.

    Assigning the module's cache root is the supported way to redirect it, and is done
    here rather than through the environment so it cannot depend on import order.
    """
    from awpy import data

    settings.ensure_dirs()
    data.AWPY_DATA_DIR = settings.awpy_dir
    return data


def available_maps(settings: Settings | None = None) -> list[str]:
    """Map names we have assets for. Empty if the asset index cannot be read."""
    settings = settings or get_settings()
    try:
        data = _configure(settings)
        return sorted(data.available_maps())
    except Exception:
        logger.warning("map asset index unavailable", exc_info=True)
        return []


def png_dimensions(path: Path) -> tuple[int, int] | None:
    """Read a PNG's pixel dimensions from its IHDR chunk.

    Twenty lines of struct beats adding an imaging library for two integers.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(_IHDR_OFFSET + _IHDR_SIZE)
    except OSError:
        return None
    if len(header) < _IHDR_OFFSET + _IHDR_SIZE or not header.startswith(_PNG_SIGNATURE):
        return None
    width, height = struct.unpack(">II", header[_IHDR_OFFSET : _IHDR_OFFSET + _IHDR_SIZE])
    return int(width), int(height)


def get_assets(map_name: str, settings: Settings | None = None) -> MapAssets:
    """Resolve the transform and radar images for ``map_name``."""
    settings = settings or get_settings()
    cleaned = (map_name or "").strip().lower()
    if not cleaned or not cleaned.replace("_", "").isalnum():
        return MapAssets(map_name=map_name, available=False, reason="Invalid map name.")

    try:
        data = _configure(settings)
    except Exception:
        logger.warning("map asset module unavailable", exc_info=True)
        return MapAssets(
            map_name=cleaned,
            available=False,
            reason="Map assets are unavailable in this installation.",
        )

    # Validate against the published list *before* the name reaches a path helper.
    try:
        known = set(data.available_maps())
    except Exception:  # noqa: BLE001
        known = set()
    if known and cleaned not in known:
        return MapAssets(
            map_name=cleaned,
            available=False,
            reason=f"No radar assets are published for '{cleaned}'.",
        )

    try:
        table = data.map_data()
    except Exception:
        logger.warning("map transform table unavailable", exc_info=True)
        return MapAssets(
            map_name=cleaned,
            available=False,
            reason="The map coordinate table could not be loaded.",
        )

    entry = table.get(cleaned)
    if not entry:
        return MapAssets(
            map_name=cleaned,
            available=False,
            reason=f"No coordinate transform is published for '{cleaned}'.",
        )

    pos_x, pos_y, scale = entry.get("pos_x"), entry.get("pos_y"), entry.get("scale")
    if pos_x is None or pos_y is None or not scale:
        return MapAssets(
            map_name=cleaned,
            available=False,
            reason=f"The coordinate transform for '{cleaned}' is incomplete.",
        )

    rotate, zoom = entry.get("rotate"), entry.get("zoom")
    if rotate not in (None, 0, 0.0) or zoom not in (None, 0, 0.0):
        # A few maps (de_dust2, cs_italy, ar_baggage) carry non-zero rotate/zoom values
        # inherited from the old radar metadata format. The reference plotting
        # implementation ignores them and uses pos_x/pos_y/scale alone, and its output is
        # known-good, so we do the same rather than apply a transform we cannot verify.
        # Recorded as a known limitation in docs/METRICS.md.
        logger.debug(
            "map %s declares rotate=%s zoom=%s; using the pos/scale transform only",
            cleaned,
            rotate,
            zoom,
        )

    sections = entry.get("verticalsections") or {}
    levels: list[MapLevel] = []
    for level_id, lower in (("default", False), ("lower", True)):
        if level_id == "lower" and "lower" not in sections:
            continue
        try:
            path = Path(data.radar_path(cleaned, lower=lower))
        except Exception:
            logger.warning("radar image for %s (%s) unavailable", cleaned, level_id, exc_info=True)
            continue
        if not path.exists():
            continue
        band = sections.get("default" if level_id == "default" else "lower") or {}
        levels.append(
            MapLevel(
                id=level_id,
                path=path,
                altitude_min=_as_float(band.get("AltitudeMin")),
                altitude_max=_as_float(band.get("AltitudeMax")),
            )
        )

    if not levels:
        return MapAssets(
            map_name=cleaned,
            available=False,
            pos_x=float(pos_x),
            pos_y=float(pos_y),
            scale=float(scale),
            reason=(
                "The radar image for this map has not been downloaded. Run "
                "'python -m app.cli warm-maps' with network access."
            ),
        )

    dimensions = png_dimensions(levels[0].path)
    return MapAssets(
        map_name=cleaned,
        available=True,
        pos_x=float(pos_x),
        pos_y=float(pos_y),
        scale=float(scale),
        image_width=dimensions[0] if dimensions else None,
        image_height=dimensions[1] if dimensions else None,
        levels=tuple(levels),
    )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def world_to_radar(
    x: float, y: float, pos_x: float, pos_y: float, scale: float
) -> tuple[float, float]:
    """Convert world coordinates to radar-image pixels.

    Mirrors the client's implementation and exists so the transform can be unit-tested
    against known values. The Y axis is inverted because world Y increases north while
    image rows increase downward.
    """
    return (x - pos_x) / scale, (pos_y - y) / scale


def warm_cache(settings: Settings | None = None) -> int:
    """Pre-download the radar assets so no request ever pays for a download."""
    settings = settings or get_settings()
    names = available_maps(settings)
    warmed = 0
    for name in names:
        assets = get_assets(name, settings)
        if assets.available:
            warmed += 1
    logger.info("warmed radar assets for %d of %d maps", warmed, len(names))
    return warmed
