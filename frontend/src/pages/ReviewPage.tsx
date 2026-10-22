import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { CodeView, DiffView } from '../components/CodeView'
import {
  Button,
  Card,
  Empty,
  ErrorBox,
  Label,
  PageHeader,
  Pill,
  SeverityBadge,
  SourceBadge,
  Spinner,
  StatusBadge,
  Tabs,
  inputClass,
  timeAgo,
} from '../components/ui'
import { api } from '../lib/api'
import { SEVERITIES, type Finding, type Review, type Verdict } from '../lib/types'
import { SeverityCounts } from './RepositoryPage'

const VERDICTS: [Verdict, string][] = [
  ['useful', 'Useful'],
  ['incorrect', 'Incorrect'],
  ['duplicate', 'Duplicate'],
  ['not_actionable', 'Not actionable'],
]

export function filterFindings(
  findings: Finding[],
  f: { severity: Set<string>; category: Set<string>; source: Set<string> },
) {
  return findings.filter(
    (x) =>
      (!f.severity.size || f.severity.has(x.severity)) &&
      (!f.category.size || f.category.has(x.category)) &&
      (!f.source.size || f.source.has(x.source)),
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-7 items-center rounded-full border px-3 text-xs font-medium capitalize ${active ? 'border-accent bg-accent-soft text-accent' : 'border-line-strong text-muted hover:bg-subtle hover:text-fg'}`}
    >
      {children}
    </button>
  )
}

function Feedback({ finding }: { finding: Finding }) {
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (v: Verdict) => api.feedback(finding.id, v),
    onSuccess: (_, v) =>
      qc.setQueryData<Finding[]>(['findings', finding.review_id], (old) =>
        old?.map((f) => (f.id === finding.id ? { ...f, my_feedback: v } : f)),
      ),
  })
  return (
    <div
      className="flex flex-wrap items-center gap-2 border-t border-line pt-5"
      role="group"
      aria-label="Rate this finding"
    >
      <span className="mr-1 text-sm font-medium">Was this finding right?</span>
      {VERDICTS.map(([v, label]) => (
        <Chip key={v} active={finding.my_feedback === v} onClick={() => m.mutate(v)}>
          {label}
        </Chip>
      ))}
      {m.error ? <span className="text-xs text-danger">Could not save feedback.</span> : null}
    </div>
  )
}

function Block({
  title,
  children,
  mono,
}: {
  title: string
  children: React.ReactNode
  mono?: boolean
}) {
  return (
    <div>
      <Label>{title}</Label>
      <div
        className={
          mono
            ? 'mt-2 overflow-auto rounded-control bg-subtle p-3 font-mono text-xs whitespace-pre'
            : 'mt-2 text-sm leading-relaxed whitespace-pre-wrap'
        }
      >
        {children}
      </div>
    </div>
  )
}

function FindingDetail({ finding, review }: { finding: Finding; review: Review }) {
  const file = useQuery({
    queryKey: ['review-file', review.id, finding.path],
    queryFn: () => api.reviewFile(review.id, finding.path),
  })
  const [copied, setCopied] = useState(false)
  return (
    <div className="rise-in min-w-0 space-y-6 p-5 lg:p-6">
      <p
        className={`rounded-control border px-3 py-2 text-xs ${finding.source === 'ai' ? 'border-ai/30 bg-ai-soft text-ai' : 'border-line bg-subtle text-muted'}`}
      >
        {finding.source === 'ai'
          ? 'LLM hypothesis. The file, lines and quoted code were checked against the source; the reasoning was not.'
          : 'Deterministic analyzer output. The same code always gives the same finding.'}
      </p>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <SourceBadge source={finding.source} />
          <span className="text-xs text-muted capitalize">
            {finding.category.replace('_', ' ')}
          </span>
          {finding.confidence ? (
            <span className="text-xs text-faint">· {finding.confidence} confidence</span>
          ) : null}
        </div>
        <h3 className="text-xl font-semibold tracking-tight break-words">{finding.title}</h3>
        <p className="font-mono text-xs break-all text-accent">
          {finding.path}:{finding.start_line}
          {finding.end_line !== finding.start_line ? `-${finding.end_line}` : ''}
        </p>
      </div>
      <p className="text-body">{finding.description}</p>
      <div className="overflow-hidden rounded-control border border-line">
        <p className="truncate border-b border-line bg-subtle px-3.5 py-2 font-mono text-xs text-muted">
          {finding.path}
        </p>
        {file.isLoading ? <Spinner label="Loading source" /> : null}
        {file.error ? (
          <div className="p-2">
            <ErrorBox error={file.error} title="Source unavailable" />
          </div>
        ) : null}
        {file.data ? (
          <CodeView
            content={file.data.content}
            highlight={[finding.start_line, finding.end_line]}
            path={finding.path}
          />
        ) : null}
      </div>
      {finding.reasoning ? <Block title="Reasoning">{finding.reasoning}</Block> : null}
      {finding.suggested_fix ? <Block title="Suggested fix">{finding.suggested_fix}</Block> : null}
      {finding.suggested_test ? (
        <div>
          <div className="flex items-center justify-between">
            <Label>Regression test</Label>
            <button
              className="text-xs font-medium text-accent hover:underline"
              onClick={() => {
                navigator.clipboard?.writeText(finding.suggested_test ?? '')
                setCopied(true)
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre className="mt-2 overflow-auto rounded-control bg-subtle p-3 font-mono text-xs leading-5">
            {finding.suggested_test}
          </pre>
        </div>
      ) : null}
      <p className="text-xs leading-relaxed text-muted">
        Source: {finding.analyzer}{' '}
        {finding.analyzer !== `llm:${finding.analyzer_version}` ? finding.analyzer_version : ''}
        {finding.rule_id ? (
          <>
            {' '}
            · rule <span className="font-mono">{finding.rule_id}</span>
          </>
        ) : null}
        {finding.doc_url ? (
          <>
            {' '}
            ·{' '}
            <a
              className="text-accent hover:underline"
              href={finding.doc_url}
              target="_blank"
              rel="noreferrer"
            >
              rule docs
            </a>
          </>
        ) : null}
        {finding.limitations ? (
          <>
            <br />
            Limitation: {finding.limitations}
          </>
        ) : null}
      </p>
      <Feedback finding={finding} />
    </div>
  )
}

function RunSummary({ review }: { review: Review }) {
  const s = review.stats
  const ai = s.ai
  const analyzers = Object.entries(s.analyzers ?? {}).filter(([k]) => !k.startsWith('_'))
  return (
    <Card>
      <div className="grid gap-6 p-5 text-sm md:grid-cols-3 md:divide-x md:divide-line lg:p-6">
        <div>
          <Label>Run</Label>
          <p className="mt-2 text-base font-semibold">
            {s.files_reviewed ?? 0} files reviewed
            {s.timings?.total_ms !== undefined ? (
              <span className="font-normal text-muted">
                {' '}
                in {(s.timings.total_ms / 1000).toFixed(1)} s
              </span>
            ) : null}
          </p>
          {s.head_sha ? (
            <p className="mt-1 font-mono text-xs text-faint">head {s.head_sha.slice(0, 10)}</p>
          ) : null}
          {s.duplicates_dropped ? (
            <p className="mt-1 text-muted">{s.duplicates_dropped} duplicate findings merged</p>
          ) : null}
        </div>
        <div className="md:pl-6">
          <Label>Analyzers</Label>
          <ul className="mt-2 space-y-1">
            {analyzers.map(([name, info]) => (
              <li key={name} className="flex items-center gap-2">
                <span className="font-medium">{name}</span>
                <span className="font-mono text-xs text-faint">{info.version}</span>
                {info.status === 'failed' ? (
                  <span className="text-xs font-medium text-danger" title={info.error}>
                    failed
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        <div className="md:pl-6">
          <Label>LLM review</Label>
          <div className="mt-2 space-y-1">
            {!ai || ai.status === 'not_requested' ? (
              <p className="text-muted">Not requested</p>
            ) : null}
            {ai?.status === 'skipped' ? <p className="text-warn">Skipped: {ai.reason}</p> : null}
            {ai?.status === 'failed' ? (
              <p className="text-danger">Failed: {ai.reason}. Analyzer results are still shown.</p>
            ) : null}
            {ai?.status === 'completed' ? (
              <>
                <p>
                  <span className="font-medium">{ai.model}</span>: {ai.accepted} of {ai.returned}{' '}
                  findings passed source validation
                </p>
                {ai.rejected?.length ? (
                  <details>
                    <summary className="cursor-pointer text-xs text-muted">
                      {ai.rejected.length} rejected
                    </summary>
                    <ul className="mt-1 space-y-0.5 text-xs text-muted">
                      {ai.rejected.map((r, i) => (
                        <li key={i}>
                          {r.title} — {r.reason.replaceAll('_', ' ')}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                <p className="text-xs text-faint">
                  {ai.input_tokens ?? '?'} in / {ai.output_tokens ?? '?'} out tokens ·{' '}
                  {((ai.latency_ms ?? 0) / 1000).toFixed(1)} s
                  {ai.files_omitted?.length
                    ? ` · ${ai.files_omitted.length} files omitted for size`
                    : ''}
                </p>
              </>
            ) : null}
          </div>
        </div>
      </div>
      {ai?.summary ? (
        <p className="border-t border-line px-5 py-4 text-sm text-muted lg:px-6">{ai.summary}</p>
      ) : null}
    </Card>
  )
}

export function ReviewPage() {
  const id = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'findings'
  const review = useQuery({
    queryKey: ['review', id],
    queryFn: () => api.review(id),
    refetchInterval: (q) =>
      q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1500 : false,
  })
  const done = review.data?.status === 'completed'
  const findings = useQuery({
    queryKey: ['findings', id],
    queryFn: () => api.findings(id),
    enabled: done,
  })
  const changed = useQuery({
    queryKey: ['changed', id],
    queryFn: () => api.changedFiles(id),
    enabled: done && review.data?.kind !== 'full',
  })
  const tests = useQuery({
    queryKey: ['tests', id],
    queryFn: () => api.testSuggestions(id),
    enabled: done,
  })
  const [filters, setFilters] = useState({
    severity: new Set<string>(),
    category: new Set<string>(),
    source: new Set<string>(),
  })
  const [query, setQuery] = useState('')
  const selectedId = Number(params.get('finding')) || null

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return filterFindings(findings.data ?? [], filters).filter(
      (f) => !q || `${f.title} ${f.path} ${f.rule_id ?? ''}`.toLowerCase().includes(q),
    )
  }, [findings.data, filters, query])
  const categories = useMemo(
    () => [...new Set((findings.data ?? []).map((f) => f.category))].sort(),
    [findings.data],
  )
  const selected = visible.find((f) => f.id === selectedId) ?? visible[0]

  const toggle = (key: keyof typeof filters, v: string) =>
    setFilters((f) => {
      const next = new Set(f[key])
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return { ...f, [key]: next }
    })

  if (review.isLoading) return <Spinner label="Loading review" />
  if (review.error) return <ErrorBox error={review.error} title="Review unavailable" />
  const r = review.data!
  const select = (fid: number) =>
    setParams({ tab: 'findings', finding: String(fid) }, { replace: true })

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <Link to={`/repositories/${r.repository_id}`} className="hover:text-fg hover:underline">
              Repository
            </Link>{' '}
            <span className="text-faint">/</span> Review #{r.id}
          </>
        }
        title={
          r.kind === 'pull_request' ? (
            `PR #${r.pr_number} ${r.pr_title ?? ''}`
          ) : r.kind === 'diff' ? (
            <span className="font-mono tracking-tight">
              {r.base_ref}..{r.head_ref}
            </span>
          ) : (
            'Whole repository'
          )
        }
        meta={
          <>
            <StatusBadge status={r.status} stage={r.stage} />
            {r.use_ai ? <Pill tone="ai">LLM review requested</Pill> : null}
            <span className="text-xs text-faint">Started {timeAgo(r.created_at)}</span>
          </>
        }
        actions={done ? <SeverityCounts counts={r.severity_counts} /> : null}
      />

      {r.status === 'queued' || r.status === 'running' ? (
        <Card className="px-6 py-12 text-center">
          <div
            aria-hidden
            className="activity-bar mx-auto mb-5 h-0.5 w-40 overflow-hidden rounded-full bg-line"
          />
          <p className="text-base font-semibold" role="status" aria-live="polite">
            {r.status === 'queued'
              ? 'Waiting for a worker'
              : `Running: ${r.stage?.replace('_', ' ') ?? 'starting'}`}
          </p>
          <p className="mt-1 text-sm text-muted">This page updates automatically.</p>
        </Card>
      ) : null}
      {r.status === 'failed' ? (
        <ErrorBox error={new Error(r.error ?? 'Unknown error')} title="Review failed" />
      ) : null}

      {done ? (
        <>
          <RunSummary review={r} />
          <Card>
            <Tabs
              label="Review results"
              value={tab}
              onChange={(k) => setParams({ tab: k })}
              items={[
                { id: 'findings', label: 'Findings', count: findings.data?.length ?? 0 },
                ...(r.kind !== 'full'
                  ? [{ id: 'changes', label: 'Changed files', count: changed.data?.length ?? 0 }]
                  : []),
                { id: 'tests', label: 'Test suggestions', count: tests.data?.length ?? 0 },
              ]}
            />

            {tab === 'findings' ? (
              <div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-3">
                  <input
                    type="search"
                    aria-label="Search findings"
                    placeholder="Search title, file or rule"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    className={`${inputClass} h-7 w-56 text-xs`}
                  />
                  <span className="mx-1 hidden h-5 w-px bg-line sm:block" />
                  <span className="text-xs font-medium text-faint">Severity</span>
                  {SEVERITIES.map((s) => (
                    <Chip
                      key={s}
                      active={filters.severity.has(s)}
                      onClick={() => toggle('severity', s)}
                    >
                      {s}
                    </Chip>
                  ))}
                  <span className="mx-1 hidden h-5 w-px bg-line sm:block" />
                  <span className="text-xs font-medium text-faint">Source</span>
                  <Chip
                    active={filters.source.has('static')}
                    onClick={() => toggle('source', 'static')}
                  >
                    Analyzer
                  </Chip>
                  <Chip active={filters.source.has('ai')} onClick={() => toggle('source', 'ai')}>
                    LLM
                  </Chip>
                  <span className="mx-1 hidden h-5 w-px bg-line sm:block" />
                  <span className="text-xs font-medium text-faint">Category</span>
                  {categories.map((c) => (
                    <Chip
                      key={c}
                      active={filters.category.has(c)}
                      onClick={() => toggle('category', c)}
                    >
                      {c.replace('_', ' ')}
                    </Chip>
                  ))}
                </div>
                {findings.isLoading ? <Spinner label="Loading findings" /> : null}
                {findings.error ? (
                  <div className="p-4">
                    <ErrorBox error={findings.error} />
                  </div>
                ) : null}
                {findings.data && !findings.data.length ? (
                  <div className="p-5">
                    <Empty title="No findings">
                      Analyzers{r.use_ai ? ' and the LLM review' : ''} reported nothing actionable
                      for the reviewed code.
                    </Empty>
                  </div>
                ) : null}
                {findings.data?.length && !visible.length ? (
                  <p className="px-5 py-8 text-center text-sm text-muted">
                    No findings match these filters.{' '}
                    <button
                      className="text-accent hover:underline"
                      onClick={() => {
                        setQuery('')
                        setFilters({ severity: new Set(), category: new Set(), source: new Set() })
                      }}
                    >
                      Clear all
                    </button>
                  </p>
                ) : null}
                {visible.length ? (
                  <div className="grid lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
                    <ul
                      className="max-h-[80vh] divide-y divide-line overflow-auto border-b border-line lg:sticky lg:top-0 lg:border-r lg:border-b-0"
                      aria-label="Findings (arrow keys move between them)"
                      onKeyDown={(e) => {
                        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
                        e.preventDefault()
                        const i = visible.findIndex((f) => f.id === selected?.id)
                        const next = visible[i + (e.key === 'ArrowDown' ? 1 : -1)]
                        if (!next) return
                        select(next.id)
                        e.currentTarget
                          .querySelector<HTMLButtonElement>(`[data-finding="${next.id}"]`)
                          ?.focus()
                      }}
                    >
                      {visible.map((f) => (
                        <li key={f.id}>
                          <button
                            data-finding={f.id}
                            onClick={() => select(f.id)}
                            aria-current={selected?.id === f.id}
                            className={`finding-row block w-full border-l-2 px-5 py-3 text-left ${selected?.id === f.id ? 'border-accent bg-accent-soft/60' : 'border-transparent hover:bg-subtle'}`}
                          >
                            <span className="flex items-center gap-1.5">
                              <SeverityBadge severity={f.severity} />
                              <SourceBadge source={f.source} />
                              {f.my_feedback ? (
                                <span className="text-xs text-faint">· rated</span>
                              ) : null}
                            </span>
                            <span className="mt-1.5 block text-sm leading-snug font-semibold break-words">
                              {f.title}
                            </span>
                            <span className="mt-1 block truncate font-mono text-xs text-faint">
                              {f.path}:{f.start_line}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    {selected ? (
                      <FindingDetail key={selected.id} finding={selected} review={r} />
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            {tab === 'changes' ? (
              <div className="space-y-3 p-5">
                {changed.data?.map((f) => (
                  <details
                    key={f.path}
                    className="overflow-hidden rounded-control border border-line"
                    open={changed.data.length <= 3}
                  >
                    <summary className="cursor-pointer bg-subtle px-3.5 py-2.5 font-mono text-xs">
                      {f.path} <span className="text-faint">({f.status})</span>{' '}
                      <span className="text-ok">+{f.additions}</span>{' '}
                      <span className="text-danger">−{f.deletions}</span>
                    </summary>
                    {f.patch ? (
                      <DiffView patch={f.patch} />
                    ) : (
                      <p className="p-3 text-xs text-muted">No textual diff.</p>
                    )}
                  </details>
                ))}
              </div>
            ) : null}

            {tab === 'tests' ? (
              <div className="space-y-4 p-5">
                {tests.data && !tests.data.length ? (
                  <Empty title="No test suggestions">
                    Every changed public function is already referenced by a test file.
                  </Empty>
                ) : null}
                <p className="text-xs text-muted">
                  Suggestions are previews to adapt. DevPilot never runs them.
                </p>
                {tests.data?.map((t) => (
                  <div key={t.id} className="overflow-hidden rounded-control border border-line">
                    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-subtle px-3.5 py-2">
                      <SourceBadge source={t.source} />
                      <span className="min-w-0 truncate font-mono text-xs font-medium">
                        {t.target}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-auto"
                        onClick={() => navigator.clipboard?.writeText(t.test_code)}
                      >
                        Copy
                      </Button>
                    </div>
                    <p className="px-4 pt-3 text-sm text-muted">{t.rationale}</p>
                    <pre className="overflow-auto px-4 py-3 font-mono text-xs leading-5">
                      {t.test_code}
                    </pre>
                  </div>
                ))}
              </div>
            ) : null}
          </Card>
        </>
      ) : null}
    </div>
  )
}
