// Mirrors backend/app/services/findings.py PLACEHOLDER: `x = ...`, `== ...`, `f(...)`, a bare `...`
// line or a TODO marks a template, not a runnable test (older reviews stored such scaffolds).
const PLACEHOLDER = /\bTODO\b|(?:=|\(|,)\s*\.\.\.|^\s*\.\.\.\s*$/m

export type SuggestionKind = 'test' | 'gap' | 'scaffold'

export function suggestionKind(code: string): SuggestionKind {
  if (!code.trim()) return 'gap'
  return PLACEHOLDER.test(code) ? 'scaffold' : 'test'
}
