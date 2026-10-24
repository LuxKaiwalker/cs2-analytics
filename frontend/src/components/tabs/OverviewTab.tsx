/** The match at a glance: result, context, shape, and who did the damage. */

import type { MatchDetail, PlayerStats, Round } from '../../api/types'
import { ScoreProgression } from '../charts/ScoreProgression'
import { RoundStrip } from '../charts/RoundStrip'
import { Badge, Panel, Stat, Tooltip } from '../ui/primitives'
import {
  formatDuration,
  formatMapName,
  formatMetric,
  formatNumber,
  formatRoundReason,
} from '../../lib/format'
import { teamColor, teamName } from '../../lib/sides'
import { useMetrics } from '../../hooks/useMetrics'

interface Props {
  match: MatchDetail
  players: PlayerStats[]
  rounds: Round[]
  onSelectRound: (roundNum: number) => void
}

export function OverviewTab({ match, players, rounds, onSelectRound }: Props) {
  const { byKey } = useMetrics()
  const scored = rounds.filter((round) => !round.is_knife_round)
  const topFraggers = [...players].sort((a, b) => b.kills - a.kills).slice(0, 3)
  const topAdr = [...players]
    .filter((player) => player.adr !== null)
    .sort((a, b) => (b.adr ?? 0) - (a.adr ?? 0))
    .slice(0, 3)

  const bombRounds = scored.filter((round) => round.bomb_planted).length
  const defuses = scored.filter((round) => round.bomb_defused).length

  return (
    <div className="flex flex-col gap-4">
      <Panel>
        <div className="flex flex-wrap items-center gap-6 px-4 py-4">
          <div>
            <div className="text-[0.6875rem] uppercase tracking-wide text-[var(--color-ink-secondary)]">
              Map
            </div>
            <div className="text-2xl font-semibold tracking-tight">
              {formatMapName(match.map_name)}
            </div>
            <div className="mt-0.5 text-[0.6875rem] text-[var(--color-ink-muted)]">
              {match.map_name ?? 'unknown'}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <TeamScore match={match} team="A" />
            <span className="text-xl text-[var(--color-ink-muted)]">:</span>
            <TeamScore match={match} team="B" />
          </div>

          <div className="ml-auto grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
            <Stat label="Rounds" value={formatNumber(match.round_count)} />
            <Stat
              label="Duration"
              value={formatDuration(match.playback_time)}
              hint={match.playback_time === null ? 'not recorded' : 'recording length'}
            />
            <Stat
              label="Bomb plants"
              value={`${bombRounds}`}
              hint={`${defuses} defused`}
            />
            <Stat
              label="Format"
              value={match.regulation_rounds ? `MR${match.regulation_rounds / 2}` : '—'}
              hint={match.has_overtime ? 'with overtime' : undefined}
            />
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Panel title="Score progression" subtitle="Cumulative rounds won">
          <div className="px-3 pb-3 pt-2">
            <ScoreProgression rounds={rounds} match={match} />
          </div>
        </Panel>

        <Panel title="Round outcomes" subtitle="Coloured by winning team — click to inspect">
          <div className="px-4 pb-4 pt-3">
            <RoundStrip rounds={rounds} match={match} onSelect={onSelectRound} />
            <div className="mt-3 flex flex-wrap gap-3 text-[0.6875rem]">
              {(['A', 'B'] as const).map((team) => (
                <span key={team} className="flex items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className="inline-block size-2.5 rounded-sm"
                    style={{
                      background: `color-mix(in oklab, ${teamColor(team)} 35%, transparent)`,
                      border: `1px solid ${teamColor(team)}`,
                    }}
                  />
                  <span className="text-[var(--color-ink-secondary)]">
                    {teamName(team, match)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Most kills">
          <ol className="divide-y divide-[var(--color-line)]">
            {topFraggers.map((player, index) => (
              <li key={player.player_key} className="flex items-center gap-3 px-4 py-2.5">
                <span className="w-4 text-xs text-[var(--color-ink-muted)] tabular">
                  {index + 1}
                </span>
                <span
                  aria-hidden="true"
                  className="h-4 w-0.5 rounded-full"
                  style={{ background: teamColor(player.team) }}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{player.name}</span>
                <span className="text-sm font-semibold tabular">{player.kills}</span>
                <span className="w-16 text-right text-xs text-[var(--color-ink-secondary)] tabular">
                  {formatMetric(player.adr, byKey.adr)} ADR
                </span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel title="Most damage per round">
          <ol className="divide-y divide-[var(--color-line)]">
            {topAdr.map((player, index) => (
              <li key={player.player_key} className="flex items-center gap-3 px-4 py-2.5">
                <span className="w-4 text-xs text-[var(--color-ink-muted)] tabular">
                  {index + 1}
                </span>
                <span
                  aria-hidden="true"
                  className="h-4 w-0.5 rounded-full"
                  style={{ background: teamColor(player.team) }}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{player.name}</span>
                <span className="text-sm font-semibold tabular">
                  {formatMetric(player.adr, byKey.adr)}
                </span>
                <span className="w-16 text-right text-xs text-[var(--color-ink-secondary)] tabular">
                  {formatMetric(player.kast, byKey.kast)} KAST
                </span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <Panel title="Match context" subtitle="How this report was produced">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-4 text-xs sm:grid-cols-4">
          <Meta label="Parser" value={`${match.parser_name ?? '—'} ${match.parser_version ?? ''}`} />
          <Meta
            label="Tick rate"
            value={match.tick_rate ? `${match.tick_rate}` : '—'}
            hint={
              match.tick_rate_source === 'fallback'
                ? 'assumed — the demo did not report playback timing, so trade timing is approximate'
                : 'from the demo header'
            }
          />
          <Meta label="Rosters from" value={match.roster_source ?? '—'} />
          <Meta
            label="Processing"
            value={match.parse_seconds ? `${match.parse_seconds.toFixed(2)}s` : '—'}
            hint={match.peak_rss_mb ? `peak ${match.peak_rss_mb} MB` : undefined}
          />
          <Meta label="Demo format" value={match.demo_version_name ?? '—'} />
          <Meta label="Server" value={match.server_name ?? '—'} wide />
        </dl>
      </Panel>

      {rounds.some((round) => round.is_knife_round) && (
        <p className="text-xs text-[var(--color-ink-secondary)]">
          This match contains a knife round, which is excluded from every statistic and
          from the round count used as a denominator.
        </p>
      )}

      <LastRoundNote rounds={scored} match={match} />
    </div>
  )
}

function TeamScore({ match, team }: { match: MatchDetail; team: 'A' | 'B' }) {
  const score = team === 'A' ? match.team_a_score : match.team_b_score
  const won = match.winner_team === team
  return (
    <div className="text-center">
      <div
        className="text-3xl font-bold tabular"
        style={{ color: won ? teamColor(team) : 'var(--color-ink-secondary)' }}
      >
        {score ?? '—'}
      </div>
      <div className="mt-0.5 flex items-center justify-center gap-1.5">
        <span
          aria-hidden="true"
          className="inline-block size-2 rounded-sm"
          style={{ background: teamColor(team) }}
        />
        <span className="text-xs text-[var(--color-ink-secondary)]">{teamName(team, match)}</span>
      </div>
      {won && (
        <Badge tone="good" className="mt-1">
          Winner
        </Badge>
      )}
    </div>
  )
}

function Meta({
  label,
  value,
  hint,
  wide,
}: {
  label: string
  value: string
  hint?: string
  wide?: boolean
}) {
  const body = (
    <div className={wide ? 'col-span-2 min-w-0' : 'min-w-0'}>
      <dt className="text-[0.6875rem] uppercase tracking-wide text-[var(--color-ink-secondary)]">
        {label}
      </dt>
      <dd className="mt-0.5 truncate text-[var(--color-ink)]">{value || '—'}</dd>
    </div>
  )
  return hint ? <Tooltip content={hint}>{body}</Tooltip> : body
}

function LastRoundNote({ rounds, match }: { rounds: Round[]; match: MatchDetail }) {
  const last = rounds[rounds.length - 1]
  if (!last) return null
  return (
    <p className="text-xs text-[var(--color-ink-secondary)]">
      Final round won by {teamName(last.winner_team, match)} ·{' '}
      {formatRoundReason(last.reason_name)}
    </p>
  )
}
