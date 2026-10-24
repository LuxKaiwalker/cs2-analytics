/**
 * One cell per round, coloured by the winning team.
 *
 * Not a chart so much as a legible index of the match: it shows the shape of the game
 * (streaks, the halftime turn) and doubles as the round selector. Colour is reinforced
 * by the round number and a tooltip, so it never carries meaning alone.
 */

import type { MatchDetail, Round } from '../../api/types'
import { Tooltip } from '../ui/primitives'
import { formatBuyType, formatRoundReason } from '../../lib/format'
import { teamColor, teamName } from '../../lib/sides'

interface Props {
  rounds: Round[]
  match: MatchDetail
  selected?: number | null
  onSelect?: (roundNum: number) => void
}

export function RoundStrip({ rounds, match, selected, onSelect }: Props) {
  return (
    <div className="flex flex-wrap gap-1" role="list" aria-label="Rounds">
      {rounds.map((round) => {
        const colour = teamColor(round.winner_team)
        const isSelected = selected === round.round_num
        const ctTeam = round.team_ct
        return (
          <Tooltip
            key={round.round_num}
            content={
              <div className="space-y-0.5">
                <div className="font-medium">
                  Round {round.round_num}
                  {round.is_overtime && ' · overtime'}
                  {round.is_knife_round && ' · knife round'}
                </div>
                <div>
                  Won by {teamName(round.winner_team, match)} ({round.winner_side ?? '—'})
                </div>
                <div className="text-[var(--color-ink-secondary)]">
                  {formatRoundReason(round.reason_name)}
                </div>
                <div className="text-[var(--color-ink-secondary)]">
                  CT {formatBuyType(round.ct_buy_type)} · T {formatBuyType(round.t_buy_type)}
                </div>
                {ctTeam && (
                  <div className="text-[var(--color-ink-muted)]">
                    {teamName(ctTeam, match)} on CT
                  </div>
                )}
              </div>
            }
          >
            <button
              role="listitem"
              onClick={() => onSelect?.(round.round_num)}
              aria-label={`Round ${round.round_num}, won by ${teamName(round.winner_team, match)}`}
              aria-current={isSelected}
              className="relative flex h-7 w-7 items-center justify-center rounded text-[0.625rem] font-semibold tabular transition"
              style={{
                // A 2px surface gap keeps adjacent cells from reading as one block.
                background: `color-mix(in oklab, ${colour} ${isSelected ? '45%' : '22%'}, transparent)`,
                color: isSelected ? 'var(--color-ink)' : 'var(--color-ink-secondary)',
                border: `1px solid color-mix(in oklab, ${colour} ${isSelected ? '90%' : '45%'}, transparent)`,
                cursor: onSelect ? 'pointer' : 'default',
              }}
            >
              {round.round_num}
              {round.is_knife_round && (
                <span
                  aria-hidden="true"
                  className="absolute -top-px right-0.5 text-[0.5rem] text-[var(--color-ink-muted)]"
                >
                  ✕
                </span>
              )}
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}
