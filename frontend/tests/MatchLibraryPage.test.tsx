/** The match library's loading, empty, error and populated states. */

import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MatchLibraryPage } from '../src/pages/MatchLibraryPage'
import { errorBody } from './msw/handlers'
import { server } from './msw/server'
import { renderWithRouter } from './helpers'

// The page navigates on row click; the memory router in the helper handles it, so the
// real module is used as-is.

describe('MatchLibraryPage', () => {
  it('shows a loading state before the list arrives', () => {
    renderWithRouter(<MatchLibraryPage />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading matches/i)
  })

  it('lists matches with their score and status', async () => {
    renderWithRouter(<MatchLibraryPage />)
    const rows = await screen.findAllByRole('button', { name: /open .* match/i })
    expect(rows.length).toBeGreaterThan(0)
    expect(screen.getAllByText('Mirage').length).toBeGreaterThan(0)
    // Scope to the list, since the filter controls carry the same words.
    const list = screen.getByRole('list')
    expect(list).toHaveTextContent('Completed')
    expect(list).toHaveTextContent('Failed')
    expect(list).toHaveTextContent('Parsing demo')
  })

  it('shows an empty state with guidance when nothing is stored', async () => {
    server.use(
      http.get('/api/matches', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    )
    renderWithRouter(<MatchLibraryPage />)
    expect(await screen.findByText(/no matches yet/i)).toBeInTheDocument()
    expect(
      screen.getByText(/upload a cs2 demo above to get your first match report/i),
    ).toBeInTheDocument()
  })

  it('shows the error envelope and offers a retry when the list fails', async () => {
    server.use(
      http.get('/api/matches', () =>
        HttpResponse.json(errorBody('internal_error', 'An unexpected error occurred.'), {
          status: 500,
        }),
      ),
    )
    renderWithRouter(<MatchLibraryPage />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/unexpected error/i)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('filters by status through the API, not in the browser', async () => {
    const seen: string[] = []
    server.use(
      http.get('/api/matches', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status')
        if (status) seen.push(status)
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 })
      }),
    )
    renderWithRouter(<MatchLibraryPage />)
    await userEvent.click(screen.getByRole('button', { name: 'Failed' }))
    await waitFor(() => expect(seen).toContain('failed'))
  })

  it('asks for confirmation before deleting', async () => {
    let deleted = false
    server.use(
      http.delete('/api/matches/:id', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderWithRouter(<MatchLibraryPage />)
    const deleteButtons = await screen.findAllByRole('button', { name: /^Delete /i })
    await userEvent.click(deleteButtons[0] as HTMLElement)

    expect(screen.getByText('Delete?')).toBeInTheDocument()
    expect(deleted).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Yes' }))
    await waitFor(() => expect(deleted).toBe(true))
  })
})
