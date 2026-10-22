import {
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { ApiError } from '../lib/api'
import type { Review, Severity } from '../lib/types'

/* ------------------------------------------------------------------ actions */

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md'
}) {
  const styles = {
    primary: 'bg-accent text-accent-fg shadow-card hover:brightness-110',
    secondary: 'border border-line-strong bg-panel text-fg shadow-card hover:bg-subtle',
    danger:
      'border border-line-strong bg-panel text-danger hover:border-danger hover:bg-danger-soft',
    ghost: 'text-muted hover:bg-subtle hover:text-fg',
  }[variant]
  const sizes = { sm: 'h-8 px-2.5 text-[13px]', md: 'h-9 px-3.5 text-sm' }[size]
  return (
    <button
      {...props}
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-control font-medium whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50 ${sizes} ${styles} ${className}`}
    />
  )
}

/* ------------------------------------------------------------------ layout */

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  meta,
}: {
  title: ReactNode
  description?: ReactNode
  eyebrow?: ReactNode
  actions?: ReactNode
  meta?: ReactNode
}) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 flex-1 basis-full sm:basis-0">
        {eyebrow ? <div className="mb-2 text-sm text-muted">{eyebrow}</div> : null}
        <h1 className="text-display break-words">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-body text-muted">{description}</p> : null}
        {meta ? <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export function Card({
  children,
  className = '',
  style,
  title,
  description,
  actions,
}: {
  children: ReactNode
  className?: string
  style?: CSSProperties
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <section
      style={style}
      className={`rounded-card border border-line bg-panel shadow-card ${className}`}
    >
      {title ? (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
            {description ? <p className="mt-0.5 text-sm text-muted">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  )
}

/** Kept for existing call sites: a card without a header. */
export const Panel = Card

export function SectionTitle({
  children,
  description,
}: {
  children: ReactNode
  description?: ReactNode
}) {
  return (
    <div className="mb-4">
      <h2 className="text-title">{children}</h2>
      {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
    </div>
  )
}

export function Label({ children }: { children: ReactNode }) {
  return <h3 className="text-label font-semibold text-faint uppercase">{children}</h3>
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: { id: T; label: string; count?: number }[]
  value: T
  onChange: (id: T) => void
  label: string
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line px-3"
    >
      {items.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px inline-flex h-11 items-center gap-2 border-b-2 px-3 text-sm whitespace-nowrap ${
            value === t.id
              ? 'border-accent font-semibold text-fg'
              : 'border-transparent text-muted hover:text-fg'
          }`}
        >
          {t.label}
          {t.count !== undefined ? (
            <span
              className={`rounded-full px-1.5 py-px text-xs tabular-nums ${value === t.id ? 'bg-accent-soft text-accent' : 'bg-subtle text-muted'}`}
            >
              {t.count}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
}) {
  return (
    <div className="rounded-card border border-line bg-panel px-5 py-4 shadow-card">
      <Label>{label}</Label>
      <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ badges */

const SEV_STYLE: Record<Severity, string> = {
  critical: 'bg-danger text-white dark:text-bg',
  high: 'bg-danger-soft text-danger',
  medium: 'bg-warn-soft text-warn',
  low: 'bg-info-soft text-info',
  info: 'bg-subtle text-muted',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex h-5 items-center rounded-md px-1.5 text-[11px] font-semibold tracking-wide uppercase ${SEV_STYLE[severity]}`}
    >
      {severity}
    </span>
  )
}

export function SourceBadge({ source }: { source: 'static' | 'ai' }) {
  return source === 'static' ? (
    <span className="inline-flex h-5 items-center rounded-md border border-line px-1.5 text-[11px] font-medium text-muted">
      Analyzer
    </span>
  ) : (
    <span
      className="inline-flex h-5 items-center rounded-md border border-dashed border-ai/60 bg-ai-soft px-1.5 text-[11px] font-medium text-ai"
      title="Model-generated hypothesis. Verify before acting on it."
    >
      LLM hypothesis
    </span>
  )
}

export function Pill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'ai' | 'accent'
}) {
  const tones = {
    neutral: 'bg-subtle text-muted',
    ok: 'bg-ok-soft text-ok',
    warn: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    ai: 'bg-ai-soft text-ai',
    accent: 'bg-accent-soft text-accent',
  }[tone]
  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap ${tones}`}
    >
      {children}
    </span>
  )
}

const STATUS_STYLE: Record<Review['status'], string> = {
  queued: 'bg-subtle text-muted',
  running: 'bg-accent-soft text-accent',
  completed: 'bg-ok-soft text-ok',
  failed: 'bg-danger-soft text-danger',
}

export function StatusBadge({
  status,
  stage,
}: {
  status: Review['status']
  stage?: string | null
}) {
  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap capitalize ${STATUS_STYLE[status]}`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full bg-current ${status === 'running' ? 'animate-pulse' : ''}`}
      />
      {status}
      {status === 'running' && stage ? (
        <span className="font-normal normal-case opacity-80">· {stage.replace('_', ' ')}</span>
      ) : null}
    </span>
  )
}

/* ------------------------------------------------------------------ states */

export function ErrorBox({
  error,
  title = 'Something went wrong',
}: {
  error: unknown
  title?: string
}) {
  const msg = error instanceof Error ? error.message : String(error)
  const rid = error instanceof ApiError ? error.requestId : undefined
  return (
    <div
      role="alert"
      className="rounded-control border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-0.5 break-words text-fg/90">{msg}</p>
      {rid ? <p className="mt-1 font-mono text-xs text-muted">Request ID: {rid}</p> : null}
    </div>
  )
}

export function Notice({
  children,
  tone = 'warn',
}: {
  children: ReactNode
  tone?: 'warn' | 'ok' | 'info'
}) {
  const tones = {
    warn: 'border-warn/30 bg-warn-soft text-warn',
    ok: 'border-ok/30 bg-ok-soft text-ok',
    info: 'border-info/30 bg-info-soft text-info',
  }[tone]
  return <div className={`rounded-control border px-4 py-3 text-sm ${tones}`}>{children}</div>
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-card border border-dashed border-line-strong px-6 py-12 text-center">
      <p className="text-base font-semibold">{title}</p>
      {children ? <div className="mx-auto mt-2 max-w-md text-sm text-muted">{children}</div> : null}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2.5 px-5 py-6 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
      {label}…
    </div>
  )
}

/* ------------------------------------------------------------------ forms */

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint ? (
        <span className="mt-1.5 block text-xs leading-relaxed text-muted">{hint}</span>
      ) : null}
    </label>
  )
}

export const inputClass =
  'h-9 w-full rounded-control border border-line-strong bg-panel px-3 text-sm text-fg placeholder:text-faint hover:border-faint focus:border-accent focus:ring-2 focus:ring-accent/25 focus:outline-none'

/* ------------------------------------------------------------------ formatting */

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function timeAgo(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return d.toLocaleDateString()
}

/* ------------------------------------------------------------------ dialog */

/** Modal confirmation on the native <dialog>: focus trap, Escape and backdrop come with it. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (open && !d?.open) d?.showModal()
    if (!open && d?.open) d.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className="dialog m-auto w-[min(440px,calc(100vw-32px))] rounded-card border border-line bg-panel p-0 text-fg shadow-pop"
    >
      <div className="p-6">
        <h2 className="text-base font-semibold">{title}</h2>
        <div className="mt-2 text-sm text-muted">{children}</div>
        <div className="mt-6 flex justify-end gap-2">
          <Button autoFocus onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  )
}
