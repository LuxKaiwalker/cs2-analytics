/**
 * Round-by-round analysis.
 *
 * The table gives the shape of the match; selecting a round opens its chronological
 * event sequence and per-player contribution, which is the level at which "what
 * actually happened" is answerable.
 */

import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useApi } from '../../hooks/useApi'
import type { MatchDetail, MatchEvent, Round, Team } from '../../api/types'
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  SideBadge,
} from '../ui/primitives'
import {
  formatBuyType,
  formatDuration,
  formatMoney,
  formatRoundClock,
  formatRoundReason,
  formatWeapon,
} from '../../lib/format'
import { teamColor, teamName } from '../../lib/sides'

interface Props {
  match: MatchDetail
  rounds: Round[]
  selectedRound: number | null
  onSelectRound: (roundNum: number) => void
}

export function RoundsTab({ match, rounds, selectedRound, onSelectRound }: Props) {
  const [teamFilter, setTeamFilter] = useState<'all' | Team>('all')

  // Default to the first round so the detail panel is never empty on arrival.
  useEffect(() => {
    if (selectedRound === null && rounds.length > 0 && rounds[0]) {
      onSelectRound(rounds[0].round_num)
    }
  }, [rounds, selectedRound, onSelectRound])

  const visible = useMemo(
    () =>
      teamFilter === 'all'
        ? rounds
        : rounds.filter((round) => round.winner_team === teamFilter),
    [rounds, teamFilter],
  )

  const selected = rounds.find((round) => round.round_num === selectedRound) ?? null

  if (rounds.length === 0) {
    return (
      <Panel>
        <EmptyState
          title="No rounds"
          description="This demo parsed but contained no completed rounds."
        />
      </Panel>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1.1fr]">
      <Panel
        title="Rounds"
        subtitle={`${visible.length} of ${rounds.length} shown`}
        actions={
          <div className="flex rounded border border-[var(--color-line-strong)] p-0.5">
            {(['all', 'A', 'B'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setTeamFilter(value)}
                aria-pressed={teamFilter === value}
                className={`rounded px-2 py-0.5 text-[0.6875rem] transition ${
                  teamFilter === value
                    ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                    : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                }`}
              >
                {value === 'all' ? 'All wins' : teamName(value, match)}
              </button>
            ))}
          </div>
        }
      >
        <div className="max-h-[32rem] overflow-auto">
          <table className="stat-table">
            <thead>
              <tr>
                <th scope="col" className="w-10">
                  #
                </th>
                <th scope="col" className="text-left">
                  Winner
                </th>
                <th scope="col" className="text-left">
                  Outcome
                </th>
                <th scope="col">Score</th>
                <th scope="col">Time</th>
                <th scope="col">Kills</th>
                <th scope="col" className="text-left">
                  Economy
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((round) => (
                <tr
                  key={round.round_num}
                  onClick={() => onSelectRound(round.round_num)}
                  className="cursor-pointer"
                  style={
                    round.round_num === selectedRound
                      ? { background: 'var(--color-surface-hover)' }
                      : undefined
                  }
                >
                  <td className="tabular">
                    <span className="flex items-center gap-1">
                      {round.round_num}
                      {round.is_overtime && (
                        <span className="text-[0.5625rem] text-[var(--color-warn)]">OT</span>
                      )}
                    </span>
                  </td>
                  <td className="text-left">
                    <span className="flex items-center gap-1.5">
                      <span
                        aria-hidden="true"
                        className="inline-block h-3 w-0.5 rounded-full"
                        style={{ background: teamColor(round.winner_team) }}
                      />
                      <span className="truncate">{teamName(round.winner_team, match)}</span>
                      <SideBadge side={round.winner_side} />
                    </span>
                  </td>
                  <td className="text-left text-[var(--color-ink-secondary)]">
                    {round.is_knife_round ? (
                      <Badge tone="neutral">knife round</Badge>
                    ) : (
                      formatRoundReason(round.reason_name)
                    )}
                  </td>
                  <td className="tabular">
                    {round.score_a_after}–{round.score_b_after}
                  </td>
                  <td className="tabular text-[var(--color-ink-secondary)]">
                    {formatDuration(round.duration_s)}
                  </td>
                  <td className="tabular">{round.kills_count}</td>
                  <td className="text-left text-[0.6875rem] text-[var(--color-ink-secondary)]">
                    CT {formatBuyType(round.ct_buy_type)} · T {formatBuyType(round.t_buy_type)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {selected ? (
        <RoundDetail match={match} round={selected} />
      ) : (
        <Panel>
          <EmptyState title="Select a round" description="Pick a round to see its timeline." />
        </Panel>
      )}
    </div>
  )
}

function RoundDetail({ match, round }: { match: MatchDetail; round: Round }) {
  const { data, loading, error, reload } = useApi(
    () =>
      api.getEvents(match.id, {
        round_num: round.round_num,
        limit: 200,
        sort: 'seq',
        order: 'asc',
      }),
    [match.id, round.round_num],
  )

  const ctTeam = round.team_ct
  const byTeam = {
    A: round.players.filter((player) => player.team === 'A'),
    B: round.players.filter((player) => player.team === 'B'),
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={`Round ${round.round_num}`}
        subtitle={`${teamName(round.winner_team, match)} won · ${formatRoundReason(round.reason_name)}`}
        actions={
          <div className="flex items-center gap-1.5">
            {round.bomb_planted && (
              <Badge tone="warn">Bomb planted{round.bombsite ? ` · ${round.bombsite}` : ''}</Badge>
            )}
            {round.bomb_defused && <Badge tone="info">Defused</Badge>}
            {round.bomb_exploded && <Badge tone="bad">Detonated</Badge>}
          </div>
        }
      >
        <div className="grid grid-cols-2 gap-4 px-4 py-3 text-xs">
          {(['A', 'B'] as const).map((team) => (
            <div key={team}>
              <div className="mb-1.5 flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="inline-block size-2 rounded-sm"
                  style={{ background: teamColor(team) }}
                />
                <span className="font-medium">{teamName(team, match)}</span>
                <SideBadge side={ctTeam === team ? 'CT' : ctTeam ? 'T' : null} />
                <span className="ml-auto text-[0.6875rem] text-[var(--color-ink-muted)]">
                  {formatMoney(team === ctTeam ? round.ct_equipment_value : round.t_equipment_value)}
                </span>
              </div>
              <table className="w-full text-[0.6875rem]">
                <thead>
                  <tr className="text-[var(--color-ink-secondary)]">
                    <th scope="col" className="text-left font-normal">
                      Player
                    </th>
                    <th scope="col" className="w-7 text-right font-normal">
                      K
                    </th>
                    <th scope="col" className="w-7 text-right font-normal">
                      D
                    </th>
                    <th scope="col" className="w-10 text-right font-normal">
                      DMG
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {byTeam[team].map((player) => (
                    <tr key={player.player_key} className="border-t border-[var(--color-line)]/60">
                      <td className="truncate py-1">
                        <span className="flex items-center gap-1">
                          <span
                            className={player.survived ? '' : 'text-[var(--color-ink-muted)]'}
                            title={player.survived ? 'survived' : 'died this round'}
                          >
                            {player.name}
                          </span>
                          {!player.present_at_freeze && (
                            <span
                              className="text-[0.5625rem] text-[var(--color-ink-muted)]"
                              title="Not present at freeze time — excluded from this round's survival credit"
                            >
                              abs
                            </span>
                          )}
                          {player.is_clutch && (
                            <span
                              className="text-[0.5625rem] text-[var(--color-warn)]"
                              title={`Clutch 1v${player.clutch_opponents ?? '?'}${
                                player.clutch_won ? ' — won' : ' — lost'
                              }`}
                            >
                              1v{player.clutch_opponents}
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="py-1 text-right tabular">{player.kills}</td>
                      <td className="py-1 text-right tabular">{player.deaths}</td>
                      <td className="py-1 text-right tabular">{player.damage}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Timeline" subtitle="Chronological, from the round's freeze end">
        {loading ? (
          <LoadingState label="Loading events…" />
        ) : error ? (
          <ErrorState message={error.message} code={error.code} onRetry={reload} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState title="No events in this round" />
        ) : (
          <ol className="max-h-[22rem] divide-y divide-[var(--color-line)]/60 overflow-auto">
            {data.items.map((event) => (
              <TimelineRow key={event.seq} event={event} />
            ))}
          </ol>
        )}
      </Panel>
    </div>
  )
}

const EVENT_GLYPH: Record<string, string> = {
  round_start: '▸',
  freeze_end: '⏱',
  utility_thrown: '◌',
  flash: '✳',
  damage: '•',
  kill: '✖',
  bomb: '◆',
  round_end: '■',
}

function TimelineRow({ event }: { event: MatchEvent }) {
  const describe = () => {
    switch (event.event_type) {
      case 'kill':
        return (
          <>
            <strong className="font-medium">{event.actor_name ?? 'world'}</strong> killed{' '}
            <strong className="font-medium">{event.victim_name}</strong>
            <span className="text-[var(--color-ink-secondary)]">
              {' '}
              with {formatWeapon(event.weapon)}
              {event.is_headshot && ' · headshot'}
              {event.subtype === 'self_kill' && ' · self'}
              {event.subtype === 'team_kill' && ' · team kill'}
            </span>
          </>
        )
      case 'damage':
        return (
          <>
            {event.actor_name ?? 'world'} hit {event.victim_name} for{' '}
            <strong className="font-medium">{event.damage_health}</strong>
            <span className="text-[var(--color-ink-secondary)]">
              {' '}
              ({formatWeapon(event.weapon)}
              {event.hitgroup ? `, ${event.hitgroup.replace(/_/g, ' ')}` : ''})
            </span>
          </>
        )
      case 'flash':
        return (
          <>
            {event.actor_name} flashed {event.victim_name}
            <span className="text-[var(--color-ink-secondary)]">
              {' '}
              for {Number(event.extra?.duration ?? 0).toFixed(1)}s
              {event.subtype === 'team_or_self' && ' · team or self flash'}
            </span>
          </>
        )
      case 'utility_thrown':
        return (
          <>
            {event.actor_name} threw{' '}
            <span className="text-[var(--color-ink-secondary)]">{formatWeapon(event.weapon)}</span>
          </>
        )
      case 'bomb':
        return (
          <>
            {event.actor_name ?? 'someone'}{' '}
            <span className="text-[var(--color-ink-secondary)]">
              {(event.subtype ?? '').replace(/_/g, ' ')}
              {event.extra?.bombsite ? ` at ${String(event.extra.bombsite)}` : ''}
            </span>
          </>
        )
      case 'round_start':
        return <span className="text-[var(--color-ink-secondary)]">Round started</span>
      case 'freeze_end':
        return <span className="text-[var(--color-ink-secondary)]">Freeze time ended</span>
      case 'round_end':
        return (
          <span className="text-[var(--color-ink-secondary)]">
            Round ended · {formatRoundReason(event.subtype)}
          </span>
        )
      default:
        return <span>{event.event_type}</span>
    }
  }

  return (
    <li className="flex items-baseline gap-2.5 px-4 py-1.5 text-xs">
      <span className="w-14 shrink-0 text-right tabular text-[var(--color-ink-muted)]">
        {formatRoundClock(event.time_in_round_s)}
      </span>
      <span
        aria-hidden="true"
        className="w-3 shrink-0 text-center text-[var(--color-ink-muted)]"
      >
        {EVENT_GLYPH[event.event_type] ?? '·'}
      </span>
      <span className="min-w-0 flex-1">{describe()}</span>
      {event.is_post_round && (
        <span
          className="shrink-0 text-[0.5625rem] text-[var(--color-ink-muted)]"
          title="After the round was decided"
        >
          post
        </span>
      )}
    </li>
  )
}
