import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { Logo as BrandLogo } from './Logo'
import type { User } from '../lib/types'

function initialTheme(): 'light' | 'dark' {
  try {
    const saved = localStorage.getItem('devpilot-theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* storage unavailable */
  }
  return 'dark' // dark-first; the light theme is opt-in
}

export function applyTheme(theme: 'light' | 'dark') {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem('devpilot-theme', theme)
  } catch {
    /* ignore */
  }
}

const NAV = [
  {
    to: '/',
    label: 'Repositories',
    icon: 'M3 4.5A1.5 1.5 0 0 1 4.5 3h3l1.5 2h6.5A1.5 1.5 0 0 1 17 6.5v8a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z',
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: 'M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4',
  },
]

function Icon({ d }: { d: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4 shrink-0" fill="none">
      <path
        d={d}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// compact: mark only below 640px, where the wordmark pushed the top bar past a 375px viewport.
function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" aria-label="DevPilot, repositories">
      <BrandLogo
        size={30}
        className="text-[17px]"
        wordmarkClassName={compact ? 'hidden sm:inline' : ''}
      />
    </Link>
  )
}

export function Layout({ user, children }: { user: User; children: ReactNode }) {
  const [theme, setTheme] = useState(initialTheme)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  // Repository and review pages live under Repositories.
  const active = pathname.startsWith('/settings') ? 1 : 0

  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }
  const signOut = async () => {
    await api.logout().catch(() => undefined)
    qc.clear()
    navigate('/login')
  }
  const quiet = 'rounded-control text-muted hover:bg-subtle hover:text-fg'
  const llm = settings.data?.llm

  return (
    <div className="min-h-screen lg:pl-60">
      {/* Sidebar, 1024px and up */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-line bg-panel lg:flex">
        <div className="flex h-14 items-center px-5">
          <Logo />
        </div>
        <nav aria-label="Main" className="relative mt-2 px-3">
          <span
            aria-hidden
            className="nav-indicator absolute top-1.5 left-3 h-6 w-0.5 rounded-full bg-accent"
            style={{ transform: `translateY(${active * 36}px)` }}
          />
          {NAV.map((n, i) => (
            <Link
              key={n.to}
              to={n.to}
              aria-current={i === active ? 'page' : undefined}
              className={`flex h-9 items-center gap-3 rounded-control pr-3 pl-4 text-sm ${i === active ? 'bg-subtle font-medium text-fg' : 'text-muted hover:bg-subtle/60 hover:text-fg'}`}
            >
              <Icon d={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto space-y-3 border-t border-line p-4 text-[13px]">
          <div
            className="flex items-center gap-2 text-muted"
            title="From server configuration; not a live connection check"
          >
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${llm?.configured ? 'bg-ai' : 'bg-faint'}`}
            />
            <span className="truncate">
              {llm?.configured ? `AI: ${llm.model ?? llm.provider}` : 'AI review off'}
            </span>
          </div>
          <p className="truncate text-muted" title={user.email}>
            {user.email}
          </p>
          <div className="flex gap-1">
            <button
              onClick={toggle}
              className={`h-8 px-2 ${quiet}`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            >
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
            <button onClick={signOut} className={`h-8 px-2 ${quiet}`}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Top bar, below 1024px */}
      <header className="app-bar sticky top-0 z-10 border-b border-line lg:hidden">
        <div className="flex h-14 items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <Logo compact />
          <nav className="flex gap-1" aria-label="Main">
            {NAV.map((n, i) => (
              <Link
                key={n.to}
                to={n.to}
                aria-current={i === active ? 'page' : undefined}
                className={`inline-flex h-8 items-center rounded-control px-2 text-sm sm:px-3 ${i === active ? 'bg-subtle font-semibold text-fg' : 'text-muted hover:bg-subtle/60 hover:text-fg'}`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1 text-sm">
            <button
              onClick={toggle}
              className={`h-8 px-2 ${quiet}`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            >
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
            <button onClick={signOut} className={`h-8 px-2 ${quiet}`}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main
        key={pathname}
        className="page-enter mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10 lg:px-10"
      >
        {children}
      </main>
    </div>
  )
}

applyTheme(initialTheme())
