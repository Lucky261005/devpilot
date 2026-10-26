import { describe, expect, it } from 'vitest'
import { suggestionKind } from './testSuggestions'

describe('suggestionKind', () => {
  it('treats empty code as a test gap', () => {
    expect(suggestionKind('')).toBe('gap')
    expect(suggestionKind('  \n')).toBe('gap')
  })

  it('flags stored templates with placeholders as incomplete scaffolds', () => {
    expect(suggestionKind('def test_a():\n    x = ...  # TODO: input\n')).toBe('scaffold')
    expect(suggestionKind('def test_a():\n    assert f(1) == ...\n')).toBe('scaffold')
    expect(suggestionKind('def test_a():\n    ...\n')).toBe('scaffold')
  })

  it('accepts complete test code, including strings that merely contain dots', () => {
    expect(suggestionKind('def test_add():\n    assert add(2, 3) == 5\n')).toBe('test')
    expect(suggestionKind('def test_s():\n    assert fmt("a...b") == "a...b"\n')).toBe('test')
  })
})
