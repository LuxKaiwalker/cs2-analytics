/** Default API handlers. Individual tests override what they care about. */

import { HttpResponse, http } from 'msw'
import {
  MATCH_ID,
  completedMatch,
  degradedMatch,
  emptyMatch,
  events,
  failedMatch,
  matchList,
  metrics,
  players,
  processingMatch,
  rounds,
} from './fixtures'

const byId = {
  [completedMatch.id]: completedMatch,
  [processingMatch.id]: processingMatch,
  [failedMatch.id]: failedMatch,
  [degradedMatch.id]: degradedMatch,
  [emptyMatch.id]: emptyMatch,
}

export function errorBody(code: string, message: string, details?: Record<string, unknown>) {
  return { error: { code, message, ...(details ? { details } : {}) } }
}

export const handlers = [
  http.get('/api/metrics', () => HttpResponse.json(metrics)),

  http.get('/api/matches', ({ request }) => {
    const status = new URL(request.url).searchParams.get('status')
    const items = status ? matchList.filter((match) => match.status === status) : matchList
    return HttpResponse.json({ items, total: items.length, limit: 50, offset: 0 })
  }),

  http.get('/api/matches/:id', ({ params }) => {
    const match = byId[params.id as string]
    if (!match) {
      return HttpResponse.json(errorBody('not_found', 'No such match.'), { status: 404 })
    }
    return HttpResponse.json(match)
  }),

  http.get('/api/matches/:id/players', ({ params }) =>
    HttpResponse.json(params.id === emptyMatch.id ? [] : players),
  ),

  http.get('/api/matches/:id/rounds', ({ params }) =>
    HttpResponse.json(params.id === emptyMatch.id ? [] : rounds),
  ),

  http.get('/api/matches/:id/events', ({ request }) => {
    const url = new URL(request.url)
    const type = url.searchParams.get('event_type')
    const round = url.searchParams.get('round_num')
    const limit = Number(url.searchParams.get('limit') ?? 50)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    let items = events
    if (type) items = items.filter((event) => event.event_type === type)
    if (round) items = items.filter((event) => event.round_num === Number(round))
    return HttpResponse.json({
      items: items.slice(offset, offset + limit),
      total: items.length,
      limit,
      offset,
    })
  }),

  http.get('/api/matches/:id/events/count', () =>
    HttpResponse.json({ round_start: 1, damage: 1, kill: 1 }),
  ),

  http.get('/api/matches/:id/weapons', () => HttpResponse.json(['deagle', 'ak47'])),

  http.get('/api/maps/:map', ({ params }) =>
    HttpResponse.json({
      map_name: params.map,
      available: true,
      pos_x: -3230,
      pos_y: 1713,
      scale: 5,
      image_width: 1024,
      image_height: 1024,
      levels: [
        {
          id: 'default',
          radar_url: `/api/maps/${String(params.map)}/radar.png?level=default`,
          altitude_min: null,
          altitude_max: null,
        },
      ],
      reason: null,
    }),
  ),

  http.get('/api/maps/:map/radar.png', () => new HttpResponse(null, { status: 200 })),

  http.delete('/api/matches/:id', () => new HttpResponse(null, { status: 204 })),

  http.post('/api/matches', () => HttpResponse.json({ id: MATCH_ID, status: 'queued' }, { status: 201 })),

  http.post('/api/matches/import', () =>
    HttpResponse.json({ id: MATCH_ID, status: 'queued' }, { status: 201 }),
  ),
]
