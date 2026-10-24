/**
 * World-to-radar coordinate transform.
 *
 * The transform's constants come from the server (`/api/maps/{map}`), which reads them
 * from the published map data. Keeping the arithmetic in one tested function — and the
 * constants in one place on the server — is what stops the client and server disagreeing
 * about where a kill happened.
 *
 * World Y increases northwards while image rows increase downwards, hence the inversion.
 */

import type { MapInfo } from '../api/types'

export interface RadarPoint {
  x: number
  y: number
}

/** World coordinates to radar-image pixels. */
export function worldToRadar(
  worldX: number,
  worldY: number,
  transform: Pick<MapInfo, 'pos_x' | 'pos_y' | 'scale'>,
): RadarPoint | null {
  const { pos_x: posX, pos_y: posY, scale } = transform
  if (posX === null || posY === null || !scale) return null
  return { x: (worldX - posX) / scale, y: (posY - worldY) / scale }
}

/** Radar-image pixels to fractions of the image, for rendering at any size. */
export function radarToFraction(
  point: RadarPoint,
  info: Pick<MapInfo, 'image_width' | 'image_height'>,
): RadarPoint | null {
  if (!info.image_width || !info.image_height) return null
  return { x: point.x / info.image_width, y: point.y / info.image_height }
}

/** World coordinates straight to image fractions, or null if the map is unusable. */
export function worldToFraction(
  worldX: number,
  worldY: number,
  info: MapInfo,
): RadarPoint | null {
  const radar = worldToRadar(worldX, worldY, info)
  if (!radar) return null
  return radarToFraction(radar, info)
}

/**
 * Which radar level an altitude belongs to.
 *
 * Multi-level maps (Nuke, Vertigo) publish altitude bands. A point outside every band
 * returns null rather than being forced onto the default level, because drawing it on
 * the wrong floor would be a confidently wrong answer.
 */
export function levelForAltitude(z: number | null, info: MapInfo): string | null {
  if (z === null || info.levels.length === 0) return null
  if (info.levels.length === 1) return info.levels[0]?.id ?? null
  for (const level of info.levels) {
    const min = level.altitude_min
    const max = level.altitude_max
    if (min !== null && max !== null && z >= min && z < max) return level.id
  }
  return null
}
