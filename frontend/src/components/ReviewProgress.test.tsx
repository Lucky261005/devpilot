import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Review } from '../lib/types'
import { formatElapsed, reviewSteps, statusLine } from '../lib/reviewSteps'
import { ReviewProgress } from './ReviewProgress'

const STARTED = '2026-10-25T10:00:00'
const T0 = Date.parse(STARTED + 'Z')

function review(over: Partial<Review>): Review {
  return {
    id: 1,
    repository_id: 1,
    kind: 'full',
    base_ref: null,
    head_ref: null,
    use_ai: true,
    status: 'running',
    stage: 'static_analysis',
    error: null,
    created_at: '2026-10-25T09:59:50',
    started_at: STARTED,
    finished_at: null,
    severity_counts: {},
    pr_number: null,
    pr_title: null,
    stats: {},
    ...over,
  }
}

const states = (r: Partial<Review>) => reviewSteps(review(r)).map((s) => `${s.key}:${s.state}`)

afterEach(cleanup)

describe('lifecycle mapping', () => {
  it('queued: only the queue step is current', () => {
    expect(states({ status: 'queued', stage: null, started_at: null })).toEqual([
      'queued:current',
      'preparing:pending',
      'static_analysis:pending',
      'ai_review:pending',
      'saving:pending',
    ])
  })

  it('running: earlier steps done, the worker stage current, later ones pending', () => {
    expect(states({ stage: 'static_analysis' })).toEqual([
      'queued:done',
      'preparing:done',
      'static_analysis:current',
      'ai_review:pending',
      'saving:pending',
    ])
    expect(states({ stage: 'starting' })[1]).toBe('preparing:current')
  })

  it('omits the LLM step when no LLM review was requested', () => {
    expect(states({ use_ai: false, stage: 'saving' })).toEqual([
      'queued:done',
      'preparing:done',
      'static_analysis:done',
      'saving:current',
    ])
  })

  it('an unknown stage marks nothing as current and is named as-is', () => {
    expect(
      states({ stage: 'indexing_symbols' })
        .slice(1)
        .every((s) => s.endsWith(':pending')),
    ).toBe(true)
    expect(statusLine({ status: 'running', stage: 'indexing_symbols' })).toBe(
      'Running: indexing symbols',
    )
  })

  it('failed: does not guess which step failed', () => {
    expect(states({ status: 'failed', stage: null })).toEqual(['queued:done', 'failed:failed'])
  })

  it('completed: every step done', () => {
    expect(states({ status: 'completed', stage: null }).every((s) => s.endsWith(':done'))).toBe(
      true,
    )
  })

  it('formats elapsed time without a percentage', () => {
    expect([formatElapsed(42_000), formatElapsed(65_000), formatElapsed(-5)]).toEqual([
      '42s',
      '1m 05s',
      '0s',
    ])
  })
})

describe('rendering', () => {
  it('announces the current stage and marks it for assistive technology', () => {
    render(<ReviewProgress review={review({ stage: 'ai_review' })} now={T0 + 75_000} />)
    expect(screen.getByRole('status')).toHaveTextContent('LLM review')
    const list = screen.getByRole('list', { name: 'Review progress' })
    const current = within(list)
      .getAllByRole('listitem')
      .find((li) => li.getAttribute('aria-current') === 'step')
    expect(current).toHaveTextContent('LLM review, in progress')
    expect(within(list).getByText(/Static analysis/)).toHaveTextContent('completed')
    expect(screen.getByText('Elapsed 1m 15s')).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('shows how long a queued review has waited', () => {
    render(
      <ReviewProgress
        review={review({ status: 'queued', stage: null, started_at: null })}
        now={T0 + 10_000}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Waiting for a worker')
    expect(screen.getByText('Waiting 20s')).toBeInTheDocument()
  })

  it('failed: shows the failure step and the run time from the server timestamps', () => {
    render(
      <ReviewProgress
        review={review({ status: 'failed', stage: null, finished_at: '2026-10-25T10:00:09' })}
        now={T0 + 999_000}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Review failed')
    expect(screen.getByText(/Stopped with an error/)).toHaveTextContent('failed')
    expect(screen.getByText('Ran for 9s')).toBeInTheDocument()
  })
})
