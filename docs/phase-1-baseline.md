# Phase 1: verified baseline

**Date:** 2026-10-23. **Commit:** `d1c8eea` on `main` (the only commit; working tree clean; no
remote). No source code was changed in this phase. The broader issue list is in
[production-readiness-audit.md](production-readiness-audit.md); this document is the measured
baseline that later phases must not regress.

## 1. Architecture (confirmed against the code, not the historical notes)

The historical notes were accurate with two refinements: the database is **SQLAlchemy over SQLite
locally and PostgreSQL in Docker**, and the provider abstraction has **two** implementations
(Ollama and Anthropic), chosen by `DEVPILOT_LLM_PROVIDER`.

```
Browser ── React 19 SPA (Vite 6, TS 5.8, Tailwind 4, TanStack Query 5, React Router 7)
   │          /login prerendered at build (scripts/prerender.mjs), hydrated by main.tsx
   │  cookie session + x-devpilot-csrf header
   ▼
FastAPI 0.143 (app/main.py: guard middleware, /api/settings, /api/health)
   ├─ api/auth.py         register, login, logout, me         (argon2, DB sessions)
   ├─ api/repositories.py ZIP / local Git / GitHub import, files, search, delete
   ├─ api/reviews.py      create review, status, findings, diffs, tests, feedback
   └─ api/github.py       OAuth, repo list, PR list/detail
        │ enqueue
        ▼
review_jobs table ── Worker (app/workers/queue.py; in-process locally, own container in compose)
        └─ services/review.py
             ├─ analyzers/  Ruff 0.17 (--isolated), Bandit 1.9, DP001 (AST)   subprocess, no shell
             ├─ ai/context.py + ai/provider.py  OllamaProvider (httpx) | AnthropicProvider (SDK 1.15)
             └─ services/findings.py  validate path/lines/quoted code, dedupe
Storage: SQLAlchemy 2.1 + Alembic 1.20 (1 migration) · snapshots under DEVPILOT_DATA_DIR
```

**Toolchain:** Python 3.12.2 via uv 0.13.1 (`backend/.python-version`, `uv.lock`); Node 22.14.0,
npm 10.9.2 (`package-lock.json`); Ollama 0.40.6 with `qwen2.5-coder:3b`.

**Entry points and commands**

| What | Command (from) |
|---|---|
| API (+ in-process worker) | `uv run uvicorn app.main:app --port 8000` (backend/) |
| Standalone worker | `python -m app.workers.queue` (backend/) |
| Maintenance | `python -m app.cli cleanup` (backend/) |
| Migrations | `uv run alembic upgrade head` (backend/; Docker runs it on start) |
| Frontend dev | `npm run dev` → http://localhost:5173, proxies `/api` (frontend/) |
| Frontend build | `npm run build` (tsc, vite build, SSR build, prerender) |
| Evaluation | `evaluation/scripts/run_eval.py`, `run_label_blind.sh` (see evaluation/README.md) |
| Full stack | `docker compose up --build` (never run; Docker daemon off) |

## 2. Commands executed and results (2026-10-23)

| Command | Result |
|---|---|
| `git status`, `git branch -a`, `git remote -v`, `git log` | clean; `main` only; no remote; 1 commit |
| `git ls-files` for env files | only `.env.example` tracked; `backend/.env` exists locally and is ignored |
| `uv run pytest -q` | **103 passed, 2 deselected** (opt-in `live_llm`) |
| `uv run ruff check .` / `ruff format --check .` | all checks passed / 50 files formatted |
| `uv run mypy app` | no issues in 37 files |
| `uv run bandit -q -r app -s B404,B603,B607` | no findings |
| `alembic upgrade head` then `alembic check` (fresh SQLite) | no drift between models and migration |
| `npx eslint .` | 0 errors, 5 warnings (`react-refresh/only-export-components`) |
| `npx prettier --check src tests` | clean |
| `npm run typecheck` | 0 errors |
| `npx vitest run` | **7 passed** |
| `npm run build` | built; `dist/login.html` prerendered |
| `npx playwright test` | **2 passed** (sign up, ZIP import, review, finding, feedback; unauthenticated redirect) |
| `npm audit --omit=dev` | 0 vulnerabilities |
| `pip-audit --strict` (exported lock) | **1 vulnerability: certifi 2026.7.22, PYSEC-2026-4320, fixed in 2026.10.19.** CI's strict audit would fail |

## 3. Feature verification matrix

