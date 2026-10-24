/**
 * The dashboard's status routing.
 *
 * The case worth the most attention is the last one: a demo that parses successfully but
 * contains no match must not look like a failure, and must not look like a bug either.
 */

import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { MatchPage } from '../src/pages/MatchPage'
import {
  completedMatch,
  degradedMatch,
  emptyMatch,
  failedMatch,
  processingMatch,
} from './msw/fixtures'
import { server } from './msw/server'
import { renderWithRouter } from './helpers'

function renderMatch(id: string) {
  return renderWithRouter(
    <Routes>
      <Route path="/matches/:matchId" element={<MatchPage />} />
    </Routes>,
    { route: `/matches/${id}` },
  )
}

describe('MatchPage', () => {
  it('shows a processing view with the current stage and no fake percentage', async () => {
    renderMatch(processingMatch.id)
    expect(await screen.findByText('Processing')).toBeInTheDocument()
    expect(screen.getAllByText('Parsing demo').length).toBeGreaterThan(0)
    // The parser reports no progress, so a progress bar would be invented.
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByText(/in this stage/i)).toBeInTheDocument()
  })

  it('shows the failure reason, its code and an actionable hint', async () => {
    renderMatch(failedMatch.id)
    expect(await screen.findByText('Processing failed')).toBeInTheDocument()
    expect(screen.getByText('The file is not a valid CS2 demo.')).toBeInTheDocument()
    expect(screen.getByText('invalid_demo')).toBeInTheDocument()
    expect(screen.getByText(/does not begin with the CS2 demo signature/i)).toBeInTheDocument()
  })

  it('renders the dashboard for a completed match', async () => {
    renderMatch(completedMatch.id)
    expect(await screen.findByRole('tab', { name: 'overview' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'players' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'rounds' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'events' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'map' })).toBeInTheDocument()
    expect(await screen.findByText('Score progression')).toBeInTheDocument()
  })

  it('switches tabs and loads the scoreboard', async () => {
    renderMatch(completedMatch.id)
    await userEvent.click(await screen.findByRole('tab', { name: 'players' }))
    expect(await screen.findByText('Player statistics')).toBeInTheDocument()
    expect(screen.getByText('organner')).toBeInTheDocument()
  })

  it('warns when a source dataset is missing and says metrics will read as a dash', async () => {
    renderMatch(degradedMatch.id)
    expect(await screen.findByText(/some source data is missing/i)).toBeInTheDocument()
    expect(screen.getByText(/contains no flash events/i)).toBeInTheDocument()
    expect(screen.getByText(/never as zero/i)).toBeInTheDocument()
  })

  it('distinguishes an empty-but-valid demo from a parsing failure', async () => {
    renderMatch(emptyMatch.id)
    expect(
      await screen.findByText(/parsed successfully, but this demo contains no match data/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/this is not a parsing failure/i)).toBeInTheDocument()
    expect(screen.queryByText('Processing failed')).not.toBeInTheDocument()
  })

  it('reports a missing match without offering a pointless retry', async () => {
    renderMatch('doesnotexist')
    expect(await screen.findByText('Match not found')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('polls while processing and shows the report once it completes', async () => {
    // The transition a user actually waits through.
    let calls = 0
    server.use(
      http.get('/api/matches/:id', () => {
        calls += 1
        return HttpResponse.json(
          calls < 2 ? processingMatch : { ...completedMatch, id: processingMatch.id },
        )
      }),
    )
    renderMatch(processingMatch.id)
    expect(await screen.findByText('Processing')).toBeInTheDocument()
    await waitFor(
      () => expect(screen.getByRole('tab', { name: 'overview' })).toBeInTheDocument(),
      { timeout: 6000 },
    )
  })

  it('stops polling once a match is complete', async () => {
    let calls = 0
    server.use(
      http.get('/api/matches/:id', () => {
        calls += 1
        return HttpResponse.json(completedMatch)
      }),
    )
    renderMatch(completedMatch.id)
    await screen.findByRole('tab', { name: 'overview' })
    const after = calls
    await new Promise((resolve) => setTimeout(resolve, 1500))
    expect(calls).toBe(after)
  })
})
