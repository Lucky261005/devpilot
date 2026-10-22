import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { HeroScene } from '../components/HeroScene'
import { Logo } from '../components/Logo'
import { Button, ErrorBox, Field, inputClass } from '../components/ui'
import { api } from '../lib/api'
import { useScanLine } from '../lib/scanLine'

/*
 * The front screen. Concept (DESIGN.md): the page is the file under review. A gutter of line
 * numbers runs down the left, a fixed scan line follows the reader, and each claim that crosses
 * it gets a margin verdict. The sign-in form stays in the first screen: this is the app's door.
 */

function SignIn() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const m = useMutation({
    mutationFn: () =>
      mode === 'login' ? api.login(email, password) : api.register(email, password),
    onSuccess: (user) => {
      qc.setQueryData(['me'], user)
      navigate('/')
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    m.mutate()
  }
  return (
    <div id="sign-in" className="scroll-mt-24">
      <form
        onSubmit={submit}
        aria-label={mode === 'login' ? 'Sign in' : 'Create account'}
        className="space-y-4 rounded-card border border-line bg-panel/85 p-5 backdrop-blur-sm"
      >
        <Field label="Email">
          <input
            className={inputClass}
            type="email"
            aria-label="Email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password" hint={mode === 'register' ? 'At least 10 characters.' : undefined}>
          <input
            className={inputClass}
            type="password"
            aria-label="Password"
            required
            minLength={mode === 'register' ? 10 : undefined}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {m.error ? (
          <ErrorBox
            error={m.error}
            title={mode === 'login' ? 'Sign-in failed' : 'Could not create account'}
          />
        ) : null}
        <Button variant="primary" type="submit" disabled={m.isPending} className="lp-cta w-full">
          {m.isPending ? 'Please wait' : mode === 'login' ? 'Sign in' : 'Create account'}
        </Button>
      </form>
      <p className="mt-4 text-sm text-muted">
        {mode === 'login' ? 'No account?' : 'Already registered?'}{' '}
        <button
          type="button"
          className="lp-link font-medium text-fg"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            m.reset()
          }}
        >
          {mode === 'login' ? 'Create one' : 'Sign in'}
        </button>
      </p>
    </div>
  )
}

type Tone = 'ok' | 'danger' | 'warn' | 'accent'

/** A margin finding. Stamps in when its block crosses the scan line. */
function Verdict({ tone, code, children }: { tone: Tone; code: string; children: string }) {
  return (
    <p className={`lp-verdict lp-${tone}`} data-stamp>
      <span className="lp-verdict-code">{code}</span> {children}
    </p>
  )
}

const STAGES: [string, string, string][] = [
  [
    'Import',
    'ZIP, local Git path or GitHub',
    'Secret files are deleted on the way in. Nothing from the repository is executed.',
  ],
  [
    'Analyze',
    'Ruff, Bandit, DevPilot DP001',
    'Deterministic rules run first. The same code always produces the same findings.',
  ],
  [
    'Ask',
    'Optional local or hosted LLM',
    'Only repositories you opt in. Repository text is marked untrusted in the prompt.',
  ],
  [
    'Verify',
    'Path, line range, quoted code',
    'Every model finding must quote code that exists at the lines it cites, or it is dropped.',
  ],
  [
    'Report',
    'Findings, diffs, test ideas',
    'Analyzer output and model hypotheses are labelled apart, with their evidence.',
  ],
]

