/**
 * The world-to-radar transform.
 *
 * Checked against the real published values for de_mirage, because a plausible-looking
 * but wrong transform is exactly the failure this view must not have.
 */

import { describe, expect, it } from 'vitest'
import type { MapInfo } from '../src/api/types'
import { levelForAltitude, worldToFraction, worldToRadar } from '../src/lib/radar'

const MIRAGE: MapInfo = {
  map_name: 'de_mirage',
  available: true,
  pos_x: -3230,
  pos_y: 1713,
  scale: 5,
  image_width: 1024,
  image_height: 1024,
  levels: [{ id: 'default', radar_url: '/r.png', altitude_min: null, altitude_max: null }],
  reason: null,
}

const NUKE: MapInfo = {
  ...MIRAGE,
  map_name: 'de_nuke',
  pos_x: -3453,
  pos_y: 2887,
  scale: 7,
  levels: [
    { id: 'default', radar_url: '/u.png', altitude_min: -495, altitude_max: 10_000 },
    { id: 'lower', radar_url: '/l.png', altitude_min: -10_000, altitude_max: -495 },
  ],
}

describe('worldToRadar', () => {
  it('maps the transform origin to the image origin', () => {
    expect(worldToRadar(-3230, 1713, MIRAGE)).toEqual({ x: 0, y: 0 })
  })

  it('divides by the scale on the x axis', () => {
    // 5 world units per pixel, so +500 units is +100 px.
    expect(worldToRadar(-2730, 1713, MIRAGE)).toEqual({ x: 100, y: 0 })
  })

  it('inverts the y axis, because world north is image up', () => {
    // Moving north (+y) must move *up* the image, i.e. toward row 0.
    expect(worldToRadar(-3230, 2213, MIRAGE)).toEqual({ x: 0, y: -100 })
    expect(worldToRadar(-3230, 1213, MIRAGE)).toEqual({ x: 0, y: 100 })
  })

  it('places the world origin where the published constants say', () => {
    expect(worldToRadar(0, 0, MIRAGE)).toEqual({ x: 646, y: 342.6 })
  })

  it('returns null rather than guessing when the transform is incomplete', () => {
    expect(worldToRadar(0, 0, { pos_x: null, pos_y: 1713, scale: 5 })).toBeNull()
    expect(worldToRadar(0, 0, { pos_x: -3230, pos_y: 1713, scale: 0 })).toBeNull()
  })
})

describe('worldToFraction', () => {
  it('converts to image fractions so the plot can be rendered at any size', () => {
    const point = worldToFraction(0, 0, MIRAGE)
    expect(point).not.toBeNull()
    expect(point?.x).toBeCloseTo(646 / 1024, 6)
    expect(point?.y).toBeCloseTo(342.6 / 1024, 6)
  })

  it('returns null when the image dimensions are unknown', () => {
    expect(worldToFraction(0, 0, { ...MIRAGE, image_width: null })).toBeNull()
  })
})

describe('levelForAltitude', () => {
  it('uses the only level on a single-level map', () => {
    expect(levelForAltitude(-170, MIRAGE)).toBe('default')
  })

  it('selects the band an altitude falls in on a multi-level map', () => {
    expect(levelForAltitude(0, NUKE)).toBe('default')
    expect(levelForAltitude(-800, NUKE)).toBe('lower')
  })

  it('returns null rather than defaulting a point outside every band', () => {
    // Drawing it on the wrong floor would be a confidently wrong answer.
    expect(levelForAltitude(99_999, NUKE)).toBeNull()
    expect(levelForAltitude(null, NUKE)).toBeNull()
  })
})
