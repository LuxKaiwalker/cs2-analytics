/** The landing page: add a match, then pick one to open. */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import type { MatchStatus, MatchSummary } from '../api/types'
import { UploadPanel } from '../components/UploadPanel'
import { StatusBadge } from '../components/StatusBadge'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
} from '../components/ui/primitives'
import { formatBytes, formatMapName, formatRelative } from '../lib/format'
import { teamColor, teamName } from '../lib/sides'

const FILTERS: { label: string; value: MatchStatus | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Completed', value: 'completed' },
  { label: 'Processing', value: 'processing' },
  { label: 'Failed', value: 'failed' },
]

/** Poll the list while anything is still being worked on, and stop once it settles. */
const ACTIVE = new Set<MatchStatus>(['uploaded', 'queued', 'processing'])

export function MatchLibraryPage() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<MatchStatus | 'all'>('all')
  const [tick, setTick] = useState(0)

  const { data, loading, error, reload } = useApi(
    () => api.listMatches(filter === 'all' ? { limit: 100 } : { status: filter, limit: 100 }),
    [filter, tick],
  )

  const hasActive = (data?.items ?? []).some((match) => ACTIVE.has(match.status))
  useEffect(() => {
    if (!hasActive) return
    const timer = window.setInterval(() => setTick((value) => value + 1), 2000)
    return () => window.clearInterval(timer)
  }, [hasActive])

  const remove = useCallback(
    async (id: string) => {
      await api.deleteMatch(id)
      reload()
    },
    [reload],
  )

  return (
    <div className="flex flex-col gap-5">
      <UploadPanel onAccepted={(id) => navigate(`/matches/${id}`)} />

      <Panel
        title="Matches"
        subtitle={data ? `${data.total} stored` : undefined}
        actions={
          <div className="flex items-center gap-1" role="group" aria-label="Filter by status">
            {FILTERS.map((option) => (
              <button
                key={option.value}
                onClick={() => setFilter(option.value)}
                aria-pressed={filter === option.value}
                className={`rounded px-2 py-1 text-xs transition ${
                  filter === option.value
                    ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                    : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      >
        {loading && !data ? (
          <LoadingState label="Loading matches…" />
        ) : error ? (
          <ErrorState message={error.message} code={error.code} onRetry={reload} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title={filter === 'all' ? 'No matches yet' : `No ${filter} matches`}
            description={
              filter === 'all'
                ? 'Upload a CS2 demo above to get your first match report. Nothing leaves this machine.'
                : 'Try a different filter.'
            }
          />
        ) : (
          <ul className="divide-y divide-[var(--color-line)]">
            {data.items.map((match) => (
              <MatchRow
                key={match.id}
                match={match}
                onOpen={() => navigate(`/matches/${match.id}`)}
                onDelete={() => void remove(match.id)}
              />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}

function MatchRow({
  match,
  onOpen,
  onDelete,
}: {
  match: MatchSummary
  onOpen: () => void
  onDelete: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const scored = match.team_a_score !== null && match.team_b_score !== null

  return (
    <li className="group flex items-center gap-3 px-4 py-3 transition hover:bg-[var(--color-surface-hover)]">
      <button
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
        aria-label={`Open ${formatMapName(match.map_name)} match`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-[var(--color-ink)]">
              {formatMapName(match.map_name)}
            </span>
            <StatusBadge status={match.status} stage={match.stage} />
            {match.has_overtime && <Badge tone="warn">OT</Badge>}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[0.6875rem] text-[var(--color-ink-muted)]">
            <span className="truncate">{match.original_filename ?? 'demo'}</span>
            <span aria-hidden="true">·</span>
            <span>{formatBytes(match.size_bytes)}</span>
            <span aria-hidden="true">·</span>
            <span title={match.uploaded_at}>uploaded {formatRelative(match.uploaded_at)}</span>
          </div>
        </div>

        {scored ? (
          <div className="flex shrink-0 items-center gap-2 text-sm font-semibold tabular">
            <span
              style={{ color: match.winner_team === 'A' ? teamColor('A') : 'var(--color-ink-secondary)' }}
              title={teamName('A', match)}
            >
              {match.team_a_score}
            </span>
            <span className="text-[var(--color-ink-muted)]">:</span>
            <span
              style={{ color: match.winner_team === 'B' ? teamColor('B') : 'var(--color-ink-secondary)' }}
              title={teamName('B', match)}
            >
              {match.team_b_score}
            </span>
          </div>
        ) : match.status === 'failed' ? (
          <span className="shrink-0 max-w-[16rem] truncate text-xs text-[var(--color-bad)]">
            {match.error_message ?? 'Processing failed'}
          </span>
        ) : null}
      </button>

      {confirming ? (
        <span className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-[var(--color-ink-secondary)]">Delete?</span>
          <Button variant="danger" size="sm" onClick={onDelete}>
            Yes
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
            No
          </Button>
        </span>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
          onClick={() => setConfirming(true)}
          ariaLabel={`Delete ${formatMapName(match.map_name)} match`}
        >
          Delete
        </Button>
      )}
    </li>
  )
}
