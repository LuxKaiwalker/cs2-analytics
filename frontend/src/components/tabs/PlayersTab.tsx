/**
 * The scoreboard: a sortable, dense statistics table.
 *
 * Two rules the table enforces:
 *
 * - An unknown value renders as an em dash with its reason, never as 0. Sorting pushes
 *   unknowns to the end in both directions, so they never masquerade as the worst score.
 * - Every column's header carries the published definition of its metric, including the
 *   denominator, because that is where scoreboards usually differ from one another.
 */

import { useMemo, useState } from 'react'
import type { MatchDetail, MetricDefinition, PlayerStats, Side } from '../../api/types'
import { MetricHeader } from '../MetricHeader'
import { EmptyState, Panel, SideBadge, Tooltip } from '../ui/primitives'
import { formatMetric } from '../../lib/format'
import { teamColor, teamName } from '../../lib/sides'
import { useMetrics } from '../../hooks/useMetrics'

type NumericKey = {
  [K in keyof PlayerStats]: PlayerStats[K] extends number | null ? K : never
}[keyof PlayerStats]

interface Column {
  key: NumericKey
  label: string
  width?: string
}

const CORE: Column[] = [
  { key: 'kills', label: 'K' },
  { key: 'deaths', label: 'D' },
  { key: 'assists', label: 'A' },
  { key: 'kd', label: 'K/D' },
  { key: 'kpr', label: 'KPR' },
  { key: 'adr', label: 'ADR' },
  { key: 'headshot_pct', label: 'HS%' },
  { key: 'kast', label: 'KAST' },
  { key: 'opening_kills', label: 'OK' },
  { key: 'opening_deaths', label: 'OD' },
  { key: 'traded_deaths', label: 'TD' },
  { key: 'utility_damage', label: 'UD' },
  { key: 'enemies_flashed', label: 'EF' },
]

const EXTRA: Column[] = [
  { key: 'rounds_present', label: 'RNDS' },
  { key: 'headshot_kills', label: 'HSK' },
  { key: 'flash_assists', label: 'FA' },
  { key: 'trade_kills', label: 'TK' },
  { key: 'damage_total', label: 'DMG' },
  { key: 'flashes_thrown', label: 'FT' },
  { key: 'flash_duration_dealt', label: 'BLIND' },
  { key: 'multikill_3k', label: '3K' },
  { key: 'multikill_4k', label: '4K' },
  { key: 'multikill_5k', label: '5K' },
  { key: 'clutches_won', label: 'CLW' },
  { key: 'clutches_played', label: 'CL' },
  { key: 'team_kills', label: 'TmK' },
  { key: 'self_kills', label: 'SK' },
]

interface Props {
  match: MatchDetail
  players: PlayerStats[]
}

