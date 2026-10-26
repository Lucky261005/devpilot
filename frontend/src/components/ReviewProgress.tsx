import {
  formatElapsed,
  parseTime,
  reviewSteps,
  statusLine,
  type StepState,
} from '../lib/reviewSteps'
import type { Review } from '../lib/types'

const STATE_TEXT: Record<StepState, string> = {
  done: 'completed',
  current: 'in progress',
  pending: 'not started',
  failed: 'failed',
}

const DOT: Record<StepState, string> = {
  done: 'border-ok bg-ok text-bg',
  current: 'border-accent bg-accent-soft text-accent',
  pending: 'border-line-strong bg-panel text-faint',
  failed: 'border-danger bg-danger text-bg',
}

/** Compact stepper for a queued, running or failed review. `now` is the client time of the latest
 * poll (react-query `dataUpdatedAt`), so elapsed time advances with the existing polling only. */
export function ReviewProgress({ review, now }: { review: Review; now: number }) {
  const steps = reviewSteps(review)
  const since = review.status === 'queued' ? review.created_at : review.started_at
  const end = review.finished_at ? parseTime(review.finished_at) : now
  const elapsed = since ? formatElapsed(end - parseTime(since)) : null
  return (
    <div className="px-5 py-6 lg:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-base font-semibold" role="status" aria-live="polite">
          {statusLine(review)}
        </p>
        {elapsed ? (
          <p className="text-sm text-muted tabular-nums">
            {review.status === 'queued' ? 'Waiting' : review.finished_at ? 'Ran for' : 'Elapsed'}{' '}
            {elapsed}
          </p>
        ) : null}
      </div>
      <ol aria-label="Review progress" className="mt-5 flex flex-col gap-3 sm:flex-row sm:gap-0">
        {steps.map((step, i) => (
          <li
            key={step.key}
            aria-current={step.state === 'current' ? 'step' : undefined}
            className="flex items-center gap-2.5 sm:flex-1 sm:flex-col sm:items-start sm:gap-2"
          >
            <div className="flex items-center sm:w-full">
              <span
                aria-hidden
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 text-xs font-semibold ${DOT[step.state]} ${step.state === 'current' ? 'motion-safe:animate-pulse' : ''}`}
              >
                {step.state === 'done' ? '✓' : step.state === 'failed' ? '!' : i + 1}
              </span>
              {i < steps.length - 1 ? (
                <span
                  aria-hidden
                  className={`mx-2 hidden h-0.5 flex-1 rounded-full sm:block ${step.state === 'done' ? 'bg-ok' : 'bg-line'}`}
                />
              ) : null}
            </div>
            <span
              className={`text-sm ${step.state === 'current' ? 'font-semibold text-fg' : step.state === 'failed' ? 'font-semibold text-danger' : step.state === 'done' ? 'text-muted' : 'text-faint'}`}
            >
              {step.label}
              <span className="sr-only">, {STATE_TEXT[step.state]}</span>
            </span>
          </li>
        ))}
      </ol>
      {review.status !== 'failed' ? (
        <p className="mt-5 text-xs text-faint">
          Steps follow the worker's real stages; this page updates automatically.
        </p>
      ) : null}
    </div>
  )
}
