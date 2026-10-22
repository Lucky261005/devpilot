import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CodeView, DiffView } from '../components/CodeView'
import {
  Button,
  ConfirmDialog,
  Card,
  Empty,
  ErrorBox,
  Field,
  PageHeader,
  Panel,
  Pill,
  SeverityBadge,
  Spinner,
  StatusBadge,
  Tabs,
  formatBytes,
  inputClass,
  timeAgo,
} from '../components/ui'
import { api } from '../lib/api'
import { SEVERITIES, SOURCE_LABEL, type Repository, type Review } from '../lib/types'

function AiConsent({ repo }: { repo: Repository }) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (allowed: boolean) => api.updateRepository(repo.id, { ai_review_allowed: allowed }),
    onSuccess: (r) => qc.setQueryData(['repo', repo.id], r),
  })
  const llm = settings.data?.llm
  return (
    <div className="space-y-2 text-sm">
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={repo.ai_review_allowed}
          disabled={m.isPending}
          onChange={(e) => m.mutate(e.target.checked)}
        />
        <span>
          <span className="font-medium">Allow LLM review for this repository</span>
          <span className="block text-muted">
            When a review requests it, excerpts of changed files (up to the context limit) are sent
            to{' '}
            {llm?.configured ? (
              <b>
                {llm.provider} ({llm.model})
              </b>
            ) : (
              'the configured provider'
            )}
            {llm?.local ? ', a model running on this server; the code does not leave it' : ''}.
            Secret files are never included. Nothing is sent unless this box is checked.
          </span>
        </span>
      </label>
      {settings.data && !llm?.configured ? (
        <p className="text-xs text-warn">
          No LLM provider is configured on this server, so reviews will run analyzers only.
        </p>
      ) : null}
      {m.error ? <ErrorBox error={m.error} /> : null}
    </div>
  )
}

