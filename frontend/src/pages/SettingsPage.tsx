import type { CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button,
  Card,
  ErrorBox,
  Notice,
  PageHeader,
  Pill,
  Spinner,
  formatBytes,
} from '../components/ui'
import { api } from '../lib/api'
import { useTitle } from '../lib/useTitle'

/** One setting: what it is on the left, its state or control on the right. */
function Row({
  title,
  description,
  children,
}: {
  title: string
  description?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3 px-5 py-4 lg:px-6">
      <div className="min-w-0 flex-1 basis-72">
        <p className="text-sm font-semibold">{title}</p>
        {description ? (
          <div className="mt-1 text-sm leading-relaxed text-muted">{description}</div>
        ) : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}

export function SettingsPage() {
  useTitle('Settings')
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const gh = useQuery({ queryKey: ['github-status'], queryFn: api.githubStatus })
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const disconnect = useMutation({
    mutationFn: api.disconnectGithub,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['github-status'] }),
  })
  if (settings.isLoading || gh.isLoading) return <Spinner label="Loading settings" />
  if (settings.error) return <ErrorBox error={settings.error} />
  const s = settings.data!
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Settings"
        description="Integrations, the LLM provider and what happens to your code. Values come from the server configuration."
      />
      <div className="space-y-8">
        {params.get('github') === 'declined' ? (
          <div role="status" className="rise-in">
            <Notice tone="warn">GitHub authorization was cancelled. Nothing was connected.</Notice>
          </div>
        ) : null}
        {params.get('github') === 'connected' ? (
          <div role="status" className="rise-in">
            <Notice tone="ok">GitHub account connected.</Notice>
          </div>
        ) : null}

        <Card className="rise-in" title="Integrations">
          <Row
            title="GitHub"
            description={
              !gh.data?.configured ? (
                <>
                  OAuth is not configured on this server. Set{' '}
                  <code className="font-mono text-fg">DEVPILOT_GITHUB_CLIENT_ID</code> and{' '}
                  <code className="font-mono text-fg">DEVPILOT_GITHUB_CLIENT_SECRET</code> to enable
                  it. ZIP and local imports work without it.
                </>
              ) : gh.data.connected ? (
                <>
                  Connected as <b className="text-fg">{gh.data.login}</b>
                  {', read-only access to the repositories you choose.'}
                </>
              ) : (
                <>
                  Requested access: {s.github.scopes}. The token is encrypted at rest and never sent
                  to the browser.
                </>
              )
            }
          >
            {!gh.data?.configured ? (
              <Pill>Not configured</Pill>
            ) : gh.data.connected ? (
              <>
                <Pill tone="ok">Connected</Pill>
                {gh.data.install_url ? (
                  <a
                    href={gh.data.install_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm font-medium text-accent hover:underline"
                  >
                    Choose repositories
                  </a>
                ) : null}
                <Button
                  variant="danger"
                  size="sm"
                  disabled={disconnect.isPending}
                  onClick={() => disconnect.mutate()}
                >
                  Disconnect
                </Button>
              </>
            ) : (
              <a
                href="/api/github/oauth/start"
                className="inline-flex h-9 items-center rounded-control bg-accent px-3.5 text-sm font-medium text-accent-fg shadow-card hover:brightness-110"
              >
                Connect GitHub
              </a>
            )}
          </Row>
          {disconnect.error ? (
            <div className="px-5 pb-4 lg:px-6">
              <ErrorBox error={disconnect.error} />
            </div>
          ) : null}
          {disconnect.data ? (
            <div role="status" className="px-5 pb-4 lg:px-6">
              <Notice tone={disconnect.data.github_grant_revoked ? 'ok' : 'warn'}>
                {disconnect.data.detail}
              </Notice>
            </div>
          ) : null}
        </Card>

        <Card
          className="rise-in"
          style={{ '--i': 1 } as CSSProperties}
          title="LLM review"
          description="Optional. Analyzer findings never depend on it. Status reflects server configuration, not a live connection test."
        >
          <div className="divide-y divide-line">
            <Row
              title="Provider"
              description={
                s.llm.configured ? (
                  <>
                    <span className="font-mono text-fg">{s.llm.model}</span>
                    {s.llm.local ? ', running locally on this server.' : '.'}
                  </>
                ) : (
                  <>
                    Reviews run deterministic analyzers only. Set{' '}
                    <code className="font-mono text-fg">DEVPILOT_LLM_PROVIDER=ollama</code> for a
                    free local model, or{' '}
                    <code className="font-mono text-fg">ANTHROPIC_API_KEY</code> for Claude.
                  </>
                )
              }
            >
              {s.llm.configured ? (
                <>
                  <Pill tone="accent">{s.llm.provider}</Pill>
                  {s.llm.local ? (
                    <Pill tone="ok">Local</Pill>
                  ) : (
                    <Pill tone="warn">Third-party API</Pill>
                  )}
                </>
              ) : (
                <Pill tone="warn">Not configured</Pill>
              )}
            </Row>
            <Row
              title="Where your code goes"
              description={
                s.llm.local
                  ? 'The model runs on this server, so source code is not sent to a third party.'
                  : "Source code leaves this server only for repositories where you enabled LLM review, and only when a review requests it. The provider's own data-retention policy applies to anything sent to it."
              }
            />
            <Row
              title="What is sent"
              description="Line-numbered excerpts of the reviewed files plus analyzer results, capped by the context limit. Files matching secret patterns (.env, keys, credentials) are deleted at import."
            />
            <Row
              title="How model output is treated"
              description="Repository content is marked as untrusted in the prompt. Every model finding is checked against the source (file, lines and quoted code) before it is shown, and is labeled as an LLM hypothesis."
            />
          </div>
        </Card>

        <Card
          className="rise-in"
          style={{ '--i': 2 } as CSSProperties}
          title="Limits and retention"
        >
          <dl className="grid gap-px overflow-hidden rounded-b-card bg-line sm:grid-cols-2 lg:grid-cols-3">
            {[
              ['Archive upload', formatBytes(s.limits.max_upload_bytes)],
              ['Repository size', formatBytes(s.limits.max_repo_bytes)],
              ['Single file', formatBytes(s.limits.max_file_bytes)],
              ['Reviews per hour', String(s.limits.reviews_per_hour)],
              ['Snapshot retention', `${s.retention_days} days`],
              ['Local Git import', s.local_import_enabled ? 'Enabled' : 'Disabled'],
            ].map(([k, v]) => (
              <div key={k} className="bg-panel px-5 py-4 lg:px-6">
                <dt className="text-xs text-faint">{k}</dt>
                <dd className="mt-1 text-base font-semibold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <p className="text-xs text-faint">
          Per-review source snapshots are removed by{' '}
          <code className="font-mono">python -m app.cli cleanup</code> after the retention period.
          Findings stay until their repository is deleted.
        </p>
      </div>
    </div>
  )
}
