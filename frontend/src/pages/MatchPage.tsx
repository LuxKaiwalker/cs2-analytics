/**
 * The match dashboard.
 *
 * Routes on processing status before showing anything analytical: a queued match gets a
 * progress view, a failed one gets the reason and a way out, and — the case that is easy
 * to get wrong — a match that parsed successfully but holds no rounds gets its own
 * message rather than looking like a failure or like an empty table.
 */

import { lazy, Suspense, useEffect, useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useMatchPolling } from '../hooks/useMatchPolling'
import type { MatchDetail } from '../api/types'
import { StatusBadge } from '../components/StatusBadge'
import { STAGE_ORDER, stageLabel } from '../lib/stages'
/*
 * Tabs load on demand. The charting library alone is most of the bundle, and a user who
 * only wants the scoreboard should not download the map and chart code to see it.
 */
const OverviewTab = lazy(() =>
  import('../components/tabs/OverviewTab').then((m) => ({ default: m.OverviewTab })),
)
const PlayersTab = lazy(() =>
  import('../components/tabs/PlayersTab').then((m) => ({ default: m.PlayersTab })),
)
const RoundsTab = lazy(() =>
  import('../components/tabs/RoundsTab').then((m) => ({ default: m.RoundsTab })),
)
const EventsTab = lazy(() =>
  import('../components/tabs/EventsTab').then((m) => ({ default: m.EventsTab })),
)
const MapTab = lazy(() =>
  import('../components/tabs/MapTab').then((m) => ({ default: m.MapTab })),
)
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
  Spinner,
} from '../components/ui/primitives'
import { formatBytes, formatMapName, formatRelative } from '../lib/format'

const TAB_IDS = ['overview', 'players', 'rounds', 'events', 'map'] as const
type TabId = (typeof TAB_IDS)[number]

export function MatchPage() {
  const { matchId } = useParams<{ matchId: string }>()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { match, loading, error, isPolling, reload } = useMatchPolling(matchId)

  const requested = params.get('tab')
  const tab: TabId = TAB_IDS.includes(requested as TabId) ? (requested as TabId) : 'overview'
  const [selectedRound, setSelectedRound] = useState<number | null>(null)

  if (loading && !match) return <LoadingState label="Loading match…" />
  if (error && !match) {
    return (
      <ErrorState
        title={error.status === 404 ? 'Match not found' : 'Could not load the match'}
        message={
          error.status === 404
            ? 'It may have been deleted. The match library has the current list.'
            : error.message
        }
        code={error.code}
        onRetry={error.status === 404 ? undefined : reload}
      />
    )
  }
  if (!match) return null

  return (
    <div className="flex flex-col gap-4">
      <MatchHeader
        match={match}
        isPolling={isPolling}
        onDelete={async () => {
          await api.deleteMatch(match.id)
          navigate('/')
        }}
      />

      {match.status === 'failed' ? (
        <FailureView match={match} onDelete={async () => {
          await api.deleteMatch(match.id)
          navigate('/')
        }} />
      ) : match.status === 'cancelled' ? (
        <Panel>
          <EmptyState
            title="Processing was cancelled"
            description="This match was cancelled before it finished. Upload the demo again to retry."
          />
        </Panel>
      ) : match.status !== 'completed' ? (
        <ProcessingView match={match} />
      ) : (
        <CompletedView
          match={match}
          tab={tab}
          onTabChange={(value) => {
            const next = new URLSearchParams(params)
            next.set('tab', value)
            setParams(next, { replace: true })
          }}
          selectedRound={selectedRound}
          onSelectRound={(roundNum) => {
            setSelectedRound(roundNum)
            const next = new URLSearchParams(params)
            next.set('tab', 'rounds')
            setParams(next, { replace: true })
          }}
        />
      )}
    </div>
  )
}

function MatchHeader({
  match,
  isPolling,
  onDelete,
}: {
  match: MatchDetail
  isPolling: boolean
  onDelete: () => Promise<void>
}) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="flex flex-wrap items-center gap-3">
      <h1 className="text-lg font-semibold tracking-tight">
        {formatMapName(match.map_name)}
      </h1>
      <StatusBadge status={match.status} stage={match.stage} />
      {match.has_overtime && <Badge tone="warn">Overtime</Badge>}
      {isPolling && <Spinner />}
      <span className="text-xs text-[var(--color-ink-muted)]">
        {match.original_filename} · {formatBytes(match.size_bytes)} · uploaded{' '}
        {formatRelative(match.uploaded_at)}
      </span>
      <div className="ml-auto">
        {confirming ? (
          <span className="flex items-center gap-1.5">
            <span className="text-xs text-[var(--color-ink-secondary)]">
              Delete this match and its demo?
            </span>
            <Button variant="danger" size="sm" onClick={() => void onDelete()}>
              Delete
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            Delete match
          </Button>
        )}
      </div>
    </div>
  )
}