export function LoginPage() {
  const root = useRef<HTMLDivElement>(null)
  useScanLine(root)

  return (
    <div ref={root} data-theme="dark" className="lp hero relative isolate min-h-screen text-fg">
      <a href="#sign-in" className="lp-skip">
        Skip to sign in
      </a>

      {/* Fixed reader: the scan line and its line readout in the gutter. */}
      <div aria-hidden className="lp-scan">
        <span className="lp-scan-readout">L001</span>
      </div>

      <header className="lp-frame relative z-10 flex h-20 items-center justify-between">
        <a href="#top" aria-label="DevPilot, back to top">
          <Logo size={40} className="text-[21px]" />
        </a>
        <nav
          aria-label="Sections"
          className="flex gap-4 font-mono text-[12px] text-muted md:gap-6 md:text-[13px]"
        >
          <a className="lp-nav" href="#pipeline">
            Pipeline
          </a>
          <a className="lp-nav" href="#check">
            The check
          </a>
          <a className="lp-nav" href="#numbers">
            Numbers
          </a>
          <a className="lp-nav hidden md:inline" href="#sign-in">
            Sign in
          </a>
        </nav>
      </header>

      <main id="top" className="relative z-10">
        {/* 1. Hero */}
        <section
          className="lp-frame lp-block grid min-h-[calc(100svh-4rem)] items-center gap-10 pb-16 lg:grid-cols-12"
          data-lines
        >
          <div className="lg:col-span-6">
            <p className="hero-rise font-mono text-[13px] text-accent">
              Analyzers first. Every AI finding checked.
            </p>
            <h1 className="lp-display hero-rise mt-4">
              Code review
              <br />
              made provable
            </h1>
            <p className="hero-rise mt-5 max-w-md text-[17px] leading-[1.55] text-muted">
              DevPilot runs deterministic analyzers on your repository, then lets a language model
              suggest more. A model finding survives only if the code it quotes is really there.
            </p>
            <div className="hero-rise mt-8 max-w-sm">
              <SignIn />
            </div>
          </div>
          <div className="hidden lg:col-span-6 lg:block">
            <HeroScene />
          </div>
        </section>

        {/* 2. Pipeline: a real sequence, so it is numbered. */}
        <section
          id="pipeline"
          className="lp-frame lp-block py-16 md:py-20"
          aria-labelledby="pipeline-h"
          data-lines
        >
          <h2 id="pipeline-h" className="lp-h2">
            What happens when you press review
          </h2>
          <ol className="mt-12 border-t border-line">
            {STAGES.map(([name, what, why], i) => (
              <li
                key={name}
                className="lp-stage group grid gap-2 border-b border-line py-6 md:grid-cols-12 md:items-baseline"
                data-reveal
              >
                <span className="font-mono text-[13px] text-faint md:col-span-1">0{i + 1}</span>
                <span className="lp-stage-name md:col-span-4">{name}</span>
                <span className="font-mono text-[13px] text-accent md:col-span-3">{what}</span>
                <span className="text-[15px] leading-[1.55] text-muted md:col-span-4">{why}</span>
                <span className="md:col-span-11 md:col-start-2">
                  <Verdict tone="ok" code="pass">{`stage ${i + 1} of 5`}</Verdict>
                </span>
              </li>
            ))}
          </ol>
          <div className="lp-margin">
            <Verdict tone="accent" code="L1">
              pipeline order is fixed
            </Verdict>
          </div>
        </section>

        {/* 3. The check: the signature moment. */}
        <section
          id="check"
          className="lp-frame lp-block py-16 md:py-20"
          aria-labelledby="check-h"
          data-lines
        >
          <h2 id="check-h" className="lp-h2 max-w-3xl">
            A model can say anything. DevPilot reads the file before it believes it.
          </h2>
          <div className="mt-14 grid gap-6 lg:grid-cols-2">
            <figure className="lp-claim min-w-0" data-reveal>
              <figcaption className="lp-claim-head">
                <span>LLM hypothesis</span>
                <span className="font-mono">inventory/store.py:22-23</span>
              </figcaption>
              <p className="lp-claim-body">
                “<code>read_config</code> opens the file and never closes it if{' '}
                <code>json.loads</code> raises.”
              </p>
              <pre className="lp-code" aria-label="Quoted source, lines 22 and 23">
                <span className="lp-ln">22</span>
                {'    f = open(path)\n'}
                <span className="lp-ln">23</span>
                {'    return json.loads(f.read())'}
              </pre>
              <Verdict tone="ok" code="verified">
                quoted code found at L22-23
              </Verdict>
            </figure>
            <figure className="lp-claim min-w-0" data-reveal>
              <figcaption className="lp-claim-head">
                <span>LLM hypothesis</span>
                <span className="font-mono">inventory/store.py:48</span>
              </figcaption>
              <p className="lp-claim-body">
                “<code>delete_item</code> builds its SQL query with string formatting.”
              </p>
              <pre className="lp-code" aria-label="Quoted source, line 48">
                <span className="lp-ln">48</span>
                {'    cur.execute(f"DELETE FROM items WHERE id={id}")'}
              </pre>
              <Verdict tone="danger" code="rejected">
                no line 48; quote not in file
              </Verdict>
            </figure>
          </div>
          <p className="mt-8 max-w-2xl text-[15px] leading-[1.55] text-muted">
            The rejected one is never shown as a finding. It stays in the run log with its reason,
            so you can see what the model tried.
          </p>
        </section>

        {/* 4. Numbers, including the unflattering one. */}
        <section
          id="numbers"
          className="lp-frame lp-block py-16 md:py-20"
          aria-labelledby="numbers-h"
          data-lines
        >
          <h2 id="numbers-h" className="lp-h2">
            Measured on a label-blind benchmark
          </h2>
          <dl className="mt-12 grid gap-px overflow-hidden rounded-card border border-line bg-line md:grid-cols-3">
            {[
              [
                '9/13',
                'seeded defects found by the analyzers alone, with 0 false alarms on 4 clean cases.',
              ],
              [
                '0',
                'extra valid findings from the local 3B model. It is shown here because it is true.',
              ],
              [
                '1.2M',
                'lines of real library code scanned by rule DP001 with 0 hits, as a false-positive check.',
              ],
            ].map(([n, claim]) => (
              <div key={n} className="bg-bg p-6 md:p-8" data-reveal>
                <dt className="lp-num">{n}</dt>
                <dd className="mt-4 max-w-xs text-[15px] leading-[1.55] text-muted">{claim}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-6 font-mono text-[12px] text-faint">
            Dataset v1: 17 synthetic cases. The rules were tuned on it, so it is a development set,
            not a promise. Full method in docs/evaluation.md.
          </p>
          <Verdict tone="warn" code="note">
            small dataset, read the caveats
          </Verdict>
        </section>

        {/* 5. Local */}
        <section
          className="lp-frame lp-block grid gap-12 py-16 md:py-20 lg:grid-cols-2 lg:items-end"
          aria-labelledby="local-h"
          data-lines
        >
          <h2 id="local-h" className="lp-statement" data-reveal>
            Runs on a laptop. The model, the database and your code never leave it.
          </h2>
          <dl className="grid gap-6 font-mono text-[13px] sm:grid-cols-2">
            {[
              ['Model', 'qwen2.5-coder 3B via Ollama, on 127.0.0.1'],
              ['Backend', 'FastAPI, SQLAlchemy, a database-backed job queue'],
              ['Frontend', 'React, TypeScript, Vite'],
              ['Cost', '₹0. No paid API, no hosting'],
            ].map(([k, v]) => (
              <div key={k} className="border-t border-line pt-4" data-reveal>
                <dt className="text-faint">{k}</dt>
                <dd className="mt-1 text-fg">{v}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>

      <footer className="lp-frame relative z-10 flex flex-wrap items-center justify-between gap-4 border-t border-line py-10 text-[13px] text-muted">
        <a href="#sign-in" className="lp-cta-link">
          Sign in and review a repository
        </a>
        <span className="font-mono">DevPilot</span>
      </footer>
    </div>
  )
}
