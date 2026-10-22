import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api } from '../lib/api'
import type { Repository } from '../lib/types'
import { Button, ErrorBox, Field, inputClass } from './ui'

/**
 * GitHub tab of "Add a repository": pick a repository the GitHub App was granted, pick a branch,
 * import that branch's current commit. The server re-checks the grant and pins the commit SHA.
 */
export function GitHubImport({
  installUrl,
  onDone,
}: {
  installUrl: string | null
  onDone: (r: Repository) => void
}) {
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [branch, setBranch] = useState('')

  // A 401 means GitHub revoked access; the server already dropped the connection.
  const onAuthError = (e: unknown) => {
    if (e instanceof ApiError && e.status === 401)
      qc.invalidateQueries({ queryKey: ['github-status'] })
  }
  const repos = useQuery({ queryKey: ['github-repos'], queryFn: api.githubRepos, retry: false })
  const branches = useQuery({
    queryKey: ['github-branches', selected],
    queryFn: () => api.githubBranches(selected!),
    enabled: !!selected,
    retry: false,
  })
  const authError = repos.error ?? branches.error
  useEffect(() => {
    if (authError instanceof ApiError && authError.status === 401)
      qc.invalidateQueries({ queryKey: ['github-status'] })
  }, [authError, qc])
  useEffect(() => {
    if (branches.data) setBranch(branches.data.default_branch)
  }, [branches.data])

  const m = useMutation({
    mutationFn: () => api.importGithub(selected!, branch),
    onSuccess: onDone,
    onError: onAuthError,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    m.mutate()
  }

  const q = query.trim().toLowerCase()
  const shown = (repos.data ?? []).filter((r) => r.full_name.toLowerCase().includes(q))
  const sha = branches.data?.branches.find((b) => b.name === branch)?.sha

  if (repos.isLoading)
    return (
      <ul role="status" aria-label="Loading repositories from GitHub" className="space-y-2">
        {[0, 1, 2].map((i) => (
          <li key={i} className="skeleton h-9" />
        ))}
      </ul>
    )
  if (repos.error)
    return (
      <div className="space-y-3">
        <ErrorBox error={repos.error} title="Could not load repositories from GitHub" />
        <Button size="sm" onClick={() => repos.refetch()}>
          Try again
        </Button>
      </div>
    )
  if (!repos.data?.length)
    return (
      <div className="rounded-control border border-line px-4 py-6 text-center text-sm text-muted">
        <p className="font-medium text-fg">No repositories granted yet</p>
        <p className="mt-1">
          DevPilot only sees repositories you install the GitHub App on, including private ones.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          {installUrl ? (
            <a
              href={installUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center rounded-control bg-accent px-3 text-[13px] font-medium text-accent-fg"
            >
              Choose repositories on GitHub
            </a>
          ) : null}
          <Button size="sm" onClick={() => repos.refetch()}>
            Refresh
          </Button>
        </div>
      </div>
    )

  return (
    <form onSubmit={submit} className="space-y-5">
      <Field label="Repository">
        <input
          type="search"
          className={inputClass}
          placeholder="Filter repositories"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </Field>
      <fieldset>
        <legend className="sr-only">Choose a repository</legend>
        <ul className="max-h-64 divide-y divide-line overflow-auto rounded-control border border-line">
          {shown.map((r) => (
            <li key={r.full_name}>
              <label
                className={`flex cursor-pointer items-center gap-3 px-3 py-2 text-sm ${selected === r.full_name ? 'bg-accent-soft' : 'hover:bg-subtle'}`}
              >
                <input
                  type="radio"
                  name="github-repo"
                  value={r.full_name}
                  checked={selected === r.full_name}
                  onChange={() => {
                    setSelected(r.full_name)
                    setBranch('')
                    m.reset()
                  }}
                  className="accent-[var(--accent)]"
                />
                <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{r.full_name}</span>
                {r.private ? <span className="text-xs text-faint">private</span> : null}
              </label>
            </li>
          ))}
          {!shown.length ? (
            <li className="px-3 py-4 text-center text-sm text-muted">No repository matches.</li>
          ) : null}
        </ul>
      </fieldset>
      {installUrl ? (
        <p className="text-xs text-muted">
          Missing one?{' '}
          <a
            className="text-accent hover:underline"
            href={installUrl}
            target="_blank"
            rel="noreferrer"
          >
            Grant DevPilot access on GitHub
          </a>
          , then{' '}
          <button
            type="button"
            className="text-accent hover:underline"
            onClick={() => repos.refetch()}
          >
            refresh
          </button>
          .
        </p>
      ) : null}

      {selected ? (
        <Field
          label="Branch"
          hint={
            sha ? `Imports commit ${sha.slice(0, 7)} exactly; the review records it.` : undefined
          }
        >
          {branches.isLoading ? (
            <div role="status" aria-label="Loading branches" className="skeleton h-9" />
          ) : branches.error ? (
            <ErrorBox error={branches.error} title="Could not load branches" />
          ) : (
            <select
              className={inputClass}
              value={branch}
              onChange={(e) => {
                setBranch(e.target.value)
                m.reset()
              }}
            >
              {branches.data?.branches.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}
                  {b.name === branches.data?.default_branch ? ' (default)' : ''}
                </option>
              ))}
            </select>
          )}
        </Field>
      ) : null}

      {m.isPending ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-control border border-line p-3 text-sm"
        >
          <div
            aria-hidden
            className="activity-bar mb-3 h-0.5 w-full overflow-hidden rounded-full bg-line"
          />
          Downloading <span className="font-mono">{selected}</span> at{' '}
          <span className="font-mono">
            {branch}
            {sha ? ` (${sha.slice(0, 7)})` : ''}
          </span>
          , then indexing. Large repositories take a minute.
        </div>
      ) : null}
      {m.error ? <ErrorBox error={m.error} title="Import failed" /> : null}
      <Button
        variant="primary"
        type="submit"
        disabled={!selected || !branch || m.isPending || !!branches.error}
      >
        {m.isPending ? 'Importing' : m.error ? 'Try again' : 'Import repository'}
      </Button>
    </form>
  )
}
