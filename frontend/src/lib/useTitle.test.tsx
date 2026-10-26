import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { useTitle } from './useTitle'

function Page({ title }: { title: string | null }) {
  useTitle(title)
  return (
    <nav>
      <Link to="/">home</Link>
      <Link to="/settings">settings</Link>
    </nav>
  )
}

afterEach(cleanup)

describe('useTitle', () => {
  it('follows client-side navigation without a reload', async () => {
    render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<Page title="Repositories" />} />
          <Route path="/settings" element={<Page title="Settings" />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(document.title).toBe('Repositories | DevPilot')
    await userEvent.click(screen.getByRole('link', { name: 'settings' }))
    expect(document.title).toBe('Settings | DevPilot')
    await userEvent.click(screen.getByRole('link', { name: 'home' }))
    expect(document.title).toBe('Repositories | DevPilot')
  })

  it('updates when the page title changes, and null restores the landing title', () => {
    const { rerender } = render(<Page title="Repository" />, { wrapper: MemoryRouter })
    expect(document.title).toBe('Repository | DevPilot')
    rerender(<Page title="payments" />)
    expect(document.title).toBe('payments | DevPilot')
    rerender(<Page title={null} />)
    expect(document.title).toBe('DevPilot: code review made provable')
  })
})
