import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { ServerSettings } from '../lib/types'
import { LoginPage } from './LoginPage'

vi.mock('../lib/scanLine', () => ({ useScanLine: () => undefined })) // scroll effects need no DOM here

function renderWith(registration: ServerSettings['registration']) {
  vi.spyOn(api, 'settings').mockResolvedValue({ registration } as ServerSettings)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('registration controls follow the server policy', () => {
  it('open: offers sign-up without an invite code', async () => {
    renderWith('open')
    await userEvent.click(await screen.findByRole('button', { name: 'Create one' }))
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Invite code/ })).not.toBeInTheDocument()
  })

  it('invite: asks for an invite code and sends it', async () => {
    renderWith('invite')
    const register = vi.spyOn(api, 'register').mockResolvedValue({ detail: 'ok' })
    vi.spyOn(api, 'login').mockResolvedValue({ id: 1, email: 'a@example.com' })
    await userEvent.click(await screen.findByRole('button', { name: 'Create one' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Email' }), 'a@example.com')
    await userEvent.type(document.querySelector('input[type=password]')!, 'long-enough-pw')
    await userEvent.type(screen.getByRole('textbox', { name: /Invite code/ }), 'the-code')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(register).toHaveBeenCalledWith('a@example.com', 'long-enough-pw', 'the-code')
  })

  it('closed: hides registration but keeps sign-in', async () => {
    renderWith('closed')
    await screen.findByRole('form', { name: 'Sign in' })
    await vi.waitFor(() => expect(api.settings).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Create one' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Invite code/ })).not.toBeInTheDocument()
  })
})
