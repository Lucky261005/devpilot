/*
 * DevPilot mark: a source file whose lines a scan bar sweeps, ending in a check. It plays once on
 * load and again on hover (styles: .logo-* in index.css). Decorative; the wordmark carries the name.
 */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className="logo-mark shrink-0"
    >
      <rect x="1" y="1" width="30" height="30" rx="8" className="logo-frame" />
      <rect x="7" y="8" width="12" height="2.5" rx="1.25" className="logo-line" />
      <rect x="10" y="14.75" width="9" height="2.5" rx="1.25" className="logo-line" />
      <rect x="7" y="21.5" width="7" height="2.5" rx="1.25" className="logo-line" />
      <path d="M19.5 22l2.6 2.6 4.4-5.2" className="logo-check" />
      <rect x="4" y="5" width="24" height="1.5" rx="0.75" className="logo-scan" />
    </svg>
  )
}

export function Logo({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <span
      className={`logo inline-flex items-center gap-3 font-semibold tracking-tight ${className}`}
    >
      <LogoMark size={size} />
      DevPilot
    </span>
  )
}
