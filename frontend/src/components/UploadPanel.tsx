/**
 * The upload and import workflow.
 *
 * Client-side checks here are a courtesy, not a control: the server validates size and
 * content independently. Catching an obviously wrong file before sending hundreds of
 * megabytes is simply kinder than letting the upload finish and then rejecting it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import { Button, Panel } from './ui/primitives'
import { formatBytes } from '../lib/format'

/**
 * Fallback only. The real limit is read from the server, so raising
 * `CS2A_MAX_DEMO_BYTES` takes effect in the UI without a rebuild and the client can
 * never reject a file the server would have accepted.
 */
const FALLBACK_MAX_BYTES = 600 * 1024 * 1024
const MIN_BYTES = 64 * 1024

type Mode = 'file' | 'url'

interface Props {
  onAccepted: (matchId: string) => void
}

export function UploadPanel({ onAccepted }: Props) {
  const [mode, setMode] = useState<Mode>('file')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [maxBytes, setMaxBytes] = useState(FALLBACK_MAX_BYTES)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let active = true
    api
      .health()
      .then((health) => {
        if (active && health.max_demo_bytes > 0) setMaxBytes(health.max_demo_bytes)
      })
      .catch(() => {
        // The fallback is only used to give a friendlier message; the server still
        // enforces the real limit.
      })
    return () => {
      active = false
    }
  }, [])

  const reject = useCallback((code: string, message: string) => {
    setError({ code, message })
    setProgress(null)
    setBusy(false)
  }, [])

  const send = useCallback(
    async (file: File) => {
      setError(null)
      if (!file.name.toLowerCase().endsWith('.dem')) {
        reject(
          'wrong_extension',
          `“${file.name}” is not a .dem file. CS2 demos are saved with a .dem extension.`,
        )
        return
      }
      if (file.size > maxBytes) {
        reject(
          'file_too_large',
          `That demo is ${formatBytes(file.size)}, over the ${formatBytes(maxBytes)} limit.`,
        )
        return
      }
      if (file.size < MIN_BYTES) {
        reject('file_too_small', `That file is only ${formatBytes(file.size)} — too small to be a demo.`)
        return
      }

      setBusy(true)
      setProgress(0)
      abortRef.current = new AbortController()
      try {
        const created = await api.uploadDemo(file, setProgress, abortRef.current.signal)
        setProgress(null)
        setBusy(false)
        onAccepted(created.id)
      } catch (caught) {
        if (caught instanceof ApiError) {
          // A duplicate is not a failure: the match already exists, so go to it.
          const existing = caught.details?.match_id
          if (caught.code === 'duplicate_demo' && typeof existing === 'string') {
            setProgress(null)
            setBusy(false)
            onAccepted(existing)
            return
          }
          reject(caught.code, caught.message)
        } else {
          reject('upload_failed', 'The upload failed unexpectedly.')
        }
      }
    },
    [onAccepted, reject, maxBytes],
  )

  const submitUrl = useCallback(async () => {
    setError(null)
    if (!url.trim()) {
      reject('url_missing', 'Enter the URL of a .dem file.')
      return
    }
    setBusy(true)
    try {
      const created = await api.importDemo(url.trim())
      setUrl('')
      setBusy(false)
      onAccepted(created.id)
    } catch (caught) {
      if (caught instanceof ApiError) {
        const existing = caught.details?.match_id
        if (caught.code === 'duplicate_demo' && typeof existing === 'string') {
          setBusy(false)
          onAccepted(existing)
          return
        }
        reject(caught.code, caught.message)
      } else {
        reject('import_failed', 'The import failed unexpectedly.')
      }
    }
  }, [onAccepted, reject, url])

  return (
    <Panel
      title="Add a match"
      subtitle="Upload a CS2 demo recorded by the game, a matchmaking download, or a league server."
    >
      <div className="px-4 pb-4 pt-3">
        <div
          className="mb-3 inline-flex rounded border border-[var(--color-line-strong)] p-0.5"
          role="tablist"
          aria-label="Upload source"
        >
          {(['file', 'url'] as const).map((value) => (
            <button
              key={value}
              role="tab"
              aria-selected={mode === value}
              onClick={() => {
                setMode(value)
                setError(null)
              }}
              className={`rounded px-3 py-1 text-xs font-medium transition ${
                mode === value
                  ? 'bg-[var(--color-surface-hover)] text-[var(--color-ink)]'
                  : 'text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]'
              }`}
            >
              {value === 'file' ? 'Upload file' : 'Import from URL'}
            </button>
          ))}
        </div>

        {mode === 'file' ? (
          <div
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              const file = event.dataTransfer.files[0]
              if (file) void send(file)
            }}
            className={`rounded border border-dashed px-6 py-8 text-center transition ${
              dragging
                ? 'border-[var(--color-team-a)] bg-[var(--color-team-a)]/5'
                : 'border-[var(--color-line-strong)]'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".dem"
              className="sr-only"
              aria-label="Choose a CS2 demo file"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void send(file)
                event.target.value = ''
              }}
            />
            {busy && progress !== null ? (
              <div className="mx-auto max-w-sm">
                <p className="mb-2 text-sm text-[var(--color-ink)]">
                  Uploading… {Math.round(progress * 100)}%
                </p>
                <div
                  className="h-1.5 overflow-hidden rounded bg-[var(--color-surface-raised)]"
                  role="progressbar"
                  aria-valuenow={Math.round(progress * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="h-full rounded bg-[var(--color-team-a)] transition-[width]"
                    style={{ width: `${progress * 100}%` }}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-3"
                  onClick={() => abortRef.current?.abort()}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <>
                <p className="text-sm text-[var(--color-ink)]">
                  Drop a <code className="text-[var(--color-ink-secondary)]">.dem</code> file here
                </p>
                <p className="mt-1 text-xs text-[var(--color-ink-secondary)]">
                  or{' '}
                  <button
                    onClick={() => inputRef.current?.click()}
                    className="text-[var(--color-team-a)] underline underline-offset-2"
                  >
                    choose a file
                  </button>{' '}
                  · up to {formatBytes(maxBytes)}
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submitUrl()
              }}
              placeholder="https://example.com/match.dem"
              aria-label="Demo URL"
              className="min-w-0 flex-1 rounded border border-[var(--color-line-strong)] bg-[var(--color-base)] px-3 py-1.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-muted)]"
            />
            <Button variant="primary" onClick={() => void submitUrl()} disabled={busy}>
              {busy ? 'Importing…' : 'Import'}
            </Button>
          </div>
        )}

        {mode === 'url' && (
          <p className="mt-2 text-[0.6875rem] leading-relaxed text-[var(--color-ink-muted)]">
            Must be a direct, publicly reachable https link. URLs resolving to private or
            internal addresses are refused.
          </p>
        )}

        {error && (
          <div
            role="alert"
            className="mt-3 rounded border border-[var(--color-bad)]/35 bg-[var(--color-bad)]/8 px-3 py-2"
          >
            <p className="text-xs font-medium text-[var(--color-bad)]">{error.message}</p>
            <code className="text-[0.625rem] text-[var(--color-ink-muted)]">{error.code}</code>
          </div>
        )}
      </div>
    </Panel>
  )
}
