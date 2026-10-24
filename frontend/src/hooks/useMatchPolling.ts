/**
 * Poll a match until it reaches a terminal state.
 *
 * Written as an async loop rather than a self-rescheduling callback: the loop reads in
 * the order it happens, needs no reference to itself, and cancels by flipping one flag.
 *
 * Three behaviours a plain interval would get wrong:
 *
 * - **It stops.** Polling ends as soon as the status is terminal; a finished match is
 *   never re-fetched.
 * - **It backs off.** The delay grows from 1s to 5s, so a long parse does not generate
 *   hundreds of requests.
 * - **It pauses when hidden.** A backgrounded tab waits instead of accumulating work
 *   nobody is looking at, and resumes promptly when the tab is shown again.
 */

import { useCallback, useEffect, useReducer } from 'react'
import { ApiError, api } from '../api/client'
import type { MatchDetail } from '../api/types'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const INITIAL_INTERVAL_MS = 1000
const MAX_INTERVAL_MS = 5000
const BACKOFF = 1.4

export interface MatchPollingState {
  match: MatchDetail | null
  loading: boolean
  error: ApiError | null
  isPolling: boolean
  reload: () => void
}

interface Stored {
  key: string
  match: MatchDetail | null
  error: ApiError | null
}

type Action =
  | { type: 'resolved'; key: string; match: MatchDetail }
  | { type: 'rejected'; key: string; error: ApiError }

function reducer(state: Stored, action: Action): Stored {
  switch (action.type) {
    case 'resolved':
      return { key: action.key, match: action.match, error: null }
    case 'rejected':
      return { key: action.key, match: state.match, error: action.error }
  }
}

/** Resolve after `ms`, or immediately if cancelled. */
function sleep(ms: number, cancelled: () => boolean): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms)
    const stop = window.setInterval(() => {
      if (cancelled()) {
        window.clearTimeout(timer)
        window.clearInterval(stop)
        resolve()
      }
    }, 100)
    window.setTimeout(() => window.clearInterval(stop), ms + 50)
  })
}

/** Resolve when the document becomes visible again. */
function whenVisible(cancelled: () => boolean): Promise<void> {
  if (!document.hidden) return Promise.resolve()
  return new Promise((resolve) => {
    const check = () => {
      if (!document.hidden || cancelled()) {
        document.removeEventListener('visibilitychange', check)
        resolve()
      }
    }
    document.addEventListener('visibilitychange', check)
  })
}

export function useMatchPolling(matchId: string | undefined): MatchPollingState {
  const [nonce, bump] = useReducer((value: number) => value + 1, 0)
  const key = `${nonce}:${matchId ?? ''}`
  const [state, dispatch] = useReducer(reducer, { key: '', match: null, error: null })

  useEffect(() => {
    if (!matchId) return
    let active = true
    const cancelled = () => !active
    let delay = INITIAL_INTERVAL_MS

    const run = async () => {
      while (active) {
        try {
          const detail = await api.getMatch(matchId)
          if (!active) return
          dispatch({ type: 'resolved', key, match: detail })
          if (TERMINAL.has(detail.status)) return
        } catch (caught) {
          if (!active) return
          dispatch({
            type: 'rejected',
            key,
            error:
              caught instanceof ApiError
                ? caught
                : new ApiError('unexpected_error', 'Could not load the match.', 0),
          })
          return
        }
        await sleep(delay, cancelled)
        await whenVisible(cancelled)
        delay = Math.min(delay * BACKOFF, MAX_INTERVAL_MS)
      }
    }
    void run()

    return () => {
      active = false
    }
  }, [key, matchId])

  const reload = useCallback(() => bump(), [bump])
  const stale = state.key !== key
  const match = stale ? null : state.match

  return {
    match,
    loading: Boolean(matchId) && stale,
    error: stale ? null : state.error,
    isPolling: match !== null && !TERMINAL.has(match.status),
    reload,
  }
}
