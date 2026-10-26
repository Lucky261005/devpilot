import type { ReactNode } from 'react'
import type { CodeRange } from '../lib/types'

/*
 * Renders a model answer as a small, safe Markdown subset: paragraphs, #-### headings, - / 1. lists,
 * fenced code, `code` and **bold**. Everything becomes React text nodes, so HTML in the answer is
 * shown literally, never parsed. Inline code naming a known file opens it in the code viewer.
 */

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; text: string; level: number }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'code'; text: string }

function parseBlocks(answer: string): Block[] {
  const blocks: Block[] = []
  const lines = answer.replace(/\r\n?/g, '\n').split('\n')
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') })
    para = []
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.trimStart().startsWith('```')) {
      flush()
      const code: string[] = []
      while (++i < lines.length && !lines[i].trimStart().startsWith('```')) code.push(lines[i])
      blocks.push({ kind: 'code', text: code.join('\n') })
      continue
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    const item = /^\s*(?:([-*])|(\d+)[.)])\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      blocks.push({ kind: 'h', level: heading[1].length, text: heading[2] })
    } else if (item) {
      flush()
      const kind = item[1] ? 'ul' : 'ol'
      const last = blocks[blocks.length - 1]
      if (last?.kind === kind) last.items.push(item[3])
      else blocks.push({ kind, items: [item[3]] })
    } else if (line.trim()) {
      para.push(line.trim())
    } else {
      flush()
    }
  }
  flush()
  return blocks
}

/** `path`, `path:12` or `path:12-20` when path is one of the answer's files. */
function rangeFor(text: string, known: CodeRange[]): CodeRange | null {
  const m = /^(.+?)(?::(\d+)(?:-(\d+))?)?$/.exec(text)
  const file = m && known.find((r) => r.path === m[1])
  if (!m || !file) return null
  if (!m[2]) return file
  const start = Number(m[2])
  return { path: file.path, start_line: start, end_line: m[3] ? Number(m[3]) : start }
}

function inline(text: string, known: CodeRange[], onOpen: (r: CodeRange) => void): ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/).map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      const code = part.slice(1, -1)
      const range = rangeFor(code, known)
      return range ? (
        <button
          key={i}
          type="button"
          onClick={() => onOpen(range)}
          className="rounded bg-accent-soft px-1 font-mono text-[0.85em] break-all text-accent hover:underline"
          title={`Open ${code}`}
        >
          {code}
        </button>
      ) : (
        <code key={i} className="rounded bg-subtle px-1 font-mono text-[0.85em] break-all">
          {code}
        </code>
      )
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return <strong key={i}>{part.slice(2, -2)}</strong>
    return part
  })
}

export function AnswerText({
  answer,
  known,
  onOpen,
}: {
  answer: string
  known: CodeRange[]
  onOpen: (r: CodeRange) => void
}) {
  const md = (t: string) => inline(t, known, onOpen)
  return (
    <div className="max-w-prose min-w-0 space-y-3 text-sm leading-relaxed">
      {parseBlocks(answer).map((b, i) => {
        if (b.kind === 'code')
          return (
            <pre
              key={i}
              className="overflow-x-auto rounded-control border border-line bg-subtle p-3 font-mono text-xs leading-5"
            >
              <code>{b.text}</code>
            </pre>
          )
        if (b.kind === 'h')
          return (
            <p key={i} role="heading" aria-level={b.level + 3} className="font-semibold text-fg">
              {md(b.text)}
            </p>
          )
        if (b.kind === 'ul' || b.kind === 'ol') {
          const List = b.kind
          return (
            <List
              key={i}
              className={`space-y-1 pl-5 ${b.kind === 'ul' ? 'list-disc' : 'list-decimal'}`}
            >
              {b.items.map((it, j) => (
                <li key={j}>{md(it)}</li>
              ))}
            </List>
          )
        }
        return <p key={i}>{md(b.text)}</p>
      })}
    </div>
  )
}