function ProcessingView({ match }: { match: MatchDetail }) {
  const [elapsed, setElapsed] = useState(0)

  // Elapsed time rather than a percentage: the parser reports no progress, so a
  // progress bar would be a fabrication. Elapsed time is true and still informative.
  useEffect(() => {
    const started = match.stage_started_at ? new Date(match.stage_started_at).getTime() : Date.now()
    const update = () => setElapsed(Math.max(0, (Date.now() - started) / 1000))
    update()
    const timer = window.setInterval(update, 500)
    return () => window.clearInterval(timer)
  }, [match.stage_started_at, match.stage])

  const currentIndex = match.stage ? STAGE_ORDER.indexOf(match.stage) : -1

  return (
    <Panel title="Processing" subtitle="The demo is being parsed on this machine.">
      <div className="px-4 py-6">
        <div className="mx-auto max-w-lg">
          <div className="mb-5 flex items-center gap-3">
            <Spinner />
            <div>
              <div className="text-sm font-medium">{stageLabel(match.stage)}</div>
              <div className="text-xs text-[var(--color-ink-muted)] tabular">
                {elapsed.toFixed(0)}s in this stage
              </div>
            </div>
          </div>

          <ol className="space-y-2">
            {STAGE_ORDER.map((stage, index) => {
              const state =
                currentIndex < 0
                  ? 'pending'
                  : index < currentIndex
                    ? 'done'
                    : index === currentIndex
                      ? 'active'
                      : 'pending'
              return (
                <li key={stage} className="flex items-center gap-2.5 text-xs">
                  <span
                    aria-hidden="true"
                    className="flex size-4 items-center justify-center rounded-full border text-[0.5625rem]"
                    style={{
                      borderColor:
                        state === 'pending' ? 'var(--color-line-strong)' : 'var(--color-team-a)',
                      background: state === 'done' ? 'var(--color-team-a)' : 'transparent',
                      color: state === 'done' ? '#fff' : 'var(--color-team-a)',
                    }}
                  >
                    {state === 'done' ? '✓' : ''}
                  </span>
                  <span
                    className={
                      state === 'pending'
                        ? 'text-[var(--color-ink-muted)]'
                        : 'text-[var(--color-ink)]'
                    }
                  >
                    {stageLabel(stage)}
                  </span>
                  {state === 'active' && (
                    <span className="text-[var(--color-ink-muted)]">· running</span>
                  )}
                </li>
              )
            })}
          </ol>

          <p className="mt-5 text-xs leading-relaxed text-[var(--color-ink-secondary)]">
            This page refreshes itself and will show the report as soon as parsing
            finishes. Parsing an 85 MB demo typically takes a couple of seconds; larger
            league demos take longer.
          </p>
        </div>
      </div>
    </Panel>
  )
}

function FailureView({
  match,
  onDelete,
}: {
  match: MatchDetail
  onDelete: () => Promise<void>
}) {
  return (
    <Panel title="Processing failed">
      <div className="px-4 py-6">
        <div className="mx-auto max-w-lg text-center">
          <p className="text-sm font-medium text-[var(--color-bad)]">
            {match.error_message ?? 'The demo could not be processed.'}
          </p>
          {match.error_code && (
            <code className="mt-1 block text-[0.6875rem] text-[var(--color-ink-muted)]">
              {match.error_code}
            </code>
          )}
          <p className="mt-4 text-xs leading-relaxed text-[var(--color-ink-secondary)]">
            {HINTS[match.error_code ?? ''] ??
              'The server log has the full diagnostic detail for this failure.'}
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <Button variant="danger" size="sm" onClick={() => void onDelete()}>
              Delete this match
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  )
}

/** Each hint says what the user can actually do about that specific failure. */
const HINTS: Record<string, string> = {
  invalid_demo:
    'The file does not begin with the CS2 demo signature. Check it is a .dem recorded by Counter-Strike 2 and not renamed or truncated.',
  source1_demo:
    'This is a CS:GO (Source 1) demo. Only Counter-Strike 2 demos can be parsed.',
  compressed_demo:
    'Matchmaking demos download compressed. Extract the .dem file and upload that.',
  unsupported_demo:
    'The parser recognised the file but cannot handle this variant. It may be a partial recording or an unsupported split demo.',
  empty_demo:
    'The demo parsed but contains no completed rounds — usually a warmup-only or aborted recording.',
  demo_missing: 'The stored demo file is no longer on disk. Upload it again.',
  out_of_memory:
    'The demo needed more memory than the worker is allowed. Raise CS2A_WORKER_MEM_LIMIT_MB and upload again.',
  timeout:
    'Parsing exceeded the time limit. Raise CS2A_PARSE_TIMEOUT_S for very long demos.',
  worker_crashed:
    'The parser exited unexpectedly on this file, which usually means the demo is corrupt.',
  abandoned_after_restart:
    'Processing was interrupted repeatedly. Delete the match and upload the demo again.',
}

