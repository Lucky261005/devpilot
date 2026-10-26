import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { AskResponse, CodeRange } from '../lib/types'
import { AnswerText } from './AnswerText'
import { CodeView } from './CodeView'
import { Button, ErrorBox, Notice, Pill, Spinner, inputClass } from './ui'

const EXAMPLES = [
  'Where is authentication handled?',
  'What happens when a review is created?',
  'Which file validates the configuration?',
]

const CONFIDENCE_TONE = { high: 'ok', medium: 'warn', low: 'danger' } as const

function RangeButton({
  range,
  active,
  onOpen,
  children,
}: {
  range: CodeRange
  active: boolean
  onOpen: (r: CodeRange) => void
  children?: ReactNode
}) {
  return (
    <button
      className={`block w-full px-3.5 py-2 text-left hover:bg-subtle ${active ? 'bg-accent-soft' : ''}`}
      onClick={() => onOpen(range)}
    >
      <span className="font-mono text-xs text-accent">
        {range.path}:{range.start_line}-{range.end_line}
      </span>
      {children}
    </button>
  )
}

function Result({ data, repoId }: { data: AskResponse; repoId: number }) {
  const [open, setOpen] = useState<CodeRange | null>(data.citations[0] ?? data.sources[0] ?? null)
  const file = useQuery({
    queryKey: ['file', repoId, open?.path],
    queryFn: () => api.repoFile(repoId, open!.path),
    enabled: !!open,
  })
  const same = (r: CodeRange) =>
    open?.path === r.path && open.start_line === r.start_line && open.end_line === r.end_line
  return (
    <div className="space-y-4">
      {data.status === 'answered' ? (
        <div className="min-w-0 space-y-3 rounded-control border border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={CONFIDENCE_TONE[data.confidence ?? 'low']}>
              {data.confidence} confidence
            </Pill>
            {data.model ? <span className="text-xs text-faint">{data.model}</span> : null}
          </div>
          <AnswerText
            answer={data.answer ?? ''}
            known={[...data.citations, ...data.sources]}
            onOpen={setOpen}
          />
          {data.unknowns.length ? (
            <div>
              <p className="text-xs font-semibold text-muted">Not shown by the code</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-muted">
                {data.unknowns.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <Notice tone={data.status === 'no_matches' ? 'info' : 'warn'}>{data.message}</Notice>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          {data.citations.length ? (
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-muted">Evidence</h3>
              <ul className="divide-y divide-line rounded-control border border-line">
                {data.citations.map((c) => (
                  <li key={`${c.path}:${c.start_line}-${c.end_line}`}>
                    <RangeButton range={c} active={same(c)} onOpen={setOpen}>
                      <span className="mt-0.5 block text-sm text-muted">{c.note}</span>
                    </RangeButton>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {data.sources.length ? (
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-muted">
                {data.status === 'answered' ? 'Code the answer was based on' : 'Matching code'}
              </h3>
              <ul className="max-h-[40vh] divide-y divide-line overflow-auto rounded-control border border-line">
                {data.sources.map((s) => (
                  <li key={`${s.path}:${s.start_line}`}>
                    <RangeButton range={s} active={same(s)} onOpen={setOpen} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
        {open ? (
          <div className="min-w-0 overflow-hidden rounded-control border border-line">
            <p className="truncate border-b border-line bg-subtle px-3.5 py-2 font-mono text-xs">
              {open.path}
            </p>
            {file.isLoading ? <Spinner label="Loading file" /> : null}
            {file.error ? <ErrorBox error={file.error} /> : null}
            {file.data ? (
              <CodeView
                content={file.data.content}
                highlight={[open.start_line, open.end_line]}
                path={open.path}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function AskRepository({ repoId }: { repoId: number }) {
  const [question, setQuestion] = useState('')
  const ask = useMutation({ mutationFn: (q: string) => api.ask(repoId, q) })
  const submit = (q: string) => {
    const text = q.trim()
    if (text.length >= 3) ask.mutate(text)
  }
  return (
    <div className="space-y-4 p-5">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit(question)
        }}
      >
        <label htmlFor="ask-question" className="block text-sm font-medium">
          Ask about this repository
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="ask-question"
            className={inputClass}
            value={question}
            maxLength={500}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Where is the configuration validated?"
          />
          <Button
            type="submit"
            variant="primary"
            disabled={ask.isPending || question.trim().length < 3}
          >
            Ask
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:bg-subtle"
              onClick={() => {
                setQuestion(ex)
                submit(ex)
              }}
            >
              {ex}
            </button>
          ))}
        </div>
        <p className="text-xs text-faint">
          Answers use only matching code from this repository and cite it. Matching is by keyword,
          so name files, functions or terms that appear in the code.
        </p>
      </form>
      {ask.isPending ? <Spinner label="Reading the code" /> : null}
      {ask.error ? <ErrorBox error={ask.error} /> : null}
      {ask.data && !ask.isPending ? (
        <Result key={JSON.stringify(ask.data.sources)} data={ask.data} repoId={repoId} />
      ) : null}
    </div>
  )
}
