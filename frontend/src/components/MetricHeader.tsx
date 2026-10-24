/**
 * A table header cell that explains its metric.
 *
 * The definition, denominator and caveats come from `/api/metrics`, which is generated
 * from the same registry the computation uses — so a column can never be documented as
 * something other than what it measures.
 */

import type { MetricDefinition } from '../api/types'
import { Tooltip } from './ui/primitives'

export function MetricHeader({
  definition,
  label,
  sorted,
  onSort,
}: {
  definition?: MetricDefinition
  label: string
  sorted?: 'asc' | 'desc' | false
  onSort?: () => void
}) {
  const content = definition ? (
    <div className="space-y-1">
      <div className="font-medium text-[var(--color-ink)]">{definition.label}</div>
      <p className="text-[var(--color-ink-secondary)]">{definition.description}</p>
      {definition.denominator && (
        <p className="text-[var(--color-ink-muted)]">Per {definition.denominator}.</p>
      )}
      {definition.caveat && (
        <p className="text-[var(--color-warn)]">{definition.caveat}</p>
      )}
    </div>
  ) : null

  const arrow = sorted === 'asc' ? '▲' : sorted === 'desc' ? '▼' : ''

  const inner = (
    <span className="inline-flex items-center gap-1">
      <span className={definition ? 'border-b border-dotted border-[var(--color-ink-muted)]' : ''}>
        {label}
      </span>
      {arrow && <span className="text-[0.5rem] text-[var(--color-ink)]">{arrow}</span>}
    </span>
  )

  const cell = onSort ? (
    <button
      onClick={onSort}
      className="w-full text-right uppercase tracking-[0.04em] hover:text-[var(--color-ink)]"
      aria-label={`Sort by ${definition?.label ?? label}`}
    >
      {inner}
    </button>
  ) : (
    inner
  )

  return content ? <Tooltip content={content}>{cell}</Tooltip> : <>{cell}</>
}
