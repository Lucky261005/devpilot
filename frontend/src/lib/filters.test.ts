import { describe, expect, it } from 'vitest'
import { filterFindings } from '../pages/ReviewPage'
import type { Finding } from './types'

const f = (
  id: number,
  severity: Finding['severity'],
  category: string,
  source: Finding['source'],
) => ({ id, severity, category, source }) as Finding

describe('filterFindings', () => {
  const all = [
    f(1, 'high', 'security', 'static'),
    f(2, 'low', 'logic', 'ai'),
    f(3, 'high', 'logic', 'ai'),
  ]
  const none = {
    severity: new Set<string>(),
    category: new Set<string>(),
    source: new Set<string>(),
  }

  it('returns everything with no filters', () => {
    expect(filterFindings(all, none).map((x) => x.id)).toEqual([1, 2, 3])
  })
  it('ANDs across dimensions and ORs within one', () => {
    expect(
      filterFindings(all, { ...none, severity: new Set(['high']), source: new Set(['ai']) }).map(
        (x) => x.id,
      ),
    ).toEqual([3])
    expect(
      filterFindings(all, { ...none, category: new Set(['logic', 'security']) }).map((x) => x.id),
    ).toEqual([1, 2, 3])
  })
})
