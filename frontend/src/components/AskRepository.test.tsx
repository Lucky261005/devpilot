import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../lib/api'
import type { AskResponse } from '../lib/types'
import { AskRepository } from './AskRepository'

const base: AskResponse = {
  status: 'answered',
  answer: 'apply_discount in inventory/pricing.py computes it.',
  confidence: 'high',
  citations: [
    { path: 'inventory/pricing.py', start_line: 4, end_line: 8, note: 'the calculation' },
  ],
  unknowns: ['How prices are rounded'],
  sources: [{ path: 'inventory/pricing.py', start_line: 1, end_line: 20 }],
  message: null,
  model: 'claude-test',
}

function renderAsk() {
  vi.spyOn(api, 'repoFile').mockResolvedValue({
    path: 'inventory/pricing.py',
    language: 'python',
    content: 'def apply_discount(price, quantity):\n    return price\n',
    line_count: 2,
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <AskRepository repoId={7} />
    </QueryClientProvider>,
  )
}

async function askQuestion(text = 'Where is the discount applied?') {
  await userEvent.type(screen.getByLabelText('Ask about this repository'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('repository Q&A', () => {
  it('sends the question for this repository and shows the answer with its evidence', async () => {
    const ask = vi.spyOn(api, 'ask').mockResolvedValue(base)
    renderAsk()
    await askQuestion()
    expect(ask).toHaveBeenCalledWith(7, 'Where is the discount applied?')
    expect(await screen.findByText(base.answer!)).toBeInTheDocument()
    expect(screen.getByText('high confidence')).toBeInTheDocument()
    expect(screen.getByText('the calculation')).toBeInTheDocument()
    expect(screen.getByText('How prices are rounded')).toBeInTheDocument()
    expect(screen.getByText('inventory/pricing.py:4-8')).toBeInTheDocument()
  })

  it('shows the honest message and matching files when no answer was generated', async () => {
    vi.spyOn(api, 'ask').mockResolvedValue({
      ...base,
      status: 'no_provider',
      answer: null,
      confidence: null,
      citations: [],
      unknowns: [],
      message: 'No LLM provider is configured. These files match your question.',
    })
    renderAsk()
    await askQuestion()
    expect(await screen.findByText(/No LLM provider is configured/)).toBeInTheDocument()
    expect(screen.getByText('Matching code')).toBeInTheDocument()
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument()
  })

  it('shows API errors such as the quota being reached', async () => {
    vi.spyOn(api, 'ask').mockRejectedValue(
      new ApiError(429, 'Review limit reached. Try again later.'),
    )
    renderAsk()
    await askQuestion()
    expect(await screen.findByText('Review limit reached. Try again later.')).toBeInTheDocument()
  })

  it('does not send questions shorter than three characters', async () => {
    const ask = vi.spyOn(api, 'ask').mockResolvedValue(base)
    renderAsk()
    await userEvent.type(screen.getByLabelText('Ask about this repository'), 'hi')
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    expect(ask).not.toHaveBeenCalled()
  })
})
