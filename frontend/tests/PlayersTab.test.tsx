/**
 * The scoreboard table.
 *
 * The two behaviours that matter most: an unknown value never reads as zero, and
 * sorting never lets an unknown masquerade as the worst score.
 */

import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlayersTab } from '../src/components/tabs/PlayersTab'
import { completedMatch, degradedMatch, players } from './msw/fixtures'
import { renderWithRouter } from './helpers'

function names(): string[] {
  const rows = screen.getAllByRole('row').slice(1)
  return rows.map((row) => within(row).getAllByRole('cell')[0]?.textContent?.trim() ?? '')
}

describe('PlayersTab', () => {
  it('renders every player with their core metrics', async () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    expect(await screen.findByText('Player statistics')).toBeInTheDocument()
    for (const player of players) {
      expect(screen.getByText(player.name)).toBeInTheDocument()
    }
    expect(screen.getByText('183.2')).toBeInTheDocument()
    expect(screen.getByText('40.7%')).toBeInTheDocument()
  })

  it('sorts by kills descending by default', () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    expect(names()[0]).toBe('organner')
  })

  it('reverses the sort when the same column is clicked again', async () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    await userEvent.click(screen.getByRole('button', { name: /sort by kills/i }))
    expect(names()[0]).not.toBe('organner')
    await userEvent.click(screen.getByRole('button', { name: /sort by kills/i }))
    expect(names()[0]).toBe('organner')
  })

  it('shows a dash, not a zero, for a metric with no denominator', () => {
    // flawlessnofrag has no kills, so the headshot rate is undefined.
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    const row = screen.getByText('flawlessnofrag').closest('tr')
    expect(row).not.toBeNull()
    const cells = within(row as HTMLElement).getAllByRole('cell')
    const texts = cells.map((cell) => cell.textContent?.trim())
    expect(texts).toContain('—')
    // And the real zeros are still zeros.
    expect(texts).toContain('0')
  })

  it('keeps unknown values last whichever way the column is sorted', async () => {
    // An absent value is not a low one: sorting it to the bottom of a descending list
    // and the top of an ascending one would make it look like the worst score.
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    const header = screen.getByRole('button', { name: /sort by headshot percentage/i })

    await userEvent.click(header)
    expect(names().at(-1)).toBe('flawlessnofrag')
    await userEvent.click(header)
    expect(names().at(-1)).toBe('flawlessnofrag')
  })

  it('filters by side', async () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    await userEvent.click(screen.getByRole('button', { name: 'T', pressed: false }))
    const shown = names()
    expect(shown).toContain('bargota22')
    expect(shown).not.toContain('organner')
  })

  it('reveals the extended columns on request', async () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    expect(screen.queryByText('CLW')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /all columns/i }))
    expect(screen.getByText('CLW')).toBeInTheDocument()
  })

  it('states the denominator the rates were computed against', () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={players} />)
    expect(screen.getByText(/13 scored rounds/)).toBeInTheDocument()
    expect(screen.getByText(/never shown as zero/i)).toBeInTheDocument()
  })

  it('explains an unknown caused by missing source data', async () => {
    // With no flash data in the demo, the cell must say why rather than show 0.
    const noFlash = players.map((player) => ({ ...player, enemies_flashed: null }))
    renderWithRouter(<PlayersTab match={degradedMatch} players={noFlash} />)
    const unknowns = await screen.findAllByLabelText('enemies_flashed: unknown')
    expect(unknowns.length).toBe(noFlash.length)
  })

  it('shows an empty state when there are no players', () => {
    renderWithRouter(<PlayersTab match={completedMatch} players={[]} />)
    expect(screen.getByText('No player statistics')).toBeInTheDocument()
  })
})
