/** The upload workflow: client-side rejection, progress, and the duplicate shortcut. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { UploadPanel } from '../src/components/UploadPanel'
import { MATCH_ID } from './msw/fixtures'
import { errorBody } from './msw/handlers'
import { server } from './msw/server'
import { fakeDemoFile, renderWithRouter } from './helpers'

/** XMLHttpRequest is not intercepted by the HTTP mock, so it is stubbed directly. */
function stubUpload(result: { status: number; body: unknown }) {
  class FakeXhr {
    status = 0
    responseText = ''
    upload = { onprogress: null as ((event: ProgressEvent) => void) | null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    onabort: (() => void) | null = null
    open() {}
    setRequestHeader() {}
    abort() {
      this.onabort?.()
    }
    send() {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 } as ProgressEvent)
      this.status = result.status
      this.responseText = JSON.stringify(result.body)
      this.onload?.()
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
}

describe('UploadPanel', () => {
  it('rejects a dropped file without a .dem extension before uploading anything', async () => {
    // The file picker already filters by `accept`, but a drag-and-drop does not —
    // so this is the path where the extension check actually earns its keep.
    const onAccepted = vi.fn()
    const sent = vi.fn()
    vi.stubGlobal(
      'XMLHttpRequest',
      class {
        upload = {}
        open() {}
        setRequestHeader() {}
        send() {
          sent()
        }
      },
    )
    const { container } = renderWithRouter(<UploadPanel onAccepted={onAccepted} />)

    const zone = container.querySelector('.border-dashed')
    expect(zone).not.toBeNull()
    fireEvent.drop(zone as Element, {
      dataTransfer: { files: [fakeDemoFile('screenshot.png', 1_000_000)] },
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(/not a \.dem file/i)
    expect(sent).not.toHaveBeenCalled()
    expect(onAccepted).not.toHaveBeenCalled()
  })

  it('rejects a file over the size limit without uploading it', async () => {
    const sent = vi.fn()
    vi.stubGlobal(
      'XMLHttpRequest',
      class {
        upload = {}
        open() {}
        setRequestHeader() {}
        send() {
          sent()
        }
      },
    )
    renderWithRouter(<UploadPanel onAccepted={vi.fn()} />)

    await userEvent.upload(
      screen.getByLabelText('Choose a CS2 demo file'),
      fakeDemoFile('huge.dem', 900 * 1024 * 1024),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/over the/i)
    expect(sent).not.toHaveBeenCalled()
  })

  it('rejects a file too small to be a demo', async () => {
    renderWithRouter(<UploadPanel onAccepted={vi.fn()} />)
    await userEvent.upload(
      screen.getByLabelText('Choose a CS2 demo file'),
      fakeDemoFile('tiny.dem', 100),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(/too small/i)
  })

  it('reports the match id once the server accepts the upload', async () => {
    stubUpload({ status: 201, body: { id: MATCH_ID, status: 'queued' } })
    const onAccepted = vi.fn()
    renderWithRouter(<UploadPanel onAccepted={onAccepted} />)

    await userEvent.upload(
      screen.getByLabelText('Choose a CS2 demo file'),
      fakeDemoFile('match.dem', 5_000_000),
    )

    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith(MATCH_ID))
  })

  it('surfaces a server rejection with its message', async () => {
    stubUpload({
      status: 422,
      body: errorBody('source1_demo', 'This is a CS:GO (Source 1) demo.'),
    })
    renderWithRouter(<UploadPanel onAccepted={vi.fn()} />)

    await userEvent.upload(
      screen.getByLabelText('Choose a CS2 demo file'),
      fakeDemoFile('old.dem', 5_000_000),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/CS:GO/)
    expect(alert).toHaveTextContent('source1_demo')
  })

  it('treats a duplicate as success and opens the existing match', async () => {
    // Re-uploading a demo is not a failure: the analysis already exists.
    stubUpload({
      status: 409,
      body: errorBody('duplicate_demo', 'Already uploaded.', { match_id: 'existing123' }),
    })
    const onAccepted = vi.fn()
    renderWithRouter(<UploadPanel onAccepted={onAccepted} />)

    await userEvent.upload(
      screen.getByLabelText('Choose a CS2 demo file'),
      fakeDemoFile('again.dem', 5_000_000),
    )

    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith('existing123'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('imports from a URL and reports the new match', async () => {
    const onAccepted = vi.fn()
    renderWithRouter(<UploadPanel onAccepted={onAccepted} />)

    await userEvent.click(screen.getByRole('tab', { name: 'Import from URL' }))
    await userEvent.type(screen.getByLabelText('Demo URL'), 'https://example.com/m.dem')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith(MATCH_ID))
  })

  it('shows the reason a URL was refused', async () => {
    server.use(
      http.post('/api/matches/import', () =>
        HttpResponse.json(
          errorBody('url_not_allowed', 'That URL resolves to a private address.'),
          { status: 422 },
        ),
      ),
    )
    renderWithRouter(<UploadPanel onAccepted={vi.fn()} />)

    await userEvent.click(screen.getByRole('tab', { name: 'Import from URL' }))
    await userEvent.type(screen.getByLabelText('Demo URL'), 'https://127.0.0.1/m.dem')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/private address/i)
  })
})
