/*
 * Login-screen illustration: a wireframe source file that a scan beam sweeps over. Where the beam
 * passes, findings get flagged, mirroring the real pipeline (analyzers flag, AI findings are checked
 * against the source and either verified or rejected). Purely decorative; hidden from assistive tech.
 * Motion is CSS-only (index.css, .hero-*) so it stays smooth while the page loads.
 */

const W = 560
const H = 420
const TOP = 56 // first code line, below the title bar
const STEP = 22
const SCAN_S = 4.8 // must match .hero-beam duration in index.css

// Indent and width of each code line, in px. A fixed shape, not data.
const LINES: [number, number][] = [
  [0, 180],
  [16, 250],
  [16, 140],
  [32, 220],
  [32, 210],
  [16, 120],
  [0, 0],
  [0, 220],
  [16, 280],
  [32, 190],
  [32, 230],
  [16, 160],
  [0, 0],
  [0, 240],
  [16, 200],
  [16, 110],
]

type Mark = { line: number; label: string; tone: 'danger' | 'warn' | 'ok' | 'muted' }
const MARKS: Mark[] = [
  { line: 3, label: 'B023  bug', tone: 'danger' },
  { line: 5, label: 'AI  rejected: no evidence', tone: 'muted' },
  { line: 10, label: 'AI  verified', tone: 'ok' },
  { line: 13, label: 'B105  security', tone: 'warn' },
]

const lineY = (i: number) => TOP + i * STEP

export function HeroScene() {
  return (
    <div aria-hidden className="hero-stage">
      <svg viewBox={`0 0 ${W} ${H}`} className="hero-svg" fill="none">
        <defs>
          <linearGradient id="hero-beam" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#8B9CFF" stopOpacity="0" />
            <stop offset="0.85" stopColor="#8B9CFF" stopOpacity="0.16" />
            <stop offset="1" stopColor="#A5B1FF" stopOpacity="0.55" />
          </linearGradient>
          <clipPath id="hero-body">
            <rect x="1" y="36" width={W - 2} height={H - 37} rx="0" />
          </clipPath>
        </defs>

        {/* Window frame */}
        <rect x="0.5" y="0.5" width={W - 1} height={H - 1} rx="12" className="hero-frame" />
        <path d={`M0.5 36.5H${W - 0.5}`} className="hero-wire" />
        {[20, 36, 52].map((cx) => (
          <circle key={cx} cx={cx} cy="18" r="4" className="hero-wire" />
        ))}
        <text x="76" y="22" className="hero-mono hero-dim">
          inventory/service.py
        </text>
        <path d={`M48.5 36.5V${H - 0.5}`} className="hero-wire" />

        {/* Code lines */}
        {LINES.map(([indent, width], i) =>
          width ? (
            <g key={i}>
              <text x="38" y={lineY(i) + 4} textAnchor="end" className="hero-mono hero-faint">
                {i + 1}
              </text>
              <rect
                x={64 + indent}
                y={lineY(i) - 4}
                width={width}
                height="8"
                rx="2"
                className="hero-code"
              />
            </g>
          ) : null,
        )}

        {/* Findings: each appears as the beam crosses its line */}
        {MARKS.map((m) => {
          const y = lineY(m.line)
          const [indent, width] = LINES[m.line]
          const delay = `${(((y - TOP) / (H - TOP)) * SCAN_S).toFixed(2)}s`
          return (
            <g
              key={m.line}
              className={`hero-mark hero-${m.tone}`}
              style={{ animationDelay: delay }}
            >
              <rect x="49" y={y - 10} width={W - 50} height="20" className="hero-row" />
              <rect
                x={64 + indent}
                y={y - 4}
                width={width}
                height="8"
                rx="2"
                className="hero-hit"
              />
              <circle cx={W - 196} cy={y} r="3.5" className="hero-dot" />
              <text x={W - 184} y={y + 4} className="hero-mono hero-label">
                {m.label}
              </text>
            </g>
          )
        })}

        {/* Scan beam */}
        <g clipPath="url(#hero-body)">
          <rect
            x="0"
            y={TOP - 64}
            width={W}
            height="64"
            fill="url(#hero-beam)"
            className="hero-beam"
          />
        </g>
      </svg>
    </div>
  )
}
