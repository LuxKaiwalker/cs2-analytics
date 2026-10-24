"""Radar images and coordinate transforms."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app import errors
from app.maps import data as map_data
from app.schemas import MapInfoOut, MapLevelOut

router = APIRouter(prefix="/maps", tags=["maps"])

#: Radar images for a given asset release never change, so they cache aggressively.
_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/{map_name}", response_model=MapInfoOut)
def map_info(map_name: str) -> MapInfoOut:
    """The transform and radar URLs for one map.

    An unavailable map returns ``available: false`` with a reason rather than a 404, so
    the UI can explain itself instead of silently dropping the spatial view.
    """
    assets = map_data.get_assets(map_name)
    return MapInfoOut(
        map_name=assets.map_name,
        available=assets.available,
        pos_x=assets.pos_x,
        pos_y=assets.pos_y,
        scale=assets.scale,
        image_width=assets.image_width,
        image_height=assets.image_height,
        levels=[
            MapLevelOut(
                id=level.id,
                radar_url=f"/api/maps/{assets.map_name}/radar.png?level={level.id}",
                altitude_min=level.altitude_min,
                altitude_max=level.altitude_max,
            )
            for level in assets.levels
        ],
        reason=assets.reason,
    )


@router.get("/{map_name}/radar.png", response_class=FileResponse)
def radar_image(
    map_name: str,
    level: str = Query(default="default", pattern="^(default|lower)$"),
) -> Response:
    """Serve a radar image from the local asset cache."""
    assets = map_data.get_assets(map_name)
    if not assets.available:
        raise errors.not_found("map radar image")
    match = next((lvl for lvl in assets.levels if lvl.id == level), None)
    if match is None:
        raise errors.not_found("map radar level")
    return FileResponse(
        match.path,
        media_type="image/png",
        headers={"Cache-Control": _CACHE_CONTROL},
    )