function CompletedView({
  match,
  tab,
  onTabChange,
  selectedRound,
  onSelectRound,
}: {
  match: MatchDetail
  tab: TabId
  onTabChange: (tab: TabId) => void
  selectedRound: number | null
  onSelectRound: (roundNum: number) => void
}) {
  const players = useApi(() => api.getPlayers(match.id), [match.id])
  const rounds = useApi(() => api.getRounds(match.id), [match.id])

  if (players.loading || rounds.loading) return <LoadingState label="Loading analytics…" />
  if (players.error || rounds.error) {
    const failure = players.error ?? rounds.error
    return (
      <ErrorState
        message={failure?.message}
        code={failure?.code}
        onRetry={() => {
          players.reload()
          rounds.reload()
        }}
      />
    )
  }

  const playerRows = players.data ?? []
  const roundRows = rounds.data ?? []

  // A successful parse with nothing in it is its own state — not a failure, and not an
  // empty table the user has to interpret.
  if (roundRows.length === 0 && playerRows.length === 0) {
    return (
      <Panel>
        <EmptyState
          title="Parsed successfully, but this demo contains no match data"
          description={
            <>
              The file was a valid CS2 demo and was read without error, but it has no
              completed rounds or players — typically a warmup-only recording, or a demo
              that was cut before the match began. This is not a parsing failure.
            </>
          }
        />
      </Panel>
    )
  }

  const degraded = Object.entries(match.availability).filter(
    ([, entry]) => entry.state !== 'available',
  )

  return (
    <>
      {degraded.length > 0 && (
        <div className="rounded border border-[var(--color-warn)]/35 bg-[var(--color-warn)]/8 px-3 py-2">
          <p className="text-xs font-medium text-[var(--color-warn)]">
            Some source data is missing from this demo
          </p>
          <ul className="mt-1 space-y-0.5 text-[0.6875rem] text-[var(--color-ink-secondary)]">
            {degraded.map(([name, entry]) => (
              <li key={name}>
                <code>{name}</code>: {entry.state}
                {entry.reason ? ` — ${entry.reason}` : ''}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[0.6875rem] text-[var(--color-ink-muted)]">
            Metrics derived from it are shown as “—”, never as zero.
          </p>
        </div>
      )}

      {match.anomalies.length > 0 && (
        <div className="rounded border border-[var(--color-line-strong)] bg-[var(--color-surface)] px-3 py-2">
          <p className="text-xs font-medium text-[var(--color-ink)]">Notes on this demo</p>
          <ul className="mt-1 space-y-0.5 text-[0.6875rem] text-[var(--color-ink-secondary)]">
            {match.anomalies.map((anomaly) => (
              <li key={anomaly.code}>{anomaly.message}</li>
            ))}
          </ul>
        </div>
      )}

      <Tabs.Root value={tab} onValueChange={(value) => onTabChange(value as TabId)}>
        <Tabs.List
          className="mb-4 flex gap-1 border-b border-[var(--color-line)]"
          aria-label="Match analysis sections"
        >
          {TAB_IDS.map((id) => (
            <Tabs.Trigger
              key={id}
              value={id}
              className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm capitalize text-[var(--color-ink-secondary)] transition hover:text-[var(--color-ink)] data-[state=active]:border-[var(--color-team-a)] data-[state=active]:text-[var(--color-ink)]"
            >
              {id}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Suspense fallback={<LoadingState label="Loading view…" />}>
          <Tabs.Content value="overview">
            <OverviewTab
              match={match}
              players={playerRows}
              rounds={roundRows}
              onSelectRound={onSelectRound}
            />
          </Tabs.Content>
          <Tabs.Content value="players">
            <PlayersTab match={match} players={playerRows} />
          </Tabs.Content>
          <Tabs.Content value="rounds">
            <RoundsTab
              match={match}
              rounds={roundRows}
              selectedRound={selectedRound}
              onSelectRound={onSelectRound}
            />
          </Tabs.Content>
          <Tabs.Content value="events">
            <EventsTab match={match} players={playerRows} roundCount={roundRows.length} />
          </Tabs.Content>
          <Tabs.Content value="map">
            <MapTab match={match} players={playerRows} />
          </Tabs.Content>
        </Suspense>
      </Tabs.Root>
    </>
  )
}
