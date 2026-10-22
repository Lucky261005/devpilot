import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../lib/api'
import { CodeView, DiffView } from './CodeView'
import { ErrorBox, SourceBadge, formatBytes } from './ui'

describe('ui', () => {
  it('labels LLM findings as hypotheses', () => {
    render(<SourceBadge source="ai" />)
    expect(screen.getByText('LLM hypothesis')).toHaveAttribute(
      'title',
      expect.stringContaining('Verify'),
    )
  })
  it('shows the request id for API errors', () => {
    render(<ErrorBox error={new ApiError(500, 'Internal server error.', 'abc123')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Request ID: abc123')
  })
  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
  })
  it('highlights the cited line range', () => {
    const { container } = render(<CodeView content={'a\nb\nc\nd'} highlight={[2, 3]} path="x.py" />)
    const hl = [...container.querySelectorAll('tr.bg-hl')].map((r) => r.getAttribute('data-line'))
    expect(hl).toEqual(['2', '3'])
  })
  it('numbers diff lines on the correct side', () => {
    const { container } = render(<DiffView patch={'@@ -10,2 +10,2 @@\n ctx\n-old\n+new'} />)
    const rows = [...container.querySelectorAll('tbody tr')].map((r) =>
      [...r.querySelectorAll('td')].map((td) => td.textContent),
    )
    expect(rows[1]).toEqual(['10', '10', ' ctx'])
    expect(rows[2]).toEqual(['11', '', '-old'])
    expect(rows[3]).toEqual(['', '11', '+new'])
  })
})
