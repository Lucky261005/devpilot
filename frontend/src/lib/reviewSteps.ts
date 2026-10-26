import type { Review } from './types'

export type StepState = 'done' | 'current' | 'pending' | 'failed'
export interface Step {
  key: string
  label: string
  state: StepState
}

// The worker's real stages, in order (backend/app/services/review.py `set_stage`). `starting` is set
// by the worker the moment it claims the job, before `preparing`.
const STAGES: { key: string; label: string; stages: string[]; ai?: boolean }[] = [
  { key: 'preparing', label: 'Preparing code', stages: ['starting', 'preparing'] },
  { key: 'static_analysis', label: 'Static analysis', stages: ['static_analysis'] },
  { key: 'ai_review', label: 'LLM review', stages: ['ai_review'], ai: true },
  { key: 'saving', label: 'Saving findings', stages: ['saving'] },
]

/** Steps for a review, derived only from its status and stage; no invented progress. */
export function reviewSteps(review: Pick<Review, 'status' | 'stage' | 'use_ai'>): Step[] {
  const stages = STAGES.filter((s) => !s.ai || review.use_ai)
  if (review.status === 'queued') {
    return [
      { key: 'queued', label: 'Queued', state: 'current' },
      ...stages.map((s) => ({ key: s.key, label: s.label, state: 'pending' as const })),
    ]
  }
  if (review.status === 'completed') {
    return [
      { key: 'queued', label: 'Queued', state: 'done' },
      ...stages.map((s) => ({ key: s.key, label: s.label, state: 'done' as const })),
    ]
  }
  const queued: Step = { key: 'queued', label: 'Queued', state: 'done' }
  if (review.status === 'failed') {
    // The worker clears `stage` when a job ends, so which step failed is not known here.
    return [queued, { key: 'failed', label: 'Stopped with an error', state: 'failed' }]
  }
  const current = stages.findIndex((s) => s.stages.includes(review.stage ?? ''))
  return [
    queued,
    ...stages.map((s, i) => ({
      key: s.key,
      label: s.label,
      // An unknown (newer) stage marks nothing as current rather than guessing.
      state:
        current < 0
          ? ('pending' as const)
          : i < current
            ? ('done' as const)
            : i === current
              ? ('current' as const)
              : ('pending' as const),
    })),
  ]
}

export function parseTime(iso: string) {
  return new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()
}

export function formatElapsed(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

export function statusLine(review: Pick<Review, 'status' | 'stage'>) {
  if (review.status === 'queued') return 'Waiting for a worker'
  if (review.status === 'failed') return 'Review failed'
  if (review.status === 'completed') return 'Review completed'
  const known = STAGES.find((s) => s.stages.includes(review.stage ?? ''))
  return known ? known.label : `Running: ${(review.stage ?? 'starting').replaceAll('_', ' ')}`
}
