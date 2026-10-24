/** Side and team labels and colours. */

import type { Side, Team } from '../api/types'

export function sideLabel(side: Side | null | undefined): string {
  if (side === 'CT') return 'CT'
  if (side === 'T') return 'T'
  return '—'
}

export function sideFullName(side: Side | null | undefined): string {
  if (side === 'CT') return 'Counter-Terrorists'
  if (side === 'T') return 'Terrorists'
  return 'Unknown side'
}

/** CSS variable for a side's colour, used by the spatial plot's marks. */
export function sideColor(side: Side | null | undefined): string {
  if (side === 'CT') return 'var(--color-ct)'
  if (side === 'T') return 'var(--color-t)'
  return 'var(--color-ink-muted)'
}

/**
 * CSS variable for a team's colour.
 *
 * Keyed on the team, not on rank or row order, so a filter that changes which teams are
 * on screen never repaints the ones that remain.
 */
export function teamColor(team: Team | null | undefined): string {
  if (team === 'A') return 'var(--color-team-a)'
  if (team === 'B') return 'var(--color-team-b)'
  return 'var(--color-ink-muted)'
}

export function teamName(
  team: Team | null | undefined,
  names: { team_a_name?: string | null; team_b_name?: string | null },
): string {
  if (team === 'A') return names.team_a_name || 'Team A'
  if (team === 'B') return names.team_b_name || 'Team B'
  return 'Unknown team'
}
