import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { User } from '../lib/types'
import { Layout } from './Layout'

describe('Layout top bar', () => {
  it('drops the wordmark below 640px so the bar fits a 375px phone, keeping Sign out', () => {
    vi.spyOn(api, 'settings').mockReturnValue(new Promise(() => {}))
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Layout user={{ id: 1, email: 'a@example.com' } as User}>page</Layout>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const bar = within(screen.getByRole('banner'))
    expect(bar.getByRole('link', { name: 'DevPilot, repositories' })).toBeInTheDocument()
    expect(bar.getByText('DevPilot')).toHaveClass('hidden', 'sm:inline')
    expect(bar.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    // The desktop sidebar keeps its full wordmark.
    const sidebar = within(screen.getByRole('complementary'))
    expect(sidebar.getByText('DevPilot')).not.toHaveClass('hidden')
  })
})
