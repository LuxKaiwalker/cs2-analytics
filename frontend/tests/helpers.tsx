import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { TooltipProvider } from '../src/components/ui/primitives'

export function renderWithRouter(ui: ReactElement, { route = '/' } = {}) {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </TooltipProvider>,
  )
}

/** A File that reports an arbitrary size without allocating it. */
export function fakeDemoFile(name: string, size: number): File {
  const file = new File(['PBDEMS2\0'], name, { type: 'application/octet-stream' })
  Object.defineProperty(file, 'size', { value: size })
  return file
}
