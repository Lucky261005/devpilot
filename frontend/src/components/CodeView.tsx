import { useEffect, useRef } from 'react'

/** Line-numbered source with a highlighted range that scrolls into view. */
export function CodeView({
  content,
  highlight,
  path,
}: {
  content: string
  highlight?: [number, number]
  path: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const lines = content.split('\n')
  useEffect(() => {
    if (!highlight) return
    // Scroll only the code panel; scrollIntoView would also move the page.
    const box = ref.current
    const row = box?.querySelector<HTMLElement>(`[data-line="${highlight[0]}"]`)
    if (box && row) box.scrollTop = row.offsetTop - box.clientHeight / 2
  }, [highlight, content])

  return (
    <div
      ref={ref}
      className="relative max-h-[70vh] overflow-auto font-mono text-[12.5px] leading-[22px]"
      aria-label={`Source of ${path}`}
    >
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            const n = i + 1
            const hl = highlight && n >= highlight[0] && n <= highlight[1]
            return (
              <tr key={n} data-line={n} className={hl ? 'code-hit bg-hl' : undefined}>
                <td className="w-12 select-none border-r border-line pr-3 text-right align-top text-faint">
                  {n}
                </td>
                <td className="whitespace-pre pr-4 pl-4">{line || ' '}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Renders a unified-diff hunk section with old/new line numbers. */
export function DiffView({ patch }: { patch: string }) {
  let oldLn = 0
  let newLn = 0
  const rows = patch.split('\n').map((line, i) => {
    const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line)
    if (m) {
      oldLn = Number(m[1])
      newLn = Number(m[2])
      return (
        <tr key={i} className="bg-accent-soft/50 text-muted">
          <td colSpan={3} className="px-3 py-0.5">
            {line}
          </td>
        </tr>
      )
    }
    if (line.startsWith('\\')) return null
    const kind = line[0]
    const row =
      kind === '+'
        ? ['', newLn++, 'bg-add']
        : kind === '-'
          ? [oldLn++, '', 'bg-del']
          : [oldLn++, newLn++, '']
    return (
      <tr key={i} className={row[2] as string}>
        <td className="w-10 select-none pr-2 text-right text-faint">{row[0]}</td>
        <td className="w-10 select-none border-r border-line pr-3 text-right text-faint">
          {row[1]}
        </td>
        <td className="whitespace-pre pr-4 pl-4">{line || ' '}</td>
      </tr>
    )
  })
  return (
    <div className="overflow-auto font-mono text-[12.5px] leading-[22px]">
      <table className="w-full border-collapse">
        <tbody>{rows}</tbody>
      </table>
    </div>
  )
}
