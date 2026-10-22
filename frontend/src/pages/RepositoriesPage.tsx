import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Empty,
  ErrorBox,
  Field,
  PageHeader,
  Pill,
  Stat,
  formatBytes,
  inputClass,
  timeAgo,
} from '../components/ui'
import { GitHubImport } from '../components/GitHubImport'
import { api } from '../lib/api'
import { SOURCE_LABEL, type Repository } from '../lib/types'

function ImportForm({ onDone }: { onDone: (r: Repository) => void }) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const gh = useQuery({ queryKey: ['github-status'], queryFn: api.githubStatus })
  const [kind, setKind] = useState<'archive' | 'local' | 'github'>('archive')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [over, setOver] = useState(false)
  const [path, setPath] = useState('')
  const m = useMutation({
    mutationFn: () => {
      if (kind === 'archive') return api.importArchive(name, file as File)
      return api.importLocal(name, path)
    },
    onSuccess: onDone,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    m.mutate()
  }
  const tabs: { id: typeof kind; label: string; disabled?: string }[] = [
    { id: 'archive', label: 'Upload ZIP' },
    {
      id: 'local',
      label: 'Local Git path',
      disabled:
        settings.data && !settings.data.local_import_enabled
          ? 'Disabled on this server (DEVPILOT_ALLOWED_LOCAL_ROOTS is empty).'
          : undefined,
    },
    {
      id: 'github',
      label: 'GitHub',
      disabled: gh.data && !gh.data.connected ? 'Connect GitHub in Settings first.' : undefined,
    },
  ]
  return (
    // Each source has its own <form>; GitHubImport renders one too, and forms cannot nest.
    <div className="space-y-5 p-5">
      <div
        role="tablist"
        aria-label="Import source"
        className="inline-flex gap-1 rounded-control bg-subtle p-1"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={kind === t.id}
            onClick={() => {
              setKind(t.id)
              m.reset()
            }}
            className={`h-8 rounded-md px-3 text-sm ${kind === t.id ? 'bg-panel font-semibold text-fg shadow-card' : 'text-muted hover:text-fg'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.find((t) => t.id === kind)?.disabled ? (
        <p className="text-sm text-muted">
          {tabs.find((t) => t.id === kind)?.disabled}{' '}
          {kind === 'github' ? (
            <Link className="text-accent hover:underline" to="/settings">
              Open settings
            </Link>
          ) : null}
        </p>
      ) : kind === 'github' ? (
        <GitHubImport installUrl={gh.data?.install_url ?? null} onDone={onDone} />
      ) : (
        <form onSubmit={submit} className="space-y-5">
          <Field label="Name">
            <input
              className={inputClass}
              required
              maxLength={100}
              pattern="[\w.\- ]+"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="payments-service"
            />
          </Field>
          {kind === 'archive' ? (
            <Field
              label="Archive"
              hint={
                settings.data
                  ? `ZIP up to ${formatBytes(settings.data.limits.max_upload_bytes)}. Secret files (.env, keys) are removed; nothing is executed.`
                  : undefined
              }
            >
              <div
                className="drop-zone relative grid h-28 place-items-center rounded-control px-4 text-center text-sm"
                data-over={over || undefined}
                onDragEnter={() => setOver(true)}
                onDragLeave={() => setOver(false)}
                onDrop={() => setOver(false)}
              >
                {/* The native input covers the zone, so clicking and dropping both work. */}
                <input
                  type="file"
                  accept=".zip,application/zip"
                  required
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="absolute inset-0 cursor-pointer opacity-0"
                />
                {file ? (
                  <span>
                    <span className="font-mono text-fg">{file.name}</span>
                    <span className="text-muted"> · {formatBytes(file.size)}</span>
                    {!/\.zip$/i.test(file.name) ? (
                      <span className="mt-1 block text-danger">Not a .zip file</span>
                    ) : null}
                  </span>
                ) : (
                  <span className="text-muted">
                    <span className="font-medium text-fg">Drop a ZIP here</span> or click to choose
                  </span>
                )}
              </div>
            </Field>
          ) : null}
          {kind === 'local' ? (
            <Field
              label="Repository path"
              hint="Must be inside a directory the server administrator allowed."
            >
              <input
                className={`${inputClass} font-mono`}
                required
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/srv/repos/my-project"
              />
            </Field>
          ) : null}
          {m.error ? <ErrorBox error={m.error} title="Import failed" /> : null}
          <Button variant="primary" type="submit" disabled={m.isPending}>
            {m.isPending ? 'Importing and indexing…' : 'Import repository'}
          </Button>
        </form>
      )}
    </div>
  )
}

export function RepositoriesPage() {
  const repos = useQuery({ queryKey: ['repos'], queryFn: api.repositories })
  const [showImport, setShowImport] = useState(false)
  const [query, setQuery] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const list = repos.data ?? []
  const ready = list.filter((r) => r.index_status === 'ready')
  const q = query.trim().toLowerCase()
  const shown = q ? list.filter((r) => `${r.name} ${r.source_ref}`.toLowerCase().includes(q)) : list

  return (
    <div>
      <PageHeader
        title="Repositories"
        description="Import a codebase, then review a whole snapshot or a range of commits. Analyzer findings and LLM hypotheses are kept separate."
        actions={
          <Button
            variant={showImport ? 'secondary' : 'primary'}
            onClick={() => setShowImport((v) => !v)}
            aria-expanded={showImport}
          >
            {showImport ? 'Cancel' : 'Add repository'}
          </Button>
        }
      />

      {list.length > 0 ? (
        <div className="rise-in mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Repositories" value={list.length} />
          <Stat
            label="Files indexed"
            value={ready.reduce((n, r) => n + r.file_count, 0).toLocaleString()}
            hint={formatBytes(ready.reduce((n, r) => n + r.total_bytes, 0))}
          />
          <Stat
            label="LLM review enabled"
            value={list.filter((r) => r.ai_review_allowed).length}
            hint="Opt-in per repository"
          />
          <Stat
            label="Failed imports"
            value={list.filter((r) => r.index_status === 'failed').length}
          />
        </div>
      ) : null}

      {showImport ? (
        <Card
          className="rise-in mb-8"
          title="Add a repository"
          description="Files are extracted safely, secret files are removed, and nothing from the repository is executed."
        >
          <ImportForm
            onDone={(r) => {
              qc.invalidateQueries({ queryKey: ['repos'] })
              setShowImport(false)
              navigate(`/repositories/${r.id}`)
            }}
          />
        </Card>
      ) : null}

      {repos.isLoading ? (
        <Card>
          <ul role="status" aria-label="Loading repositories" className="divide-y divide-line">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex items-center gap-6 px-5 py-3.5">
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-3.5 w-40" />
                  <div className="skeleton h-3 w-64" />
                </div>
                <div className="skeleton h-5 w-28" />
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {repos.error ? <ErrorBox error={repos.error} /> : null}
      {repos.data && list.length === 0 && !showImport ? (
        <Empty title="No repositories yet">
          Upload a ZIP archive, point at a local Git repository, or connect GitHub. A sample
          repository with seeded defects lives in{' '}
          <code className="font-mono text-fg">fixtures/sample_repositories/inventory_service</code>.
        </Empty>
      ) : null}

      {list.length > 0 ? (
        <Card className="rise-in" style={{ '--i': 1 } as CSSProperties}>
          <div className="flex items-center gap-3 border-b border-line px-5 py-3">
            <input
              type="search"
              aria-label="Filter repositories"
              placeholder="Filter by name or source"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className={`${inputClass} h-8 max-w-xs text-[13px]`}
            />
            <span className="ml-auto text-xs text-faint tabular-nums">
              {shown.length} of {list.length}
            </span>
          </div>
          {shown.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-muted">
              No repository matches “{query.trim()}”.{' '}
              <button className="text-accent hover:underline" onClick={() => setQuery('')}>
                Clear filter
              </button>
            </p>
          ) : null}
          <ul className="divide-y divide-line">
            {shown.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/repositories/${r.id}`}
                  className="group flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 last:rounded-b-card hover:bg-subtle/70"
                >
                  <div className="min-w-0 flex-1 basis-64">
                    <p className="truncate text-sm font-semibold group-hover:text-accent">
                      {r.name}
                    </p>
                    <p
                      className="mt-0.5 truncate font-mono text-xs text-faint"
                      title={r.source_ref}
                    >
                      {SOURCE_LABEL[r.source_type]} · {r.source_ref}
                      {r.source_branch ? ` @ ${r.source_branch}` : ''}
                      {r.source_sha ? ` · ${r.source_sha.slice(0, 7)}` : ''}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {r.index_status === 'failed' ? (
                      <Pill tone="danger">Import failed</Pill>
                    ) : r.index_status === 'ready' ? (
                      <Pill>
                        {r.file_count} files · {formatBytes(r.total_bytes)}
                      </Pill>
                    ) : (
                      <Pill tone="accent">Indexing</Pill>
                    )}
                    {r.ai_review_allowed ? <Pill tone="ai">LLM review on</Pill> : null}
                  </div>
                  <span className="text-xs text-faint sm:w-28 sm:text-right">
                    Added {timeAgo(r.created_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}
