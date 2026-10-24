/**
 * Kill and death positions plotted on the map's radar image.
 *
 * The honesty constraints on this view are stricter than on the tables, because a
 * picture is persuasive:
 *
 * - If the server has no radar image or no coordinate transform for the map, the view
 *   says so and draws nothing. It never falls back to a generic grid, which would put
 *   real coordinates on an invented map.
 * - Marks are the individual positions, not a smoothed density surface. A blurred
 *   heatmap over 78 kills would imply a confidence the sample does not support.
 * - Multi-level maps (Nuke, Vertigo) are split by the published altitude bands, and a
 *   position outside every band is counted as unplaceable rather than drawn on the
 *   wrong floor.
 */

import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useApi } from '../../hooks/useApi'
import type { MatchDetail, MatchEvent, PlayerStats, Side } from '../../api/types'
import { EmptyState, ErrorState, LoadingState, Panel } from '../ui/primitives'
import { levelForAltitude, worldToFraction } from '../../lib/radar'
import { formatMapName, formatWeapon } from '../../lib/format'

type Marker = 'deaths' | 'kills'

interface Plotted {
  key: number
  x: number
  y: number
  side: Side | null
  label: string
  detail: string
  level: string | null
}

interface Props {
  match: MatchDetail
  players: PlayerStats[]
}