function StartReview({ repo, prNumber }: { repo: Repository; prNumber?: number }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const kinds: Review['kind'][] =
    repo.source_type === 'local'
      ? ['diff', 'full']
      : repo.source_type === 'github'
        ? ['full']
        : ['full']
  const [kind, setKind] = useState<Review['kind']>(prNumber ? 'pull_request' : kinds[0])
  const [base, setBase] = useState('HEAD~1')
  const [head, setHead] = useState('HEAD')
  const [useAi, setUseAi] = useState(repo.ai_review_allowed)
  const m = useMutation({
    mutationFn: () =>
      api.createReview(repo.id, {
        kind,
        use_ai: useAi && repo.ai_review_allowed,
        ...(kind === 'diff' ? { base_ref: base, head_ref: head } : {}),
        ...(kind === 'pull_request' ? { pr_number: prNumber } : {}),
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['reviews', repo.id] })
      navigate(`/reviews/${r.id}`)
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    m.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      {!prNumber ? (
        <fieldset className="grid gap-2 sm:grid-cols-2">
          <legend className="sr-only">Review scope</legend>
          {kinds.map((k) => (
            <label
              key={k}
              className={`flex cursor-pointer items-start gap-3 rounded-control border px-3.5 py-3 text-sm ${
                kind === k ? 'border-accent bg-accent-soft' : 'border-line-strong hover:bg-subtle'
              }`}
            >
              <input
                type="radio"
                name="kind"
                className="mt-0.5 accent-[var(--accent)]"
                checked={kind === k}
                onChange={() => setKind(k)}
              />
              <span>
                <span className="block font-semibold">
                  {k === 'diff' ? 'Compare two refs' : 'Whole repository'}
                </span>
                <span className="mt-0.5 block text-xs text-muted">
                  {k === 'diff' ? 'Only lines changed between the refs' : 'Every indexed file'}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="text-sm">
          Review pull request <b>#{prNumber}</b> (changed lines only).
        </p>
      )}
      {kind === 'diff' ? (
        <div className="grid grid-cols-2 gap-4">
          <Field label="Base ref">
            <input
              className={`${inputClass} font-mono`}
              value={base}
              onChange={(e) => setBase(e.target.value)}
              required
            />
          </Field>
          <Field label="Head ref">
            <input
              className={`${inputClass} font-mono`}
              value={head}
              onChange={(e) => setHead(e.target.value)}
              required
            />
          </Field>
        </div>
      ) : null}
      <label
        className={`flex items-center gap-2.5 text-sm ${repo.ai_review_allowed ? '' : 'text-muted'}`}
      >
        <input
          className="h-4 w-4 accent-[var(--accent)]"
          type="checkbox"
          checked={useAi && repo.ai_review_allowed}
          disabled={!repo.ai_review_allowed}
          onChange={(e) => setUseAi(e.target.checked)}
        />
        Include LLM review {repo.ai_review_allowed ? '' : '(enable it for this repository first)'}
      </label>
      {m.error ? <ErrorBox error={m.error} title="Could not start review" /> : null}
      <Button variant="primary" type="submit" disabled={m.isPending}>
        {m.isPending ? 'Queuing…' : 'Start review'}
      </Button>
    </form>
  )
}

export function SeverityCounts({ counts }: { counts: Review['severity_counts'] }) {
  const present = SEVERITIES.filter((s) => counts[s])
  if (!present.length) return <span className="text-xs text-faint">No findings</span>
  return (
    <span className="flex flex-wrap gap-2">
      {present.map((s) => (
        <span key={s} className="flex items-center gap-1 text-xs font-medium tabular-nums">
          <SeverityBadge severity={s} />
          {counts[s]}
        </span>
      ))}
    </span>
  )
}

function ReviewHistory({ repoId }: { repoId: number }) {
  const reviews = useQuery({
    queryKey: ['reviews', repoId],
    queryFn: () => api.reviews(repoId),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.status === 'queued' || r.status === 'running') ? 2000 : false,
  })
  if (reviews.isLoading) return <Spinner label="Loading reviews" />
  if (reviews.error) return <ErrorBox error={reviews.error} />
  if (!reviews.data?.length)
    return (
      <div className="p-5">
        <Empty title="No reviews yet">Choose a scope above and start the first review.</Empty>
      </div>
    )
  return (
    <ul className="divide-y divide-line">
      {reviews.data.map((r) => (
        <li key={r.id}>
          <Link
            to={`/reviews/${r.id}`}
            className="group flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 hover:bg-subtle/70"
          >
            <span className="w-10 font-mono text-xs text-faint">#{r.id}</span>
            <span className="min-w-0 flex-1 basis-48 truncate text-sm font-medium group-hover:text-accent">
              {r.kind === 'pull_request'
                ? `PR #${r.pr_number} ${r.pr_title ?? ''}`
                : r.kind === 'diff'
                  ? `${r.base_ref}..${r.head_ref}`
                  : 'Whole repository'}
            </span>
            {r.use_ai ? <Pill tone="ai">+LLM</Pill> : null}
            <StatusBadge status={r.status} stage={r.stage} />
            {r.status === 'completed' ? <SeverityCounts counts={r.severity_counts} /> : null}
            <span className="text-xs text-faint sm:w-24 sm:text-right">
              {timeAgo(r.created_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function Search({ repoId }: { repoId: number }) {
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'text' | 'identifier'>('text')
  const [query, setQuery] = useState<{ q: string; mode: typeof mode } | null>(null)
  const [open, setOpen] = useState<{ path: string; line: number } | null>(null)
  const results = useQuery({
    queryKey: ['search', repoId, query],
    queryFn: () => api.search(repoId, query!.q, query!.mode),
    enabled: !!query,
  })
  const file = useQuery({
    queryKey: ['file', repoId, open?.path],
    queryFn: () => api.repoFile(repoId, open!.path),
    enabled: !!open,
  })
  return (
    <div className="space-y-4 p-5">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (input.trim()) setQuery({ q: input.trim(), mode })
        }}
      >
        <input
          aria-label="Search code"
          className={`${inputClass} max-w-md font-mono`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={mode === 'identifier' ? 'function or class name' : 'text in code'}
        />
        <select
          aria-label="Search mode"
          className={`${inputClass} w-auto`}
          value={mode}
          onChange={(e) => setMode(e.target.value as typeof mode)}
        >
          <option value="text">Text</option>
          <option value="identifier">Definition</option>
        </select>
        <Button type="submit">Search</Button>
      </form>
      {results.isFetching ? <Spinner label="Searching" /> : null}
      {results.error ? <ErrorBox error={results.error} /> : null}
      {results.data && !results.data.results.length ? (
        <p className="text-sm text-muted">No matches for “{results.data.query}”.</p>
      ) : null}
      {results.data?.results.length ? (
        <p className="text-xs text-faint">
          {results.data.results.length} matching lines
          {results.data.results.length >= 50 ? ' (first 50)' : ''}
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {results.data?.results.length ? (
          <ul className="max-h-[70vh] divide-y divide-line overflow-auto rounded-control border border-line font-mono text-xs">
            {results.data.results.map((r) => (
              <li key={`${r.path}:${r.line}`}>
                <button
                  className={`block w-full px-3.5 py-2 text-left hover:bg-subtle ${open?.path === r.path && open.line === r.line ? 'bg-accent-soft' : ''}`}
                  onClick={() => setOpen({ path: r.path, line: r.line })}
                >
                  <span className="text-accent">
                    {r.path}:{r.line}
                  </span>
                  <span className="mt-0.5 block truncate text-muted">{r.text.trim()}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {open && file.data ? (
          <div className="overflow-hidden rounded-control border border-line">
            <p className="truncate border-b border-line bg-subtle px-3.5 py-2 font-mono text-xs">
              {open.path}
            </p>
            <CodeView
              content={file.data.content}
              highlight={[open.line, open.line]}
              path={open.path}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}

function Pulls({ repo }: { repo: Repository }) {
  const pulls = useQuery({ queryKey: ['pulls', repo.id], queryFn: () => api.pulls(repo.id) })
  const [selected, setSelected] = useState<number | null>(null)
  const detail = useQuery({
    queryKey: ['pull', repo.id, selected],
    queryFn: () => api.pull(repo.id, selected!),
    enabled: selected !== null,
  })
  if (pulls.isLoading) return <Spinner label="Loading pull requests from GitHub" />
  if (pulls.error)
    return (
      <div className="p-4">
        <ErrorBox error={pulls.error} title="Could not load pull requests" />
      </div>
    )
  if (!pulls.data?.length)
    return (
      <div className="p-4">
        <Empty title="No open pull requests" />
      </div>
    )
  return (
    <div className="grid gap-5 p-5 lg:grid-cols-[320px_1fr]">
      <ul className="divide-y divide-line self-start overflow-hidden rounded-control border border-line">
        {pulls.data.map((p) => (
          <li key={p.number}>
            <button
              onClick={() => setSelected(p.number)}
              className={`block w-full px-3.5 py-2.5 text-left text-sm hover:bg-subtle ${selected === p.number ? 'bg-accent-soft' : ''}`}
            >
              <span className="font-mono text-xs text-muted">#{p.number}</span> {p.title}
              <span className="block text-xs text-muted">
                {p.author} · {p.head_ref} → {p.base_ref}
                {p.draft ? ' · draft' : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="space-y-3">
        {selected === null ? (
          <p className="text-sm text-muted">Select a pull request to inspect its changes.</p>
        ) : null}
        {detail.isLoading ? <Spinner label="Loading changes" /> : null}
        {detail.error ? <ErrorBox error={detail.error} /> : null}
        {detail.data ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-lg font-semibold tracking-tight">
                #{detail.data.number} {detail.data.title}
              </h3>
              <a
                className="text-sm text-accent hover:underline"
                href={detail.data.url}
                target="_blank"
                rel="noreferrer"
              >
                Open on GitHub
              </a>
            </div>
            <Panel className="p-4">
              <StartReview repo={repo} prNumber={detail.data.number} key={detail.data.number} />
            </Panel>
            {detail.data.files.map((f) => (
              <details key={f.path} className="overflow-hidden rounded-control border border-line">
                <summary className="cursor-pointer bg-subtle px-3.5 py-2 font-mono text-xs">
                  {f.path} <span className="text-ok">+{f.additions}</span>{' '}
                  <span className="text-danger">−{f.deletions}</span>
                </summary>
                {f.patch ? (
                  <DiffView patch={f.patch} />
                ) : (
                  <p className="p-3 text-xs text-muted">No textual diff (binary or too large).</p>
                )}
              </details>
            ))}
          </>
        ) : null}
      </div>
    </div>
  )
}

export function RepositoryPage() {
  const id = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'reviews'
  const qc = useQueryClient()
  const navigate = useNavigate()
  const repo = useQuery({ queryKey: ['repo', id], queryFn: () => api.repository(id) })
  const [confirming, setConfirming] = useState(false)
  const del = useMutation({
    mutationFn: () => api.deleteRepository(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['repos'] })
      navigate('/')
    },
  })
  if (repo.isLoading) return <Spinner label="Loading repository" />
  if (repo.error) return <ErrorBox error={repo.error} title="Repository unavailable" />
  const r = repo.data!
  const tabs: { id: string; label: string }[] = [
    { id: 'reviews', label: 'Review history' },
    { id: 'search', label: 'Search code' },
    ...(r.source_type === 'github' ? [{ id: 'pulls', label: 'Pull requests' }] : []),
  ]
  const skipped = Object.entries(r.skipped ?? {})
  return (
    <div>
      <PageHeader
        eyebrow={
          <Link to="/" className="hover:text-fg hover:underline">
            Repositories
          </Link>
        }
        title={r.name}
        meta={
          <>
            <Pill>{SOURCE_LABEL[r.source_type]}</Pill>
            <span className="min-w-0 truncate font-mono text-xs text-faint" title={r.source_ref}>
              {r.source_ref}
            </span>
          </>
        }
        actions={
          <Button variant="danger" disabled={del.isPending} onClick={() => setConfirming(true)}>
            Delete repository
          </Button>
        }
      />
      <ConfirmDialog
        open={confirming}
        title={`Delete ${r.name}?`}
        confirmLabel="Delete repository"
        onClose={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false)
          del.mutate()
        }}
      >
        The repository, its snapshots and all its reviews are removed. This cannot be undone.
      </ConfirmDialog>
      {r.index_status === 'failed' ? (
        <ErrorBox error={new Error(r.index_error ?? 'Unknown error')} title="Import failed" />
      ) : null}
      {r.index_status === 'ready' ? (
        <div className="space-y-8">
          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <Card
              className="rise-in"
              title="New review"
              description="Runs in the background; you can leave this page."
            >
              <div className="p-5">
                <StartReview repo={r} key={String(r.ai_review_allowed)} />
              </div>
            </Card>
            <Card
              className="rise-in"
              style={{ '--i': 1 } as CSSProperties}
              title="Index and LLM access"
            >
              <div className="space-y-5 p-5">
                <dl className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <dt className="text-xs text-faint">Files indexed</dt>
                    <dd className="mt-0.5 text-lg font-semibold tabular-nums">{r.file_count}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-faint">Size</dt>
                    <dd className="mt-0.5 text-lg font-semibold tabular-nums">
                      {formatBytes(r.total_bytes)}
                    </dd>
                  </div>
                  <div className="col-span-2 text-xs text-muted">
                    Indexed {timeAgo(r.indexed_at)}
                    {skipped.length
                      ? ` · skipped ${skipped.map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ')}`
                      : ''}
                  </div>
                </dl>
                <div className="border-t border-line pt-5">
                  <AiConsent repo={r} />
                </div>
              </div>
            </Card>
          </div>
          <Card className="rise-in" style={{ '--i': 2 } as CSSProperties}>
            <Tabs
              label="Repository sections"
              items={tabs}
              value={tab}
              onChange={(k) => setParams({ tab: k })}
            />
            {tab === 'reviews' ? <ReviewHistory repoId={id} /> : null}
            {tab === 'search' ? <Search repoId={id} /> : null}
            {tab === 'pulls' ? <Pulls repo={r} /> : null}
          </Card>
        </div>
      ) : null}
    </div>
  )
}
