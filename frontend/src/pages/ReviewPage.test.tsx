import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { Review } from '../lib/types'
import { ReviewPage } from './ReviewPage'

// A whole-repository review shaped like the live run that prompted this test: one analyzer
// finding, an LLM that returned nothing after seeing only part of the repository.
const review = {
  id: 3,
  repository_id: 2,
  kind: 'full',
  base_ref: null,
  head_ref: null,
  use_ai: true,
  status: 'completed',
  stage: null,
  error: null,
  created_at: '2026-10-26T10:00:00',
  started_at: '2026-10-26T10:00:00',
  finished_at: '2026-10-26T10:02:00',
  severity_counts: {},
  pr_number: null,
  pr_title: null,
  stats: {
    files_reviewed: 4,
    findings: { static: 1, ai: 0 },
    analyzers: {},
    ai: {
      status: 'completed',
      model: 'qwen2.5-coder:3b',
      returned: 0,
      accepted: 0,
      files_in_context: 2,
      files_partial: ['app.py'],
      files_omitted: [],
      summary: 'No actionable defects found.',
    },
  },
} as unknown as Review

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderReview(findings: unknown[] = []) {
  vi.spyOn(api, 'review').mockResolvedValue(review)
  vi.spyOn(api, 'findings').mockResolvedValue(findings as never)
  vi.spyOn(api, 'testSuggestions').mockResolvedValue([])
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/reviews/3']}>
        <Routes>
          <Route path="/reviews/:id" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewPage result summary', () => {
  it('separates analyzer and LLM results and shows what the model saw', async () => {
    renderReview()
    expect(await screen.findByText(/1 analyzer finding \(rule-based\)/)).toHaveTextContent(
      '0 LLM findings (model suggestions)',
    )
    expect(
      screen.getByText(/The model saw 2 of 4 reviewed files; 1 only as excerpts/),
    ).toBeVisible()
    expect(screen.getByText(/not a verification/)).toBeInTheDocument()
  })

  it('does not present an empty result as proof that the code is defect-free', async () => {
    renderReview()
    expect(await screen.findByText(/does not prove the code is free of defects/)).toBeVisible()
  })
})
