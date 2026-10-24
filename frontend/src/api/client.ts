/**
 * The API client.
 *
 * Every backend failure arrives as `{"error": {code, message, details}}`, including
 * validation errors, so one error type covers the whole surface and the UI can branch
 * on a stable `code` instead of parsing prose.
 */

import type {
  EventQuery,
  Health,
  MapInfo,
  MatchDetail,
  MatchEvent,
  MatchStatus,
  MatchSummary,
  Metrics,
  Page,
  PlayerStats,
  Round,
} from './types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
}

async function toError(response: Response): Promise<ApiError> {
  let code = 'request_failed'
  let message = `Request failed with status ${response.status}.`
  let details: Record<string, unknown> = {}
  try {
    const body = (await response.json()) as ErrorEnvelope
    if (body.error) {
      code = body.error.code ?? code
      message = body.error.message ?? message
      details = body.error.details ?? {}
    }
  } catch {
    // A non-JSON body (a proxy error page, say) leaves the defaults in place.
  }
  return new ApiError(code, message, response.status, details)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function query(params: Record<string, unknown> | object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  health: () => request<Health>('/api/health'),

  metrics: () => request<Metrics>('/api/metrics'),

  listMatches: (params: { status?: MatchStatus; map?: string; q?: string; limit?: number; offset?: number } = {}) =>
    request<Page<MatchSummary>>(`/api/matches${query(params)}`),

  getMatch: (id: string) => request<MatchDetail>(`/api/matches/${id}`),

  getPlayers: (id: string) => request<PlayerStats[]>(`/api/matches/${id}/players`),

  getRounds: (id: string) => request<Round[]>(`/api/matches/${id}/rounds`),

  getEvents: (id: string, params: EventQuery = {}) =>
    request<Page<MatchEvent>>(`/api/matches/${id}/events${query(params)}`),

  getEventCounts: (id: string) => request<Record<string, number>>(`/api/matches/${id}/events/count`),

  getWeapons: (id: string) => request<string[]>(`/api/matches/${id}/weapons`),

  getMapInfo: (mapName: string) => request<MapInfo>(`/api/maps/${mapName}`),

  deleteMatch: (id: string) => request<void>(`/api/matches/${id}`, { method: 'DELETE' }),

  /**
   * Upload a demo as a raw body.
   *
   * Not multipart: the server enforces its size cap while reading the stream, which it
   * cannot do for a form body that the framework has already spooled to disk.
   * `XMLHttpRequest` rather than `fetch` because it is the only one that reports upload
   * progress, and these files are hundreds of megabytes.
   */
  uploadDemo: (
    file: File,
    onProgress?: (fraction: number) => void,
    signal?: AbortSignal,
  ): Promise<{ id: string; status: MatchStatus }> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `/api/matches${query({ filename: file.name })}`)
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total)
      }
      xhr.onload = () => {
        let parsed: unknown = null
        try {
          parsed = JSON.parse(xhr.responseText)
        } catch {
          // handled below
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(parsed as { id: string; status: MatchStatus })
          return
        }
        const envelope = parsed as ErrorEnvelope | null
        reject(
          new ApiError(
            envelope?.error?.code ?? 'upload_failed',
            envelope?.error?.message ?? `Upload failed with status ${xhr.status}.`,
            xhr.status,
            envelope?.error?.details ?? {},
          ),
        )
      }
      xhr.onerror = () =>
        reject(new ApiError('network_error', 'The upload could not reach the server.', 0))
      xhr.onabort = () => reject(new ApiError('cancelled', 'The upload was cancelled.', 0))

      signal?.addEventListener('abort', () => xhr.abort())
      xhr.send(file)
    }),

  importDemo: (url: string, filename?: string) =>
    request<{ id: string; status: MatchStatus }>('/api/matches/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename: filename ?? null }),
    }),
}
