/**
 * The event table.
 *
 * The point of these tests is that filtering and paging are server-side: every control
 * must turn into a query parameter, not into a client-side array filter.
 */

import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { EventsTab } from '../src/components/tabs/EventsTab'
import { completedMatch, events, players } from './msw/fixtures'
import { server } from './msw/server'
import { renderWithRouter } from './helpers'

/** Record the query parameters of every events request. */
function captureQueries(total = events.length) {
  const seen: URLSearchParams[] = []
  server.use(
    http.get('/api/matches/:id/events', ({ request }) => {
      const url = new URL(request.url)
      seen.push(url.searchParams)
      return HttpResponse.json({
        items: events,
        total,
        limit: Number(url.searchParams.get('limit') ?? 50),
        offset: Number(url.searchParams.get('offset') ?? 0),
      })
    }),
  )
  return seen
}

function render() {
  return renderWithRouter(
    <EventsTab match={completedMatch} players={players} roundCount={13} />,
  )
}

describe('EventsTab', () => {
  it('lists events with their round, time and detail', async () => {
    render()
    expect(await screen.findByText(/matching event/i)).toBeInTheDocument()
    expect(screen.getByText('round start')).toBeInTheDocument()
    expect(screen.getAllByText('organner').length).toBeGreaterThan(0)
  })

  it('shows both the reported and the capped damage figure', async () => {
    // Hiding the difference would invite the reader to sum the raw numbers.
    render()
    expect(await screen.findByText(/reported 199, capped to 100/i)).toBeInTheDocument()
  })

  it('sends the event type as a query parameter', async () => {
    const seen = captureQueries()
    render()
    await screen.findByText(/matching event/i)
    await userEvent.click(screen.getByRole('button', { name: /^Kills/ }))
    await waitFor(() =>
      expect(seen.some((params) => params.get('event_type') === 'kill')).toBe(true),
    )
  })

  it('sends the player filter as a query parameter', async () => {
    const seen = captureQueries()
    render()
    await screen.findByText(/matching event/i)
    await userEvent.selectOptions(screen.getByLabelText('Filter by player'), 'organner')
    await waitFor(() =>
      expect(seen.some((params) => params.get('player_key') === 'organner')).toBe(true),
    )
  })

  it('sends the round, side, weapon and damage filters', async () => {
    const seen = captureQueries()
    render()
    await screen.findByText(/matching event/i)

    await userEvent.selectOptions(screen.getByLabelText('Filter by round'), '5')
    await userEvent.selectOptions(screen.getByLabelText('Filter by side'), 'CT')
    await userEvent.selectOptions(screen.getByLabelText('Filter by weapon'), 'deagle')
    await userEvent.type(screen.getByLabelText('Minimum damage'), '90')

    await waitFor(() => {
      const last = seen.at(-1)
      expect(last?.get('round_num')).toBe('5')
      expect(last?.get('side')).toBe('CT')
      expect(last?.get('weapon')).toBe('deagle')
      expect(last?.get('min_damage')).toBe('90')
    })
  })

  it('debounces the search box into a single query parameter', async () => {
    const seen = captureQueries()
    render()
    await screen.findByText(/matching event/i)
    await userEvent.type(screen.getByLabelText('Search events'), 'awp')
    await waitFor(() => expect(seen.some((params) => params.get('search') === 'awp')).toBe(true))
  })

  it('sends the sort column and direction', async () => {
    const seen = captureQueries()
    render()
    await screen.findByText(/matching event/i)
    await userEvent.selectOptions(screen.getByLabelText('Sort by'), 'damage_health')
    await waitFor(() =>
      expect(seen.some((params) => params.get('sort') === 'damage_health')).toBe(true),
    )
    await userEvent.click(screen.getByLabelText(/sort descending/i))
    await waitFor(() => expect(seen.some((params) => params.get('order') === 'desc')).toBe(true))
  })

  it('pages through the results with an offset', async () => {
    const seen = captureQueries(500)
    render()
    await screen.findByText(/matching event/i)
    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(seen.some((params) => params.get('offset') === '50')).toBe(true))
  })

  it('returns to the first page when a filter changes', async () => {
    // Page 7 of the old result set is meaningless against the new one.
    const seen = captureQueries(500)
    render()
    await screen.findByText(/matching event/i)
    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => expect(seen.some((params) => params.get('offset') === '50')).toBe(true))

    await userEvent.click(screen.getByRole('button', { name: /^Kills/ }))
    await waitFor(() => {
      const last = seen.at(-1)
      expect(last?.get('event_type')).toBe('kill')
      expect(last?.get('offset')).toBe('0')
    })
  })

  it('disables Previous on the first page', async () => {
    captureQueries(500)
    render()
    await screen.findByText(/matching event/i)
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
  })

  it('offers a way out of an over-filtered view', async () => {
    server.use(
      http.get('/api/matches/:id/events', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    )
    render()
    await userEvent.click(await screen.findByRole('button', { name: /^Kills/ }))
    expect(await screen.findByText(/no matching events/i)).toBeInTheDocument()
    const empty = screen.getByText(/no matching events/i).closest('div')
    expect(within(empty as HTMLElement).getByRole('button', { name: /clear filters/i })).toBeInTheDocument()
  })

  it('surfaces a rejected filter as an error rather than an empty table', async () => {
    server.use(
      http.get('/api/matches/:id/events', () =>
        HttpResponse.json(
          { error: { code: 'validation_error', message: 'Some request parameters were invalid.' } },
          { status: 422 },
        ),
      ),
    )
    render()
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid/i)
  })

  it('flags events that happened after the round was decided', async () => {
    server.use(
      http.get('/api/matches/:id/events', () =>
        HttpResponse.json({
          items: [{ ...events[1], is_post_round: true }],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    )
    render()
    expect(await screen.findByText('post')).toBeInTheDocument()
  })
})
