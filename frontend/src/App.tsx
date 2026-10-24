import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { TooltipProvider } from './components/ui/primitives'
import { MatchLibraryPage } from './pages/MatchLibraryPage'
import { MatchPage } from './pages/MatchPage'

function Header() {
  const { pathname } = useLocation()
  const onMatch = pathname.startsWith('/matches/')
  return (
    <header className="sticky top-0 z-20 border-b border-[var(--color-line)] bg-[var(--color-base)]/95 backdrop-blur">
      <div className="mx-auto flex max-w-[110rem] items-center gap-4 px-4 py-3 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5 text-[var(--color-ink)]">
          <svg viewBox="0 0 24 24" className="size-5 text-[var(--color-team-a)]" aria-hidden="true">
            <path
              d="M3 20V9l5-5 4 4 4-4 5 5v11"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <path d="M3 20h18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <span className="text-sm font-semibold tracking-tight">CS2 Match Analytics</span>
        </Link>
        {onMatch && (
          <Link
            to="/"
            className="text-xs text-[var(--color-ink-secondary)] transition hover:text-[var(--color-ink)]"
          >
            ← Match library
          </Link>
        )}
        <div className="ml-auto text-[0.6875rem] text-[var(--color-ink-muted)]">
          Local analysis · demos stay on this machine
        </div>
      </div>
    </header>
  )
}

export function App() {
  return (
    <TooltipProvider>
      <div className="min-h-screen">
        <Header />
        <main className="mx-auto max-w-[110rem] px-4 py-6 sm:px-6">
          <Routes>
            <Route path="/" element={<MatchLibraryPage />} />
            <Route path="/matches/:matchId" element={<MatchPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </TooltipProvider>
  )
}