1 = fully functional and verified end to end · 2 = partial · 3 = UI-only/mocked · 4 = broken · 5 = not implemented

| Feature | Status | How verified / what is missing |
|---|---|---|
| Sign up, sign in, sign out, session expiry | 1 | API tests, Playwright, browser |
| Login throttle | 2 | Works; memory-only, per process |
| Password reset, email verification, account deletion | 5 | No routes |
| ZIP import | 1 | `test_ingestion.py`, Playwright |
| Local Git import | 1 | Tests + demo repo in browser; confined to `DEVPILOT_ALLOWED_LOCAL_ROOTS` |
| GitHub OAuth / import / PR list / PR review | 2 | **Mocked only** (`github_mock` in `tests/test_api.py`); never run against github.com |
| GitHub write-back (comments, checks, webhooks) | 5 | Out of scope for this phase |
| Analyzer review, whole repo and diff | 1 | Tests + live run in browser |
| LLM review via Ollama | 1 | Live runs and label-blind benchmark (quality: 0 unique valid findings) |
| LLM review via Anthropic | 2 | **Fake client only** (`tests/test_provider.py`); never called live |
| Per-repo AI consent | 1 | `test_ai_review_requires_consent`, UI |
| Finding validation and dedupe | 1 | `test_full_review_with_ai_validates_and_dedupes` |
| Findings workspace (filters, search, keys, highlight) | 1 | Browser |
| Test suggestions | 2 | Shown; never executed by design; quality unmeasured |
| Finding feedback | 1 | Playwright |
| Feedback summary | 3 | API exists and is tested; no UI |
| Code search | 1 | `test_import_index_search_and_file_view` |
| Settings | 1 | Real config values; AI status is config, not a live check |
| Delete repository | 1 | `test_delete_repository_cascades`, dialog in browser |
| Snapshot cleanup | 2 | CLI exists; not scheduled |
| Expired-session cleanup | 5 | Never deleted |
| Docker compose stack | 2 | Never built or run |

**Mocked vs real network integrations**

| Integration | In tests | Real use verified |
|---|---|---|
| Ollama HTTP API | `httpx.MockTransport` (`test_ollama_provider.py`) | Yes, on this machine |
| Anthropic API | fake client | No |
| GitHub REST + OAuth | monkeypatched client | No |
| Git CLI, Ruff, Bandit | real subprocesses | Yes |

## 4. Security and robustness review

**Authentication:** argon2 hashes, timing-equalised failed login, 32-byte session tokens stored
hashed in `sessions`, httpOnly SameSite=Lax cookie, `Secure` only when `DEVPILOT_COOKIE_SECURE=true`.
**Authorization and isolation:** every repository and review route goes through `owned_repo` /
`owned_review` (22 call sites); `test_other_users_cannot_see_or_touch_repository` passes; feedback
summary filters by user. **CSRF:** custom header required on unsafe methods (tested).
**Credentials:** GitHub tokens Fernet-encrypted; `DEVPILOT_SECRET_KEY` mandatory outside
development; no real secrets in tracked files (pattern scan before the first commit found only test
tokens, a redaction regex and the seeded fixture password). **Uploads:** size cap, 411 without
Content-Length, safe ZIP extraction, secret files removed, nothing from a repository executed;
analyzers run without a shell and Ruff with `--isolated`. **Background jobs:** `SKIP LOCKED`
claiming, stale-job recovery and internal errors recorded (`test_worker_recovers_stale_...`).
**Errors:** JSON errors carry a request id; AI failure keeps analyzer results.

**Critical findings**

| # | Finding | Why it matters |
|---|---|---|
| S1 | Open registration | Anyone reaching a deployed instance can create accounts and run reviews (and LLM calls) |
| S2 | No TLS and `Secure` cookies off by default | Session cookies would travel in clear text |
| S3 | Vulnerable `certifi` pinned in `uv.lock` | Known advisory; CI fails |
| S4 | Security headers absent (CSP, HSTS, frame-ancestors) and `/docs` public | Clickjacking and API surface exposure once public |
| S5 | `--forwarded-allow-ips=*` | Client IP (rate limits) spoofable if the API is ever reachable without nginx |

## 5. Persistence and filesystem assumptions

- `DEVPILOT_DATA_DIR` defaults to the **relative** path `./data`; it resolves against the directory
  uvicorn starts in. Snapshots live at `data/snapshots/<repo>/{current,review-<id>}`. The API and
  worker must share it (compose mounts one volume; a second host would need shared storage).