export function PlayersTab({ match, players }: Props) {
  const { byKey } = useMetrics()
  const [sortKey, setSortKey] = useState<NumericKey>('kills')
  const [descending, setDescending] = useState(true)
  const [sideFilter, setSideFilter] = useState<'all' | Side>('all')
  const [showAll, setShowAll] = useState(false)

  const columns = showAll ? [...CORE, ...EXTRA] : CORE

  const rows = useMemo(() => {
    const filtered =
      sideFilter === 'all'
        ? players
        : players.filter((player) => player.last_side === sideFilter)
    return [...filtered].sort((a, b) => {
      const left = a[sortKey]
      const right = b[sortKey]
      // Unknowns sort last whichever direction is active: an absent value is not a low one.
      if (left === null && right === null) return a.name.localeCompare(b.name)
      if (left === null) return 1
      if (right === null) return -1
      if (left === right) return a.name.localeCompare(b.name)
      return descending ? right - left : left - right
    })
  }, [players, sideFilter, sortKey, descending])

  const sortBy = (key: NumericKey) => {
    if (key === sortKey) {
      setDescending((value) => !value)
    } else {
      setSortKey(key)
      setDescending(true)
    }
  }

  if (players.length === 0) {
    return (
      <Panel>
        <EmptyState
          title="No player statistics"
          description="This match parsed successfully but produced no player rows."
        />
      </Panel>
    )
  }

  return (
    <Panel
      title="Player statistics"
      subtitle={`${rows.length} players · hover a column heading for its definition`}
      actions={
        <div className="flex items-center gap-1.5">
          <div className="flex rounded border border-[var(--color-line-strong)] p-0.5">
            {(['all', 'CT', 'T'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setSideFilter(value)}
                aria-pressed={sideFilter === value}
                className={`rounded px-2 py-0.5 text-[0.6875rem] transition ${
                  sideFilter === value
                    ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                    : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                }`}
              >
                {value === 'all' ? 'All' : value}
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowAll((value) => !value)}
            className="rounded px-2 py-1 text-[0.6875rem] text-[var(--color-ink-secondary)] transition hover:text-[var(--color-ink)]"
          >
            {showAll ? 'Fewer columns' : 'All columns'}
          </button>
        </div>
      }
    >
      <div className="overflow-x-auto">
        <table className="stat-table">
          <thead>
            <tr>
              <th scope="col" className="min-w-[12rem]">
                Player
              </th>
              <th scope="col" className="w-12">
                Side
              </th>
              {columns.map((column) => (
                <th key={column.key} scope="col">
                  <MetricHeader
                    definition={byKey[column.key]}
                    label={column.label}
                    sorted={sortKey === column.key ? (descending ? 'desc' : 'asc') : false}
                    onSort={() => sortBy(column.key)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((player) => (
              <tr key={player.player_key}>
                <td>
                  <span className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="h-3.5 w-0.5 shrink-0 rounded-full"
                      style={{ background: teamColor(player.team) }}
                      title={teamName(player.team, match)}
                    />
                    <span className="truncate font-medium">{player.name}</span>
                    {player.is_bot && (
                      <span className="text-[0.625rem] text-[var(--color-ink-muted)]">BOT</span>
                    )}
                  </span>
                </td>
                <td>
                  <SideBadge side={player.last_side} />
                </td>
                {columns.map((column) => (
                  <Cell
                    key={column.key}
                    value={player[column.key]}
                    metricKey={column.key}
                    match={match}
                    definition={byKey[column.key]}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="border-t border-[var(--color-line)] px-4 py-2.5 text-[0.6875rem] leading-relaxed text-[var(--color-ink-muted)]">
        Rates divide by the match's {match.round_count ?? '—'} scored rounds, excluding
        knife rounds. A dash means the demo did not contain the data for that metric — it
        is never shown as zero. No composite rating is provided; see{' '}
        <code>/api/metrics</code> for why.
      </p>
    </Panel>
  )
}

function Cell({
  value,
  metricKey,
  match,
  definition,
}: {
  value: number | null
  metricKey: string
  match: MatchDetail
  definition?: MetricDefinition
}) {
  if (value !== null) {
    return <td>{formatMetric(value, definition)}</td>
  }

  // Say *why* it is unknown: an empty source dataset reads differently from a zero
  // denominator, and the user can act on the difference.
  const sources = definition?.source_datasets ?? []
  const missing = sources
    .map((name) => ({ name, entry: match.availability[name] }))
    .filter((item) => item.entry && item.entry.state !== 'available')
  const reason = missing.length
    ? missing
        .map((item) => item.entry?.reason ?? `the ${item.name} data is ${item.entry?.state}`)
        .join(' ')
    : `Not defined for this player${definition?.denominator ? ` (no ${definition.denominator})` : ''}.`

  return (
    <td>
      <Tooltip content={reason}>
        <span className="unknown cursor-help" aria-label={`${metricKey}: unknown`}>
          —
        </span>
      </Tooltip>
    </td>
  )
}
