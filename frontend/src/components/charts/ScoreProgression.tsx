/**
 * Cumulative score across the match.
 *
 * Form: change over time, two comparable series on one scale — a step line, because the
 * score changes discretely at round boundaries and interpolating between them would
 * imply fractional rounds.
 *
 * Both series share one y-axis (they are the same measure), there is a legend plus a
 * direct label at each line's end, and colour is keyed to the team rather than to its
 * rank — so the leader's colour does not change when the lead does.
 */

import {
  CartesianGrid,
  Label,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MatchDetail, Round } from '../../api/types'
import { teamName } from '../../lib/sides'

const AXIS = '#6b7280'
const GRID = '#262b33'
const TEAM_A = '#3987e5'
const TEAM_B = '#d95926'

interface Props {
  rounds: Round[]
  match: MatchDetail
}

interface Row {
  round: number
  a: number
  b: number
  winner: string | null
  reason: string | null
}

export function ScoreProgression({ rounds, match }: Props) {
  const nameA = teamName('A', match)
  const nameB = teamName('B', match)

  const data: Row[] = [
    { round: 0, a: 0, b: 0, winner: null, reason: null },
    ...rounds.map((round) => ({
      round: round.round_num,
      a: round.score_a_after,
      b: round.score_b_after,
      winner: round.winner_team,
      reason: round.reason_name,
    })),
  ]

  const last = data[data.length - 1]
  const halftime = rounds.find((round) => round.half_index === 1)?.round_num
  const firstOvertime = rounds.find((round) => round.is_overtime)?.round_num
  const maxScore = Math.max(last?.a ?? 0, last?.b ?? 0)

  return (
    <div>
      {/* Legend: always present for two series, and never colour-alone — each swatch
          sits beside its name in ordinary ink. */}
      <div className="mb-2 flex items-center gap-4 px-1 text-xs">
        {[
          { name: nameA, color: TEAM_A, score: last?.a ?? 0 },
          { name: nameB, color: TEAM_B, score: last?.b ?? 0 },
        ].map((series) => (
          <span key={series.name} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-0.5 w-4 rounded-full"
              style={{ background: series.color }}
            />
            <span className="text-[var(--color-ink-secondary)]">{series.name}</span>
            <span className="font-semibold text-[var(--color-ink)] tabular">{series.score}</span>
          </span>
        ))}
      </div>

      <div className="h-56 w-full" role="img" aria-label={`Score progression: ${nameA} ${last?.a ?? 0}, ${nameB} ${last?.b ?? 0}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 44, bottom: 4, left: -18 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="round"
              stroke={GRID}
              tick={{ fill: AXIS, fontSize: 11 }}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={24}
            />
            <YAxis
              stroke={GRID}
              tick={{ fill: AXIS, fontSize: 11 }}
              tickLine={false}
              allowDecimals={false}
              domain={[0, Math.max(4, maxScore)]}
              width={44}
            />
            {halftime !== undefined && (
              <ReferenceLine x={halftime} stroke={GRID} strokeDasharray="3 3">
                <Label
                  value="halftime"
                  position="insideTopLeft"
                  fill={AXIS}
                  fontSize={10}
                  offset={6}
                />
              </ReferenceLine>
            )}
            {firstOvertime !== undefined && (
              <ReferenceLine x={firstOvertime} stroke={GRID} strokeDasharray="3 3">
                <Label value="OT" position="insideTopLeft" fill={AXIS} fontSize={10} offset={6} />
              </ReferenceLine>
            )}
            <Tooltip
              content={<ScoreTooltip nameA={nameA} nameB={nameB} />}
              cursor={{ stroke: GRID, strokeWidth: 1 }}
            />
            <Line
              type="stepAfter"
              dataKey="a"
              name={nameA}
              stroke={TEAM_A}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#14171c' }}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="b"
              name={nameB}
              stroke={TEAM_B}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#14171c' }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: Row }[]
  nameA: string
  nameB: string
}

function ScoreTooltip({ active, payload, nameA, nameB }: TooltipProps) {
  const row = payload?.[0]?.payload
  if (!active || !row || row.round === 0) return null
  return (
    <div className="rounded border border-[var(--color-line-strong)] bg-[var(--color-surface-raised)] px-2.5 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-[var(--color-ink)]">Round {row.round}</div>
      <div className="flex items-center gap-3 tabular">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block size-2 rounded-sm"
            style={{ background: TEAM_A }}
          />
          <span className="text-[var(--color-ink-secondary)]">{nameA}</span>
          <span className="font-semibold text-[var(--color-ink)]">{row.a}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block size-2 rounded-sm"
            style={{ background: TEAM_B }}
          />
          <span className="text-[var(--color-ink-secondary)]">{nameB}</span>
          <span className="font-semibold text-[var(--color-ink)]">{row.b}</span>
        </span>
      </div>
    </div>
  )
}