- `DEVPILOT_DATABASE_URL` defaults to `sqlite:///./devpilot.db`, also relative to the start
  directory. SQLite has a single writer; with the in-process worker that is fine locally, but more than
  one API process needs PostgreSQL (compose already uses it). Job claiming relies on `SKIP LOCKED`,
  which SQLite ignores, so **one worker only on SQLite**.
- Temporary work uses `tempfile.TemporaryDirectory()` (OS temp).
- Local Git import depends on host paths in `DEVPILOT_ALLOWED_LOCAL_ROOTS`; meaningless on a server.
- `git` must be on PATH (installed in the backend image).

## 6. AI provider abstraction and evaluation

`app/ai/provider.py` defines `LLMProvider` and `get_provider()`; the review pipeline only sees the
protocol. Ollama: JSON-schema `format`, temperature 0, `num_ctx` 16384, refuses prompts above 75% of
the window. Anthropic: structured output via `messages.parse`. Evaluation lives in `evaluation/`
(dataset v1, label-blind harness, reports) with tests `test_eval_scoring.py`, `test_eval_leakage.py`,
`test_eval_artifacts.py`, `test_two_step.py`, `test_ast_rules.py`. Gaps: no held-out validation set,
no live provider health check.

## 7. Deployment blockers and missing configuration

1. No remote, CI never run (after S3 is fixed, it should pass).
2. S1, S2, S4 above.
3. nginx does not serve the prerendered page (`try_files $uri /index.html`).
4. Compose: hardcoded Postgres password; never run.
5. No backups, no scheduled cleanup, no error tracking.
6. Unset for production: `DEVPILOT_SECRET_KEY`, `DEVPILOT_COOKIE_SECURE=true`,
   `DEVPILOT_FRONTEND_ORIGIN` (public URL), GitHub OAuth client and callback, provider choice.

## 8. Files that must not be rewritten without cause

These are tested, working and load-bearing. Change them surgically:

- `backend/app/ai/provider.py`, `app/ai/context.py`, `app/ai/schema.py` (provider abstraction, prompt; production prompt intentionally frozen)
- `backend/app/services/findings.py` (validation and dedupe)
- `backend/app/services/ingestion.py`, `services/indexing.py`, `services/diff.py` (safe import)
- `backend/app/workers/queue.py`, `services/review.py` (job pipeline)
- `backend/app/api/deps.py`, `app/api/auth.py`, `app/core/security.py`, `app/main.py` guard (auth, isolation, CSRF)
- `backend/app/analyzers/*` (benchmark results depend on them)
- `backend/alembic/versions/*` (add new migrations; never edit the existing one)
- `evaluation/datasets/v1/cases.py` and `evaluation/reports/**` (historical evidence)
- `frontend/src/lib/api.ts`, `lib/types.ts` (API contract), `components/ui.tsx`, `pages/*` (UI just redesigned)
- `frontend/scripts/prerender.mjs`, `src/entry-prerender.tsx`, `src/main.tsx` (hydration must match)

## 9. Prioritised implementation plan and definition of done

| Phase | Scope | Definition of done |
|---|---|---|
| **2. Green baseline in CI** | Upgrade `certifi` in `uv.lock`; nginx `try_files $uri $uri.html /index.html`; push to a private GitHub repo | All CI jobs (backend, frontend, e2e, evaluation) green on GitHub; no other code changed |
| **3. Production hardening** | Invite-gated registration; refuse production start without `cookie_secure`; security headers; disable `/docs` outside development; Postgres password from env; pin forwarded IPs | New tests for each; existing 103 + 7 + 2 still pass; a production-mode config check documented |
| **4. Run the real stack** | `docker compose up` locally; CI job that builds compose and runs Playwright against it | Compose healthy on a clean machine; Playwright green against it in CI |
| **5. Operations** | DB-backed rate limits; scheduled snapshot and session cleanup; backups with a restore drill; live LLM health on Settings | Each has a test or a recorded drill; Settings shows a truthful provider state |
| **6. GitHub for real** | OAuth app against github.com; verify import and PR review on a public repo | Manual checklist executed and recorded; feature moves from 2 to 1 |
| **7. Deploy** | One host behind Caddy (HTTPS), compose, env set, backups on | Public URL over HTTPS; Playwright smoke passes against it; restore drill passes |

Every phase also requires: the full baseline suite in section 2 re-run with results recorded, no
regression in the evaluation numbers, and no change to the files in section 8 beyond what the phase
names.
