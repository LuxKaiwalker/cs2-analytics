/**
 * Value formatting.
 *
 * The single rule that matters: a `null` metric is "unknown", and unknown renders as an
 * em dash — never as 0. The backend deliberately distinguishes the two (no kills means
 * an undefined headshot rate, not a 0% one), and that distinction has to survive all
 * the way to the cell.
 */

import type { MetricDefinition } from '../api/types'

export const UNKNOWN = '—'

export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNKNOWN
  return value.toFixed(decimals)
}

export function formatMetric(
  value: number | null | undefined,
  definition?: Pick<MetricDefinition, 'format'>,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNKNOWN
  switch (definition?.format) {
    case 'percent':
      return `${value.toFixed(1)}%`
    case 'ratio':
      return value.toFixed(2)
    case 'decimal':
      return value.toFixed(1)
    default:
      return Number.isInteger(value) ? String(value) : value.toFixed(1)
  }
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return UNKNOWN
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return UNKNOWN
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const remainder = total % 60
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    return `${hours}h ${minutes % 60}m`
  }
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

/** Round time, which is legitimately negative during freeze time. */
export function formatRoundClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return UNKNOWN
  const sign = seconds < 0 ? '-' : ''
  const total = Math.abs(seconds)
  const minutes = Math.floor(total / 60)
  const remainder = (total % 60).toFixed(1).padStart(4, '0')
  return `${sign}${minutes}:${remainder}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return UNKNOWN
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return UNKNOWN
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86_400)}d ago`
}

/** A map's display name: `de_mirage` reads better as "Mirage". */
export function formatMapName(mapName: string | null | undefined): string {
  if (!mapName) return 'Unknown map'
  const stripped = mapName.replace(/^(de|cs|ar|rush)_/, '').replace(/_/g, ' ')
  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
}

/** Weapon names arrive as engine identifiers. */
export function formatWeapon(weapon: string | null | undefined): string {
  if (!weapon) return UNKNOWN
  return weapon.replace(/^weapon_/, '').replace(/_/g, ' ')
}

const REASON_LABELS: Record<string, string> = {
  ct_win: 'CT elimination',
  t_win: 'T elimination',
  terrorists_win: 'T elimination',
  counter_terrorists_win: 'CT elimination',
  target_bombed: 'Bomb detonated',
  bomb_defused: 'Bomb defused',
  target_saved: 'Time expired',
  hostages_rescued: 'Hostages rescued',
  hostages_not_rescued: 'Hostages not rescued',
}

export function formatRoundReason(reason: string | null | undefined): string {
  if (!reason) return UNKNOWN
  return REASON_LABELS[reason] ?? reason.replace(/_/g, ' ')
}

const BUY_LABELS: Record<string, string> = {
  pistol: 'Pistol',
  eco: 'Eco',
  force: 'Force',
  full: 'Full buy',
}

export function formatBuyType(buy: string | null | undefined): string {
  if (!buy) return UNKNOWN
  return BUY_LABELS[buy] ?? buy
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return UNKNOWN
  return `$${value.toLocaleString()}`
}
