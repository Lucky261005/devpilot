export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type Verdict = 'useful' | 'incorrect' | 'duplicate' | 'not_actionable'
export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'info']
export const SOURCE_LABEL = {
  archive: 'ZIP archive',
  local: 'Local Git',
  github: 'GitHub',
} as const

export interface User {
  id: number
  email: string
}

export interface Repository {
  id: number
  name: string
  source_type: 'archive' | 'local' | 'github'
  source_ref: string
  ai_review_allowed: boolean
  index_status: 'pending' | 'indexing' | 'ready' | 'failed'
  index_error: string | null
  indexed_at: string | null
  file_count: number
  total_bytes: number
  skipped: Record<string, number>
  created_at: string
}

export interface AiStats {
  status: 'not_requested' | 'skipped' | 'failed' | 'completed'
  reason?: string
  model?: string
  summary?: string
  returned?: number
  accepted?: number
  rejected?: { title: string; reason: string }[]
  input_tokens?: number | null
  output_tokens?: number | null
  latency_ms?: number
  files_in_context?: number
  files_omitted?: string[]
}

export interface Review {
  id: number
  repository_id: number
  kind: 'full' | 'diff' | 'pull_request'
  base_ref: string | null
  head_ref: string | null
  use_ai: boolean
  status: 'queued' | 'running' | 'completed' | 'failed'
  stage: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  severity_counts: Partial<Record<Severity, number>>
  pr_number: number | null
  pr_title: string | null
  stats: {
    timings?: Record<string, number>
    analyzers?: Record<
      string,
      { version?: string; status?: string; error?: string; files?: number; count?: number }
    >
    ai?: AiStats
    files_reviewed?: number
    duplicates_dropped?: number
    findings?: { static: number; ai: number }
    base_sha?: string
    head_sha?: string
  }
}

export interface Finding {
  id: number
  review_id: number
  source: 'static' | 'ai'
  analyzer: string
  analyzer_version: string
  rule_id: string | null
  title: string
  description: string
  severity: Severity
  category: string
  path: string
  start_line: number
  end_line: number
  evidence: string
  reasoning: string | null
  suggested_fix: string | null
  suggested_test: string | null
  confidence: 'low' | 'medium' | 'high' | null
  limitations: string | null
  doc_url: string | null
  my_feedback: Verdict | null
}

export interface ChangedFile {
  path: string
  status: string
  additions: number
  deletions: number
  patch: string | null
}

export interface TestSuggestion {
  id: number
  source: 'static' | 'ai'
  target: string
  path: string
  start_line: number
  rationale: string
  test_code: string
}

export interface FileContent {
  path: string
  language: string
  content: string
  line_count: number
}

export interface SearchResponse {
  query: string
  mode: string
  results: { path: string; line: number; text: string; language: string }[]
}

export interface ServerSettings {
  llm: { provider: string | null; model: string | null; configured: boolean; local: boolean }
  github: { configured: boolean; scopes: string }
  limits: {
    max_upload_bytes: number
    max_repo_bytes: number
    max_file_bytes: number
    reviews_per_hour: number
  }
  local_import_enabled: boolean
  retention_days: number
}

export interface PullSummary {
  number: number
  title: string
  state: string
  author: string
  url: string
  base_ref: string
  head_ref: string
  updated_at: string | null
  draft: boolean
}

export interface PullDetail extends PullSummary {
  files: {
    path: string
    status: string
    additions: number
    deletions: number
    patch: string | null
  }[]
}
