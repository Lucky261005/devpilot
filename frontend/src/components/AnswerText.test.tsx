import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CodeRange } from '../lib/types'
import { AnswerText } from './AnswerText'

const known: CodeRange[] = [{ path: 'inventory/pricing.py', start_line: 4, end_line: 8 }]

function show(answer: string, onOpen = vi.fn()) {
  const view = render(<AnswerText answer={answer} known={known} onOpen={onOpen} />)
  return { ...view, onOpen }
}

afterEach(cleanup)

describe('AnswerText', () => {
  it('renders headings, paragraphs, lists, bold and inline code', () => {
    const { container } = show(
      '## Summary\nThe **discount** is applied in `apply_discount`.\n\n- first\n- second\n\n1. one\n2. two',
    )
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument()
    expect(screen.getByText('discount').tagName).toBe('STRONG')
    expect(screen.getByText('apply_discount').tagName).toBe('CODE')
    expect(container.querySelectorAll('ul > li')).toHaveLength(2)
    expect(container.querySelectorAll('ol > li')).toHaveLength(2)
  })

  it('keeps fenced code verbatim in a horizontally scrollable block', () => {
    const { container } = show('Example:\n```python\ndef f(x):\n    return x  # **not bold**\n```')
    const pre = container.querySelector('pre')!
    expect(pre).toHaveClass('overflow-x-auto')
    expect(pre.textContent).toBe('def f(x):\n    return x  # **not bold**')
    expect(pre.querySelector('strong')).toBeNull()
  })

  it('turns a cited file reference into a button that opens those lines', async () => {
    const { onOpen } = show('See `inventory/pricing.py:5-6` and `unknown.py:1`.')
    await userEvent.click(screen.getByRole('button', { name: 'inventory/pricing.py:5-6' }))
    expect(onOpen).toHaveBeenCalledWith({
      path: 'inventory/pricing.py',
      start_line: 5,
      end_line: 6,
    })
    expect(screen.queryByRole('button', { name: 'unknown.py:1' })).not.toBeInTheDocument()
  })

  it('shows HTML from the model as text, never as markup', () => {
    const { container } = show(
      '<img src=x onerror="alert(1)"> <script>alert(2)</script> **<b>x</b>**',
    )
    expect(container.querySelector('img, script, b')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">')
  })
})
