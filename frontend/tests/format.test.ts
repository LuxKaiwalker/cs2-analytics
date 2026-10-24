/** Formatting, and the rule that unknown is never zero. */

import { describe, expect, it } from 'vitest'
import {
  UNKNOWN,
  formatBuyType,
  formatBytes,
  formatDuration,
  formatMapName,
  formatMetric,
  formatRoundClock,
  formatRoundReason,
  formatWeapon,
} from '../src/lib/format'

describe('formatMetric', () => {
  it('renders null as an em dash, never as zero', () => {
    expect(formatMetric(null)).toBe(UNKNOWN)
    expect(formatMetric(undefined)).toBe(UNKNOWN)
    expect(formatMetric(null, { format: 'percent' })).toBe(UNKNOWN)
  })

  it('keeps a genuine zero distinct from unknown', () => {
    expect(formatMetric(0, { format: 'decimal' })).toBe('0.0')
    expect(formatMetric(0, { format: 'percent' })).toBe('0.0%')
    expect(formatMetric(0, { format: 'percent' })).not.toBe(UNKNOWN)
  })

  it('formats each metric kind to its own precision', () => {
    expect(formatMetric(183.153_8, { format: 'decimal' })).toBe('183.2')
    expect(formatMetric(40.740_7, { format: 'percent' })).toBe('40.7%')
    expect(formatMetric(27, { format: 'ratio' })).toBe('27.00')
    expect(formatMetric(13, { format: 'integer' })).toBe('13')
  })

  it('treats NaN as unknown', () => {
    expect(formatMetric(Number.NaN)).toBe(UNKNOWN)
  })
})

describe('formatRoundClock', () => {
  it('keeps freeze-time events negative rather than clamping them', () => {
    // Negative round time is real: the event happened during the buy phase.
    expect(formatRoundClock(-26.5)).toBe('-0:26.5')
  })

  it('formats in-round time', () => {
    expect(formatRoundClock(6.25)).toBe('0:06.3')
    expect(formatRoundClock(75)).toBe('1:15.0')
  })

  it('renders null as unknown', () => {
    expect(formatRoundClock(null)).toBe(UNKNOWN)
  })
})

describe('other formatters', () => {
  it('formats bytes', () => {
    expect(formatBytes(84_203_211)).toBe('80.3 MB')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(null)).toBe(UNKNOWN)
  })

  it('formats durations', () => {
    expect(formatDuration(647)).toBe('10:47')
    expect(formatDuration(null)).toBe(UNKNOWN)
  })

  it('makes map names readable without inventing one', () => {
    expect(formatMapName('de_mirage')).toBe('Mirage')
    expect(formatMapName('cs_office')).toBe('Office')
    expect(formatMapName(null)).toBe('Unknown map')
  })

  it('strips the weapon prefix', () => {
    expect(formatWeapon('weapon_ak47')).toBe('ak47')
    expect(formatWeapon('usp_silencer')).toBe('usp silencer')
    expect(formatWeapon(null)).toBe(UNKNOWN)
  })

  it('translates round end reasons and buy types', () => {
    expect(formatRoundReason('target_bombed')).toBe('Bomb detonated')
    expect(formatRoundReason('ct_win')).toBe('CT elimination')
    expect(formatRoundReason(null)).toBe(UNKNOWN)
    expect(formatBuyType('full')).toBe('Full buy')
    expect(formatBuyType(null)).toBe(UNKNOWN)
  })
})
