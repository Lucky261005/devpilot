import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { Repository } from '../lib/types'
import { RepositoryPage } from './RepositoryPage'

const pending = () => new Promise<never>(() => {})

describe('RepositoryPage header', () => {
  it('shows index facts with the repository identity, leaving the side card to LLM access', async () => {
    vi.spyOn(api, 'repository').mockResolvedValue({
      id: 7,
      name: 'payments',
      source_type: 'archive',
      source_ref: 'payments.zip',
      source_branch: null,
      source_sha: null,
      index_status: 'ready',
      index_error: null,
      indexed_at: new Date().toISOString(),
      file_count: 1,
      total_bytes: 2048,
      skipped: {},
      ai_review_allowed: false,
    } as unknown as Repository)
    vi.spyOn(api, 'settings').mockImplementation(pending)
    vi.spyOn(api, 'reviews').mockImplementation(pending)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/repositories/7']}>
          <Routes>
            <Route path="/repositories/:id" element={<RepositoryPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const header = within(await screen.findByRole('banner'))
    expect(header.getByText(/1 file · 2\.0 KB · indexed/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'LLM access' })).toBeInTheDocument()
    expect(screen.queryByText('Files indexed')).not.toBeInTheDocument()
    expect(document.title).toBe('payments | DevPilot')
  })
})
