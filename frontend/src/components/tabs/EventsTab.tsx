/**
 * The searchable event table.
 *
 * Filtering, sorting and paging all happen on the server. That is the point: a match has
 * thousands of events and the browser should never download them all to narrow them
 * down. Every control maps to a query parameter the API validates.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useApi } from '../../hooks/useApi'
import type {
  EventQuery,
  EventType,
  MatchDetail,
  MatchEvent,
  PlayerStats,
  Side,
} from '../../api/types'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  SideBadge,
} from '../ui/primitives'
import { formatRoundClock, formatWeapon } from '../../lib/format'

const PAGE_SIZE = 50

const EVENT_TYPES: { value: EventType | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'kill', label: 'Kills' },
  { value: 'damage', label: 'Damage' },
  { value: 'flash', label: 'Flashes' },
  { value: 'utility_thrown', label: 'Utility' },
  { value: 'bomb', label: 'Bomb' },
  { value: 'round_end', label: 'Round ends' },
]

const SORTS: { value: NonNullable<EventQuery['sort']>; label: string }[] = [
  { value: 'seq', label: 'Chronological' },
  { value: 'damage_health', label: 'Damage' },
  { value: 'tick', label: 'Tick' },
]

interface Props {
  match: MatchDetail
  players: PlayerStats[]
  roundCount: number
}

export function EventsTab({ match, players, roundCount }: Props) {
  const [eventType, setEventType] = useState<EventType | 'all'>('all')
  const [playerKey, setPlayerKey] = useState('')
  const [side, setSide] = useState<'' | Side>('')
  const [weapon, setWeapon] = useState('')
  const [round, setRound] = useState('')
  const [minDamage, setMinDamage] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [sort, setSort] = useState<NonNullable<EventQuery['sort']>>('seq')
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const [offset, setOffset] = useState(0)

  /**
   * Wrap a filter setter so changing it also returns to the first page.
   *
   * Done in the same update rather than from an effect watching the filters: page 7 of
   * the old result set is meaningless against the new one, and resetting it here avoids
   * a render that would briefly request a page that does not exist.
   */
  function filterSetter<T>(set: (value: T) => void): (value: T) => void {
    return (value: T) => {
      set(value)
      setOffset(0)
    }
  }

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  const query: EventQuery = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset,
      sort,
      order,
      ...(eventType !== 'all' ? { event_type: eventType } : {}),
      ...(playerKey ? { player_key: playerKey } : {}),
      ...(side ? { side } : {}),
      ...(weapon ? { weapon } : {}),
      ...(round ? { round_num: Number(round) } : {}),
      ...(minDamage ? { min_damage: Number(minDamage) } : {}),
      ...(debounced ? { search: debounced } : {}),
    }),
    [offset, sort, order, eventType, playerKey, side, weapon, round, minDamage, debounced],
  )

  const { data, loading, error, reload } = useApi(
    () => api.getEvents(match.id, query),
    [match.id, JSON.stringify(query)],
  )
  const weapons = useApi(() => api.getWeapons(match.id), [match.id])
  const counts = useApi(() => api.getEventCounts(match.id), [match.id])

  const clear = useCallback(() => {
    setEventType('all')
    setPlayerKey('')
    setSide('')
    setWeapon('')
    setRound('')
    setMinDamage('')
    setSearch('')
    setSort('seq')
    setOrder('asc')
    setOffset(0)
  }, [])

  const active =
    eventType !== 'all' || playerKey || side || weapon || round || minDamage || debounced

  const total = data?.total ?? 0
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <Panel
      title="Events"
      subtitle={
        data
          ? `${total.toLocaleString()} matching event${total === 1 ? '' : 's'}`
          : 'Loading…'
      }
      actions={
        active ? (
          <Button size="sm" variant="ghost" onClick={clear}>
            Clear filters
          </Button>
        ) : undefined
      }
    >
      {/* Filters in one row above the table. */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-line)] px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {EVENT_TYPES.map((option) => {
            const count = option.value === 'all' ? undefined : counts.data?.[option.value]
            return (
              <button
                key={option.value}
                onClick={() => filterSetter(setEventType)(option.value)}
                aria-pressed={eventType === option.value}
                className={`rounded border px-2 py-1 text-[0.6875rem] transition ${
                  eventType === option.value
                    ? 'border-[var(--color-team-a)] bg-[var(--color-team-a)]/12 text-[var(--color-ink)]'
                    : 'border-[var(--color-line-strong)] text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                }`}
              >
                {option.label}
                {count !== undefined && (
                  <span className="ml-1 text-[var(--color-ink-muted)] tabular">{count}</span>
                )}
              </button>
            )
          })}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(event) => filterSetter(setSearch)(event.target.value)}
            placeholder="Search players, weapons…"
            aria-label="Search events"
            className="w-44 rounded border border-[var(--color-line-strong)] bg-[var(--color-base)] px-2 py-1 text-xs placeholder:text-[var(--color-ink-muted)]"
          />
          <Select
            value={playerKey}
            onChange={filterSetter(setPlayerKey)}
            ariaLabel="Filter by player"
            options={[
              { value: '', label: 'Any player' },
              ...players.map((player) => ({ value: player.player_key, label: player.name })),
            ]}
          />
          <Select
            value={side}
            onChange={(value) => filterSetter(setSide)(value as '' | Side)}
            ariaLabel="Filter by side"
            options={[
              { value: '', label: 'Any side' },
              { value: 'CT', label: 'CT' },
              { value: 'T', label: 'T' },
            ]}
          />
          <Select
            value={weapon}
            onChange={filterSetter(setWeapon)}
            ariaLabel="Filter by weapon"
            options={[
              { value: '', label: 'Any weapon' },
              ...(weapons.data ?? []).map((name) => ({
                value: name,
                label: formatWeapon(name),
              })),
            ]}
          />
          <Select
            value={round}
            onChange={filterSetter(setRound)}
            ariaLabel="Filter by round"
            options={[
              { value: '', label: 'Any round' },
              ...Array.from({ length: roundCount }, (_, index) => ({
                value: String(index + 1),
                label: `Round ${index + 1}`,
              })),
            ]}
          />
          <input
            type="number"
            min={0}
            value={minDamage}
            onChange={(event) => filterSetter(setMinDamage)(event.target.value)}
            placeholder="Min dmg"
            aria-label="Minimum damage"
            className="w-20 rounded border border-[var(--color-line-strong)] bg-[var(--color-base)] px-2 py-1 text-xs placeholder:text-[var(--color-ink-muted)]"
          />
          <Select
            value={sort}
            onChange={(value) => filterSetter(setSort)(value as NonNullable<EventQuery['sort']>)}
            ariaLabel="Sort by"
            options={SORTS}
          />
          <button
            onClick={() => { setOrder(order === 'asc' ? 'desc' : 'asc'); setOffset(0) }}
            className="rounded border border-[var(--color-line-strong)] px-2 py-1 text-[0.6875rem] text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]"
            aria-label={`Sort ${order === 'asc' ? 'descending' : 'ascending'}`}
          >
            {order === 'asc' ? '↑ Asc' : '↓ Desc'}
          </button>
        </div>
      </div>

      {loading && !data ? (
        <LoadingState label="Loading events…" />
      ) : error ? (
        <ErrorState message={error.message} code={error.code} onRetry={reload} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title="No matching events"
          description={active ? 'Try widening or clearing the filters.' : undefined}
          action={
            active ? (
              <Button size="sm" onClick={clear}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="stat-table">
              <thead>
                <tr>
                  <th scope="col" className="w-12">
                    Rnd
                  </th>
                  <th scope="col" className="w-16">
                    Time
                  </th>
                  <th scope="col" className="w-20">
                    Tick
                  </th>
                  <th scope="col" className="text-left">
                    Event
                  </th>
                  <th scope="col" className="text-left">
                    Actor
                  </th>
                  <th scope="col" className="text-left">
                    Victim
                  </th>
                  <th scope="col" className="text-left">
                    Weapon
                  </th>
                  <th scope="col" className="w-14">
                    Dmg
                  </th>
                  <th scope="col" className="text-left">
                    Detail
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((event) => (
                  <tr key={event.seq}>
                    <td className="tabular">{event.round_num}</td>
                    <td className="tabular text-[var(--color-ink-secondary)]">
                      {formatRoundClock(event.time_in_round_s)}
                    </td>
                    <td className="tabular text-[var(--color-ink-muted)]">{event.tick}</td>
                    <td className="text-left">
                      <span className="flex items-center gap-1.5">
                        <span>{event.event_type.replace(/_/g, ' ')}</span>
                        {event.is_post_round && (
                          <Badge tone="neutral" title="After the round was decided">
                            post
                          </Badge>
                        )}
                      </span>
                    </td>
                    <td className="text-left">
                      <span className="flex items-center gap-1.5">
                        <SideBadge side={event.actor_side} />
                        <span className="truncate">{event.actor_name ?? '—'}</span>
                      </span>
                    </td>
                    <td className="text-left">
                      {event.victim_name ? (
                        <span className="flex items-center gap-1.5">
                          <SideBadge side={event.victim_side} />
                          <span className="truncate">{event.victim_name}</span>
                        </span>
                      ) : (
                        <span className="unknown">—</span>
                      )}
                    </td>
                    <td className="text-left text-[var(--color-ink-secondary)]">
                      {event.weapon ? formatWeapon(event.weapon) : <span className="unknown">—</span>}
                    </td>
                    <td className="tabular">
                      {event.damage_health !== null ? (
                        event.damage_health
                      ) : (
                        <span className="unknown">—</span>
                      )}
                    </td>
                    <td className="text-left text-[0.6875rem] text-[var(--color-ink-muted)]">
                      <Detail event={event} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-[var(--color-line)] px-4 py-2.5 text-xs">
            <span className="text-[var(--color-ink-secondary)] tabular">
              {offset + 1}–{Math.min(offset + data.items.length, total)} of{' '}
              {total.toLocaleString()}
            </span>
            <span className="flex items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                ← Previous
              </Button>
              <span className="text-[var(--color-ink-muted)] tabular">
                {page} / {pages}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next →
              </Button>
            </span>
          </div>
        </>
      )}
    </Panel>
  )
}

function Detail({ event }: { event: MatchEvent }) {
  const extra = event.extra ?? {}
  const parts: string[] = []
  if (event.event_type === 'kill') {
    if (event.is_headshot) parts.push('headshot')
    if (extra.assister_name) parts.push(`assist: ${String(extra.assister_name)}`)
    if (extra.assist_is_flash) parts.push('flash assist')
    if (extra.noscope) parts.push('no-scope')
    if (extra.thru_smoke) parts.push('through smoke')
    if (event.subtype && event.subtype !== 'kill') parts.push(event.subtype.replace(/_/g, ' '))
  } else if (event.event_type === 'damage') {
    const raw = extra.damage_raw
    // The reported figure and the figure that may be summed are both shown: the
    // difference is the capping rule, and hiding it would invite the wrong conclusion.
    if (typeof raw === 'number' && event.damage_health !== null && raw !== event.damage_health) {
      parts.push(`reported ${raw}, capped to ${event.damage_health}`)
    }
    if (event.hitgroup) parts.push(event.hitgroup.replace(/_/g, ' '))
    if (extra.is_team_damage) parts.push('team damage')
    if (extra.is_self_damage) parts.push('self damage')
  } else if (event.event_type === 'flash') {
    if (typeof extra.duration === 'number') parts.push(`${extra.duration.toFixed(2)}s`)
    if (event.subtype === 'team_or_self') parts.push('team or self')
  } else if (event.event_type === 'bomb') {
    if (event.subtype) parts.push(event.subtype.replace(/_/g, ' '))
    if (extra.bombsite) parts.push(`site ${String(extra.bombsite)}`)
  } else if (event.event_type === 'round_end' && event.subtype) {
    parts.push(event.subtype.replace(/_/g, ' '))
  }
  return <span className="truncate">{parts.join(' · ') || '—'}</span>
}

function Select({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  ariaLabel: string
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label={ariaLabel}
      className="max-w-[9rem] rounded border border-[var(--color-line-strong)] bg-[var(--color-base)] px-1.5 py-1 text-xs text-[var(--color-ink)]"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}
