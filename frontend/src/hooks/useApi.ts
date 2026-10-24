/**
 * A small async-data hook: loading, error and data as one explicit state.
 *
 * `loading` is **derived**, not stored. The stored state carries the key it was fetched
 * for, so when the inputs change the previous result is recognised as stale during
 * render rather than by setting state from an effect — which is both a cascading render
 * and the thing React's lint rules rightly object to. Every state transition therefore
 * happens in a promise callback, after the request has actually resolved.
 */

import { useCallback, useEffect, useReducer } from 'react'
import { ApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiError | null
  reload: () => void
}

interface Stored<T> {
  key: string
  data: T | null
  error: ApiError | null
}

type Action<T> =
  | { type: 'resolved'; key: string; data: T }
  | { type: 'rejected'; key: string; error: ApiError }

function reducer<T>(_state: Stored<T>, action: Action<T>): Stored<T> {
  switch (action.type) {
    case 'resolved':
      return { key: action.key, data: action.data, error: null }
    case 'rejected':
      return { key: action.key, data: null, error: action.error }
  }
}

function toApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError('unexpected_error', 'Something went wrong.', 0)
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean } = {},
): AsyncState<T> {
  const enabled = options.enabled ?? true
  const [nonce, bump] = useReducer((value: number) => value + 1, 0)
  const key = `${nonce}:${JSON.stringify(deps)}`

  const [state, dispatch] = useReducer(reducer<T>, {
    key: '',
    data: null,
    error: null,
  } as Stored<T>)

  useEffect(() => {
    if (!enabled) return
    let active = true
    // `fetcher` is a new closure every render, so it is deliberately not a dependency:
    // `key` is derived from the caller's `deps` and is the only thing that should
    // trigger a refetch. The closure captured here is the one from the render that
    // produced the current key, which is exactly the request we want.
    fetcher()
      .then((data) => {
        if (active) dispatch({ type: 'resolved', key, data })
      })
      .catch((caught: unknown) => {
        if (active) dispatch({ type: 'rejected', key, error: toApiError(caught) })
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled])

  const reload = useCallback(() => bump(), [bump])
  const stale = state.key !== key

  return {
    data: stale ? null : state.data,
    loading: enabled && stale,
    error: stale ? null : state.error,
    reload,
  }
}
