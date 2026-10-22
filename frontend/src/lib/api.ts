import type {
  ChangedFile,
  FileContent,
  Finding,
  PullDetail,
  PullSummary,
  Repository,
  Review,
  SearchResponse,
  ServerSettings,
  TestSuggestion,
  User,
  Verdict,
} from './types'

export class ApiError extends Error {
  status: number
  requestId?: string
  constructor(status: number, message: string, requestId?: string) {
    super(message)
    this.status = status
    this.requestId = requestId
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'x-devpilot-csrf': '1' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['content-type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'Cannot reach the DevPilot API. Is the backend running?')
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`
    throw new ApiError(res.status, detail, data.request_id)
  }
  return data as T
}

const q = (params: Record<string, string | string[] | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => s.append(k, x))
    else if (v !== undefined) s.set(k, v)
  }
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const api = {
  me: () => request<User>('GET', '/api/auth/me'),
  login: (email: string, password: string) =>
    request<User>('POST', '/api/auth/login', { email, password }),
  register: (email: string, password: string) =>
    request<User>('POST', '/api/auth/register', { email, password }),
  logout: () => request<void>('POST', '/api/auth/logout'),
  settings: () => request<ServerSettings>('GET', '/api/settings'),

  repositories: () => request<Repository[]>('GET', '/api/repositories'),
  repository: (id: number) => request<Repository>('GET', `/api/repositories/${id}`),
  importArchive: (name: string, file: File) => {
    const fd = new FormData()
    fd.set('name', name)
    fd.set('file', file)
    return request<Repository>('POST', '/api/repositories/archive', fd)
  },
  importLocal: (name: string, path: string) =>
    request<Repository>('POST', '/api/repositories/local', { name, path }),
  importGithub: (full_name: string, branch: string) =>
    request<Repository>('POST', '/api/repositories/github', { full_name, branch }),
  updateRepository: (id: number, patch: { ai_review_allowed?: boolean }) =>
    request<Repository>('PATCH', `/api/repositories/${id}`, patch),
  deleteRepository: (id: number) => request<void>('DELETE', `/api/repositories/${id}`),
  search: (id: number, query: string, mode: 'text' | 'identifier') =>
    request<SearchResponse>('GET', `/api/repositories/${id}/search${q({ q: query, mode })}`),
  repoFile: (id: number, path: string) =>
    request<FileContent>('GET', `/api/repositories/${id}/file${q({ path })}`),

  reviews: (repoId: number) => request<Review[]>('GET', `/api/repositories/${repoId}/reviews`),
  createReview: (
    repoId: number,
    body: {
      kind: Review['kind']
      base_ref?: string
      head_ref?: string
      pr_number?: number
      use_ai: boolean
    },
  ) => request<Review>('POST', `/api/repositories/${repoId}/reviews`, body),
  review: (id: number) => request<Review>('GET', `/api/reviews/${id}`),
  findings: (id: number) => request<Finding[]>('GET', `/api/reviews/${id}/findings`),
  changedFiles: (id: number) => request<ChangedFile[]>('GET', `/api/reviews/${id}/changed-files`),
  testSuggestions: (id: number) =>
    request<TestSuggestion[]>('GET', `/api/reviews/${id}/test-suggestions`),
  reviewFile: (id: number, path: string) =>
    request<FileContent>('GET', `/api/reviews/${id}/file${q({ path })}`),
  feedback: (findingId: number, verdict: Verdict) =>
    request<void>('PUT', `/api/findings/${findingId}/feedback`, { verdict }),

  githubStatus: () =>
    request<{
      configured: boolean
      connected: boolean
      login: string | null
      scopes: string | null
      install_url: string | null
    }>('GET', '/api/github/status'),
  githubRepos: () =>
    request<{ full_name: string; private: boolean; default_branch: string; updated_at: string }[]>(
      'GET',
      '/api/github/repos',
    ),
  githubBranches: (full_name: string) =>
    request<{ default_branch: string; branches: { name: string; sha: string }[] }>(
      'GET',
      `/api/github/repos/${full_name.split('/').map(encodeURIComponent).join('/')}/branches`,
    ),
  disconnectGithub: () => request<void>('DELETE', '/api/github/account'),
  pulls: (repoId: number) => request<PullSummary[]>('GET', `/api/repositories/${repoId}/pulls`),
  pull: (repoId: number, n: number) =>
    request<PullDetail>('GET', `/api/repositories/${repoId}/pulls/${n}`),
}
