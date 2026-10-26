import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../lib/api'
import type { RecentReview, Repository } from '../lib/types'
import { RepositoriesPage } from './RepositoriesPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RepositoriesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const repo = {
  id: 1,
  name: 'payments',
  source_type: 'archive',
  source_ref: 'payments.zip',
  index_status: 'ready',
  file_count: 3,
  total_bytes: 100,
  ai_review_allowed: false,
  created_at: '2026-10-25T10:00:00',
} as Repository

const row = (over: Partial<RecentReview>): RecentReview => ({
  id: 1,
  repository_id: 1,
  repository_name: 'payments',
  kind: 'full',
  use_ai: false,
  status: 'completed',
  stage: null,
  created_at: '2026-10-25T10:00:00',
  finished_at: '2026-10-25T10:01:00',
  severity_counts: {},
  pr_number: null,
  ...over,
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('RepositoriesPage empty state', () => {
  it('lets the long sample path wrap so it cannot widen a 375px page', async () => {
    vi.spyOn(api, 'repositories').mockResolvedValue([])
    const recent = vi.spyOn(api, 'recentReviews')
    renderPage()
    const path = await screen.findByText('fixtures/sample_repositories/inventory_service')
    expect(path).toHaveClass('break-all')
    expect(recent).not.toHaveBeenCalled() // no repositories, so no recent-reviews section
    expect(document.title).toBe('Repositories | DevPilot')
  })
})

describe('Recent reviews', () => {
  it('links each review and labels completed, running and failed distinctly', async () => {
    vi.spyOn(api, 'repositories').mockResolvedValue([repo])
    vi.spyOn(api, 'recentReviews').mockResolvedValue([
      row({ id: 9, status: 'running', stage: 'static_analysis', finished_at: null }),
      row({ id: 8, status: 'failed', repository_name: 'billing' }),
      row({ id: 7, kind: 'pull_request', pr_number: 12, use_ai: true }),
    ])
    renderPage()
    const section = (await screen.findByRole('heading', { name: 'Recent reviews' })).closest(
      'section',
    )!
    const links = await within(section).findAllByRole('link')
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/reviews/9',
      '/reviews/8',
      '/reviews/7',
    ])
    expect(links[0]).toHaveTextContent(/running/i)
    expect(links[1]).toHaveTextContent('billing')
    expect(links[1]).toHaveTextContent(/failed/i)
    expect(links[2]).toHaveTextContent('PR #12 · +LLM')
    expect(links[2]).toHaveTextContent(/completed/i)
  })

  it('explains how to start when there are no reviews yet', async () => {
    vi.spyOn(api, 'repositories').mockResolvedValue([repo])
    vi.spyOn(api, 'recentReviews').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/No reviews yet/)).toHaveTextContent('Start review')
  })

  it('shows an error without hiding the repository list', async () => {
    vi.spyOn(api, 'repositories').mockResolvedValue([repo])
    vi.spyOn(api, 'recentReviews').mockRejectedValue(new ApiError(500, 'Internal server error.'))
    renderPage()
    expect(await screen.findByText('Recent reviews unavailable')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /payments\.zip/ })).toBeInTheDocument()
  })
})