export function MapTab({ match, players }: Props) {
  const [marker, setMarker] = useState<Marker>('deaths')
  const [playerKey, setPlayerKey] = useState('')
  const [level, setLevel] = useState<string | null>(null)
  const [hovered, setHovered] = useState<Plotted | null>(null)

  const mapInfo = useApi(
    () => api.getMapInfo(match.map_name ?? ''),
    [match.map_name],
    { enabled: Boolean(match.map_name) },
  )
  const kills = useApi(
    () => api.getEvents(match.id, { event_type: 'kill', limit: 200, sort: 'seq' }),
    [match.id],
  )

  const info = mapInfo.data
  const activeLevel = level ?? info?.levels[0]?.id ?? null

  const { points, unplaceable } = useMemo(() => {
    if (!info?.available || !kills.data) return { points: [] as Plotted[], unplaceable: 0 }
    const result: Plotted[] = []
    let skipped = 0
    for (const event of kills.data.items) {
      if (playerKey) {
        const involves =
          marker === 'deaths' ? event.victim_key === playerKey : event.actor_key === playerKey
        if (!involves) continue
      }
      const [wx, wy, wz, side, label] =
        marker === 'deaths'
          ? [event.victim_x, event.victim_y, event.victim_z, event.victim_side, event.victim_name]
          : [event.actor_x, event.actor_y, event.actor_z, event.actor_side, event.actor_name]
      if (wx === null || wy === null) {
        skipped += 1
        continue
      }
      const fraction = worldToFraction(wx as number, wy as number, info)
      if (!fraction) {
        skipped += 1
        continue
      }
      const pointLevel = levelForAltitude(wz as number | null, info)
      if (info.levels.length > 1 && pointLevel === null) {
        skipped += 1
        continue
      }
      result.push({
        key: event.seq,
        x: fraction.x,
        y: fraction.y,
        side: side as Side | null,
        label: (label as string | null) ?? 'unknown',
        detail: describe(event, marker),
        level: pointLevel,
      })
    }
    return { points: result, unplaceable: skipped }
  }, [info, kills.data, marker, playerKey])

  const visible = useMemo(
    () =>
      info && info.levels.length > 1
        ? points.filter((point) => point.level === activeLevel)
        : points,
    [points, info, activeLevel],
  )

  if (!match.map_name) {
    return (
      <Panel>
        <EmptyState
          title="No map recorded"
          description="The demo did not report a map name, so positions cannot be placed."
        />
      </Panel>
    )
  }

  return (
    <Panel
      title="Positions"
      subtitle={`${formatMapName(match.map_name)} · ${visible.length} plotted`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded border border-[var(--color-line-strong)] p-0.5">
            {(['deaths', 'kills'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setMarker(value)}
                aria-pressed={marker === value}
                className={`rounded px-2 py-0.5 text-[0.6875rem] capitalize transition ${
                  marker === value
                    ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                    : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                }`}
              >
                {value === 'deaths' ? 'Death positions' : 'Killer positions'}
              </button>
            ))}
          </div>
          <select
            value={playerKey}
            onChange={(event) => setPlayerKey(event.target.value)}
            aria-label="Filter by player"
            className="max-w-[10rem] rounded border border-[var(--color-line-strong)] bg-[var(--color-base)] px-1.5 py-1 text-xs"
          >
            <option value="">All players</option>
            {players.map((player) => (
              <option key={player.player_key} value={player.player_key}>
                {player.name}
              </option>
            ))}
          </select>
          {info && info.levels.length > 1 && (
            <div className="flex rounded border border-[var(--color-line-strong)] p-0.5">
              {info.levels.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setLevel(item.id)}
                  aria-pressed={activeLevel === item.id}
                  className={`rounded px-2 py-0.5 text-[0.6875rem] capitalize transition ${
                    activeLevel === item.id
                      ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                      : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                  }`}
                >
                  {item.id === 'default' ? 'Upper' : 'Lower'}
                </button>
              ))}
            </div>
          )}
        </div>
      }
    >
      {mapInfo.loading || kills.loading ? (
        <LoadingState label="Loading map…" />
      ) : mapInfo.error ? (
        <ErrorState
          message={mapInfo.error.message}
          code={mapInfo.error.code}
          onRetry={mapInfo.reload}
        />
      ) : !info || !info.available ? (
        <EmptyState
          title="Map assets unavailable"
          description={
            <>
              {info?.reason ??
                `No radar image is available for ${match.map_name}.`}{' '}
              Positions are not drawn without a verified coordinate transform, because
              plotting them on a stand-in map would be misleading. Every other tab is
              unaffected.
            </>
          }
        />
      ) : (
        <div className="px-4 pb-4 pt-3">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
            <div className="relative aspect-square w-full max-w-[44rem] flex-1 overflow-hidden rounded border border-[var(--color-line)] bg-black">
              <img
                src={info.levels.find((item) => item.id === activeLevel)?.radar_url ?? ''}
                alt={`${formatMapName(match.map_name)} radar`}
                className="absolute inset-0 size-full object-contain opacity-95"
                draggable={false}
              />
              <svg
                viewBox="0 0 1 1"
                className="absolute inset-0 size-full"
                role="img"
                aria-label={`${visible.length} ${marker} plotted on ${formatMapName(match.map_name)}`}
              >
                {visible.map((point) => (
                  <g key={point.key}>
                    {/* A surface-coloured ring keeps overlapping marks separable. */}
                    <circle
                      cx={point.x}
                      cy={point.y}
                      r={0.011}
                      fill="none"
                      stroke="#0d0f12"
                      strokeWidth={0.005}
                      opacity={0.9}
                    />
                    <circle
                      cx={point.x}
                      cy={point.y}
                      r={0.0095}
                      fill={point.side === 'CT' ? '#3987e5' : point.side === 'T' ? '#c98500' : '#6b7280'}
                      fillOpacity={0.85}
                      onMouseEnter={() => setHovered(point)}
                      onMouseLeave={() => setHovered(null)}
                      style={{ cursor: 'pointer' }}
                    />
                  </g>
                ))}
              </svg>
              {hovered && (
                <div className="pointer-events-none absolute left-2 top-2 rounded border border-[var(--color-line-strong)] bg-[var(--color-surface-raised)]/95 px-2 py-1.5 text-xs shadow-lg">
                  <div className="font-medium">{hovered.label}</div>
                  <div className="text-[var(--color-ink-secondary)]">{hovered.detail}</div>
                </div>
              )}
            </div>

            <div className="shrink-0 lg:w-60">
              {/* Legend: two series, so it is always present, and the labels name the
                  sides rather than relying on colour. */}
              <div className="mb-3 space-y-1.5 text-xs">
                {(
                  [
                    { side: 'CT' as Side, colour: '#3987e5', label: 'Counter-Terrorists' },
                    { side: 'T' as Side, colour: '#c98500', label: 'Terrorists' },
                  ]
                ).map((series) => (
                  <div key={series.side} className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="inline-block size-2.5 rounded-full"
                      style={{ background: series.colour, outline: '1.5px solid #0d0f12' }}
                    />
                    <span className="text-[var(--color-ink-secondary)]">{series.label}</span>
                    <span className="ml-auto font-semibold tabular">
                      {visible.filter((point) => point.side === series.side).length}
                    </span>
                  </div>
                ))}
              </div>

              <dl className="space-y-1 border-t border-[var(--color-line)] pt-2.5 text-[0.6875rem] text-[var(--color-ink-muted)]">
                <div className="flex justify-between gap-2">
                  <dt>Radar</dt>
                  <dd className="tabular">
                    {info.image_width}×{info.image_height}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>Scale</dt>
                  <dd className="tabular">{info.scale} units/px</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>Origin</dt>
                  <dd className="tabular">
                    {info.pos_x}, {info.pos_y}
                  </dd>
                </div>
                {unplaceable > 0 && (
                  <div className="flex justify-between gap-2 text-[var(--color-warn)]">
                    <dt>Unplaceable</dt>
                    <dd className="tabular" title="No coordinates, or outside every altitude band">
                      {unplaceable}
                    </dd>
                  </div>
                )}
              </dl>

              <p className="mt-3 text-[0.6875rem] leading-relaxed text-[var(--color-ink-muted)]">
                Each mark is one recorded position, not a smoothed density — a match
                contains too few kills for a density surface to mean anything.
              </p>
            </div>
          </div>
        </div>
      )}
    </Panel>
  )
}

function describe(event: MatchEvent, marker: Marker): string {
  const weapon = formatWeapon(event.weapon)
  if (marker === 'deaths') {
    return `Round ${event.round_num} · killed by ${event.actor_name ?? 'world'} (${weapon})`
  }
  return `Round ${event.round_num} · killed ${event.victim_name ?? '—'} (${weapon})`
}
