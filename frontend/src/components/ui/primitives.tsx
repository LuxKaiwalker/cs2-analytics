/**
 * Shared UI primitives.
 *
 * Small and local on purpose: the app needs a handful of consistent pieces, not a
 * component library. Radix supplies the two things that are genuinely hard to get right
 * by hand — tooltips and tabs with correct keyboard and screen-reader behaviour.
 */

import * as RadixTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export function Panel({
  children,
  className = '',
  title,
  subtitle,
  actions,
}: {
  children?: ReactNode
  className?: string
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-[var(--color-line)] px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-[var(--color-ink)]">{title}</h2>}
            {subtitle && (
              <p className="mt-0.5 text-xs text-[var(--color-ink-secondary)]">{subtitle}</p>
            )}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

const BUTTON_VARIANTS = {
  primary:
    'bg-[var(--color-team-a)] text-white hover:brightness-110 disabled:bg-[var(--color-line-strong)]',
  secondary:
    'bg-[var(--color-surface-raised)] text-[var(--color-ink)] border border-[var(--color-line-strong)] hover:bg-[var(--color-surface-hover)]',
  ghost: 'text-[var(--color-ink-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-ink)]',
  danger:
    'bg-transparent text-[var(--color-bad)] border border-[var(--color-bad)]/40 hover:bg-[var(--color-bad)]/10',
} as const

export function Button({
  children,
  onClick,
  variant = 'secondary',
  size = 'md',
  disabled,
  type = 'button',
  className = '',
  title,
  ariaLabel,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: keyof typeof BUTTON_VARIANTS
  size?: 'sm' | 'md'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
  title?: string
  ariaLabel?: string
}) {
  const sizing = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-1.5 text-sm'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      className={`inline-flex items-center gap-1.5 rounded font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${sizing} ${BUTTON_VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

const BADGE_TONES = {
  neutral: 'bg-[var(--color-surface-raised)] text-[var(--color-ink-secondary)] border-[var(--color-line-strong)]',
  good: 'bg-[var(--color-good)]/12 text-[var(--color-good)] border-[var(--color-good)]/35',
  bad: 'bg-[var(--color-bad)]/12 text-[var(--color-bad)] border-[var(--color-bad)]/35',
  warn: 'bg-[var(--color-warn)]/12 text-[var(--color-warn)] border-[var(--color-warn)]/35',
  info: 'bg-[var(--color-team-a)]/12 text-[var(--color-team-a)] border-[var(--color-team-a)]/35',
} as const

export function Badge({
  children,
  tone = 'neutral',
  className = '',
  title,
}: {
  children: ReactNode
  tone?: keyof typeof BADGE_TONES
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.6875rem] font-medium leading-tight ${BADGE_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

/** A side chip. The letters carry the meaning; the tint only reinforces it. */
export function SideBadge({ side }: { side: 'T' | 'CT' | null | undefined }) {
  if (!side) return <span className="unknown">—</span>
  const isCt = side === 'CT'
  return (
    <span
      className="inline-flex min-w-[1.75rem] justify-center rounded border px-1 py-0.5 text-[0.625rem] font-semibold"
      style={{
        color: isCt ? 'var(--color-ct)' : 'var(--color-t)',
        borderColor: isCt ? 'color-mix(in oklab, var(--color-ct) 35%, transparent)' : 'color-mix(in oklab, var(--color-t) 35%, transparent)',
        background: isCt ? 'color-mix(in oklab, var(--color-ct) 12%, transparent)' : 'color-mix(in oklab, var(--color-t) 12%, transparent)',
      }}
    >
      {side}
    </span>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-[var(--color-ink-secondary)]">
      <svg
        className="size-4 animate-spin"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      {label && <span>{label}</span>}
    </span>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-12" role="status" aria-live="polite">
      <Spinner label={label} />
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="text-[var(--color-ink-muted)]">{icon}</div>}
      <p className="text-sm font-medium text-[var(--color-ink)]">{title}</p>
      {description && (
        <p className="max-w-md text-xs leading-relaxed text-[var(--color-ink-secondary)]">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  code,
  onRetry,
}: {
  title?: string
  message?: string
  code?: string
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center" role="alert">
      <p className="text-sm font-medium text-[var(--color-bad)]">{title}</p>
      {message && (
        <p className="max-w-md text-xs leading-relaxed text-[var(--color-ink-secondary)]">
          {message}
        </p>
      )}
      {code && <code className="text-[0.6875rem] text-[var(--color-ink-muted)]">{code}</code>}
      {onRetry && (
        <div className="mt-2">
          <Button onClick={onRetry} size="sm">
            Try again
          </Button>
        </div>
      )}
    </div>
  )
}

export function Tooltip({
  content,
  children,
  side = 'top',
}: {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}) {
  if (!content) return <>{children}</>
  return (
    <RadixTooltip.Root delayDuration={150}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded border border-[var(--color-line-strong)] bg-[var(--color-surface-raised)] px-2.5 py-2 text-xs leading-relaxed text-[var(--color-ink)] shadow-lg"
        >
          {content}
          <RadixTooltip.Arrow className="fill-[var(--color-line-strong)]" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

export const TooltipProvider = RadixTooltip.Provider

/** A labelled statistic. The label is as important as the number. */
export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  tone?: 'good' | 'bad'
}) {
  const color =
    tone === 'good'
      ? 'var(--color-good)'
      : tone === 'bad'
        ? 'var(--color-bad)'
        : 'var(--color-ink)'
  return (
    <div className="min-w-0">
      <div className="text-[0.6875rem] uppercase tracking-wide text-[var(--color-ink-secondary)]">
        {label}
      </div>
      <div className="mt-0.5 truncate text-lg font-semibold tabular" style={{ color }}>
        {value}
      </div>
      {hint && <div className="text-[0.6875rem] text-[var(--color-ink-muted)]">{hint}</div>}
    </div>
  )
}
