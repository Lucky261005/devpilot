# DevPilot production-readiness audit

**Date:** 2026-10-20. **Scope:** the whole repository as it is on disk. **Method:** read the code and
configuration, ran every check CI runs, and relied on flows exercised end to end in this session
(browser, API and Playwright). Nothing was changed for this audit. Every claim below cites a file,
a command result, or says "not verified".

## 1. Summary

DevPilot is in good shape as a **local, single-machine tool**: 103 backend tests and 2 end-to-end
tests pass, lint, format and type checks are clean on the backend, and the core flow (sign up,
import, review, read findings, give feedback) works. It is **not yet deployable to the public
internet**. Blockers, in order:

1. **No version control history.** `git log`: "branch 'master' does not have any commits yet"; no
   remote. CI (`.github/workflows/ci.yml`) has never run and only triggers on pushes to `main`.
2. **CI would fail today:** `prettier --check` flags `frontend/src/lib/scanLine.ts` and
   `frontend/src/pages/LoginPage.tsx`.
3. **Open registration plus LLM review** lets anyone on the internet create accounts and spend
   your LLM budget or GPU (rate limit is per user, `reviews_per_hour=30`, with unlimited users).
4. **No TLS, missing security headers, API docs public** (details in section 5).
5. **The Docker stack has never been run** (daemon off in every session), so the deployment path is
   unverified.

## 2. Architecture and stack (as built)

| Layer | What is there | Evidence |
|---|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind 4, TanStack Query, React Router 7, GSAP (front screen only, lazy) | `frontend/package.json` |
| Front screen | Prerendered at build time into `dist/login.html`, hydrated in the browser | `frontend/scripts/prerender.mjs`, `src/main.tsx` |
| API | FastAPI, 32 routes under `/api` (auth, repositories, reviews, GitHub, settings, health) | `backend/app/api/*.py` |
| Jobs | Database-backed queue (`review_jobs`, `SKIP LOCKED`), worker in-process locally or a separate container | `app/workers/queue.py`, `docker-compose.yml` |
| Database | SQLAlchemy 2 + Alembic (1 migration, no drift: `alembic check` reports none). SQLite locally, PostgreSQL 16 in compose | `backend/alembic/versions/` |
| Analyzers | Ruff, Bandit, DevPilot DP001 (subprocesses and AST) | `app/analyzers/` |
| LLM | `LLMProvider` protocol: Anthropic (`messages.parse`) or Ollama (`/api/chat`, JSON schema); every finding validated against path, lines and quoted code | `app/ai/provider.py`, `app/services/findings.py` |
| Auth | Email + password (argon2), server-side sessions in DB, httpOnly SameSite=Lax cookie, CSRF header | `app/api/auth.py`, `app/main.py` |
| Packaging | Backend Dockerfile (non-root, runs `alembic upgrade head`), frontend nginx image, compose with Postgres + API + worker + web | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` |
| CI | Backend: ruff, format, mypy, bandit, pytest, pip-audit. Frontend: eslint, prettier, typecheck, tests, build, npm audit. E2E Playwright. Evaluation job | `.github/workflows/ci.yml` |

## 3. Feature status

Legend: **1** fully functional and verified · **2** partial · **3** UI-only/mocked · **4** broken ·
**5** not implemented. "Verified" means exercised end to end in this project, not just present.

| Feature | Status | Evidence / gap |
|---|---|---|
| Register, sign in, sign out, session expiry | 1 | `test_auth_flow_and_session_cookie`, Playwright sign-up, used in the browser |
| Login throttling | 2 | 10 attempts/min per IP, **in-process memory** (`app/core/ratelimit.py` says so); resets on restart, not shared across replicas |
| Password reset, email verification, account deletion | 5 | No routes in `app/api/auth.py` |
| ZIP import (safe extraction, secrets removed) | 1 | `test_ingestion.py`, Playwright imports a ZIP |
| Local Git path import | 1 | Allowed-roots check tested; demo repo imported in the browser. Not meaningful on a hosted server |
| GitHub OAuth, import, PR list and PR review | 2 | Covered by mocked tests (`test_github_import_pulls_and_pr_review`, `test_oauth_state_is_validated`); **never run against real GitHub** (no OAuth app configured) |
| GitHub write-back (PR comments, checks, webhooks) | 5 | No such code; reviews are pull-only and manual |
| Whole-repo and diff reviews (analyzers) | 1 | `test_full_review_static_only`, `test_local_diff_review_reports_only_changed_lines`, real review run in the browser |
| LLM review, Ollama | 1 (works), quality weak | Verified live; label-blind benchmark: 0 unique valid findings, AI-only 0/13 (`docs/evaluation.md`) |
| LLM review, Anthropic | 2 | Code path unit-tested with a fake client (`test_provider.py`); **never called live** (₹0 budget) |
| AI consent per repository | 1 | `test_ai_review_requires_consent`, UI toggle |
| Finding validation and dedupe | 1 | `test_full_review_with_ai_validates_and_dedupes` |
| Findings UI: filters, search, keyboard nav, code highlight | 1 | Checked in the browser after the redesign |
| Test suggestions | 2 | Generated and listed; never executed by design. Heuristic quality unmeasured |
| Feedback on findings | 1 | Playwright gives feedback; `/api/feedback/summary` exists but **has no UI** (status 3 for that view) |
| Code search | 1 | `test_import_index_search_and_file_view` |
| Settings page | 1 | Values come from `/api/settings`; LLM status is configuration, **not a live health check** |
| Delete repository (cascade) | 1 | `test_delete_repository_cascades`, dialog verified in browser |
| Snapshot retention cleanup | 2 | `python -m app.cli cleanup` exists; **nothing schedules it** |
| Expired session cleanup | 5 | Expired sessions are rejected but never deleted |
| Dashboard / review-history page across repos | 5 | Not built; history is per repository |
| Evaluation harness | 1 | 103 tests include leakage and artifact tests; reports reproducible |
| Docker compose deployment | 2 | Files reviewed; **never built or run**. One bug found (section 4, H4) |

No hardcoded sample data is shown as real data in the app. The front screen's two example
hypotheses and the hero illustration are illustrative and labelled by context; the benchmark
numbers on it match `docs/evaluation.md`.

## 4. Issues by priority

### Critical (must fix before any public deployment)

| ID | Issue | Evidence | Fix |
|---|---|---|---|
| C1 | No commits, no remote, CI never ran | `git log` fails; `git remote -v` empty | First commit on `main`, push to GitHub, see CI green |
| C2 | Open sign-up exposes compute and LLM spend | `POST /api/auth/register` has no gate; per-user limits only | Invite code or allow-list env var for registration in production; global daily review cap |
| C3 | No HTTPS story; `cookie_secure` defaults to false | `.env.example`, nginx listens on 80 only | Terminate TLS at a reverse proxy or host; set `DEVPILOT_COOKIE_SECURE=true` in production and refuse to start otherwise |

### High

| ID | Issue | Evidence | Fix |
|---|---|---|---|
| H1 | CI fails on formatting | `prettier --check`: 2 files | Run prettier; add a pre-commit or make it part of the dev loop |
| H2 | CI push trigger targets `main`, local branch is `master` | `ci.yml` `branches: [main]` | Rename branch to `main` before the first push |
| H3 | Security headers missing: no CSP, HSTS, `frame-ancestors`/X-Frame-Options, Referrer-Policy | `app/main.py` sets only `x-content-type-options`; `nginx.conf` sets none | Add them in nginx (static UI) and the API middleware |
| H4 | Prerendered front screen not served in Docker | `nginx.conf`: `try_files $uri /index.html;` never tries `login.html` | `try_files $uri $uri.html /index.html;` |
| H5 | Rate limits are in-process | `ratelimit.py` shortcut comment | Move to a DB table (already have Postgres) before running more than one API process |
| H6 | `--forwarded-allow-ips=*` trusts any `X-Forwarded-For` | `backend/Dockerfile` CMD | Safe only while the API is reachable solely through nginx; pin to the proxy's address or network |
| H7 | Docker stack unverified | Never run | Build and run compose once; run Playwright against it |
| H8 | No backups for Postgres or snapshots | compose volumes only | Scheduled `pg_dump` plus volume backup; document restore |

### Medium

| ID | Issue | Fix |
|---|---|---|
| M1 | API docs (`/docs`, `/openapi.json`) public in production | `docs_url=None, openapi_url=None` when `env != development` |
| M2 | Postgres password `devpilot` hardcoded in compose | Take it from `.env` |
| M3 | Snapshot and session cleanup never scheduled | Run cleanup from the worker loop once a day |
| M4 | No password reset or account deletion | Needed for any real users; account deletion also for privacy |
| M5 | LLM status not a live check | Add `/api/health/llm` that pings the provider with a timeout |
| M6 | SPA returns 200 for unknown URLs | Serve a 404 page with status 404 from nginx for non-app paths, or accept for an app |
| M7 | Logs: JSON logging exists; no error tracking or metrics | Add basic request metrics and an error sink before real users |

### Low

| ID | Issue | Fix |
|---|---|---|
| L1 | 5 eslint `react-refresh/only-export-components` warnings | Move helpers out of component files when touched |
| L2 | No og:image / canonical (no public URL yet) | Add when the domain exists |
| L3 | Feedback summary endpoint has no UI | Surface it on Settings or a small report page |
| L4 | Leftover local test data (account `ui-check@example.com`, demo repo, reviews) | Delete from the local DB; never ship `*.db` (already ignored) |

## 5. Security and data-loss review

**Done well (verified in code or tests):** argon2 password hashing with a timing-equalised login;
server-side sessions with expiry; httpOnly SameSite=Lax cookie plus a custom CSRF header
(`test_csrf_header_required_for_mutations`); per-user ownership checks on every repository and
review (`test_other_users_cannot_see_or_touch_repository`); upload size and missing-length guards;
safe ZIP extraction and secret-file removal; local import confined to allowed roots; GitHub tokens
encrypted with Fernet and `DEVPILOT_SECRET_KEY` required outside development; repository text
marked untrusted in LLM prompts and every model finding validated against the source; Ollama kept
on 127.0.0.1; `.env` and `*.db` git-ignored; non-root backend container.

**Risks:** C2, C3, H3, H5, H6, M1, M2 above. **Data loss:** no backups (H8); deleting a repository is
immediate and permanent (confirmed by dialog, no undo). **Secrets:** none found in tracked files;
`backend/.env` exists locally and is ignored. `pip-audit` was not run in this audit (network);
`npm audit --omit=dev` reports 0 vulnerabilities.

## 6. AI quality and reliability

- **Quality:** on the label-blind benchmark the local 3B model contributed **0 unique valid
  findings**; analyzers found 9/13 (development set). The product's value today is the analyzers plus
  the validation layer, not the model. Claude has never been measured (₹0 budget).
- **Reliability:** one case makes Ollama loop until its repeat limit and return HTTP 500; DevPilot
  records the failure and keeps analyzer results (`test_ai_failure_keeps_static_results`). Prompts
  over 75% of the context window are refused, not truncated.
- **Gaps:** no held-out validation set; no live provider health check; no per-deployment spend cap
  (relevant once a paid provider is used).

## 7. Missing tests

1. Docker compose smoke test (build, migrate, sign up, import, review).
2. Frontend: hydration of the prerendered `/login` (no mismatch), and the new confirm dialog.
3. Rate limiting across processes (after H5).
4. Registration gate (after C2) and cookie-secure enforcement (after C3).
5. A live-provider test path for Anthropic, opt-in (the `live_llm` marker exists, no key to run it).

## 8. Proposed production architecture (₹0-compatible first)

- **Single small VM or home server** running the existing compose stack behind **Caddy** (automatic
  HTTPS), API reachable only through the proxy.
- PostgreSQL in compose with a nightly `pg_dump` to another disk; snapshots volume backed up.
- LLM: **off or Ollama on the same machine** for a demo; Anthropic only with a spend cap and
  invite-only registration.
- Registration by invite code; one worker process; cleanup inside the worker.
- GitHub OAuth app pointed at the public URL.

## 9. Acceptance criteria per major feature

| Feature | Accepted when |
|---|---|
| Deployment | `docker compose up` on a clean machine serves the UI over HTTPS; Playwright passes against it |
| Auth | Only invited emails can register; cookies are `Secure`; login throttling survives a restart |
| Import | ZIP and GitHub imports succeed on a real public repo; failures show the reason |
| Review | Analyzer review of a 5k-file repo finishes within the job timeout; status updates without reload |
| AI review | With a provider configured, findings are validated and labelled; provider down shows "unavailable" and analyzer results still appear |
| GitHub | OAuth round trip against real GitHub; PR list and PR review work on a real public PR |
| Data safety | A backup can be restored into a fresh stack and shows the same repositories and findings |
| Security | Response headers include CSP, HSTS, frame-ancestors; `/docs` returns 404 in production |

## 10. Phased implementation checklist

Each milestone is small and independently testable. Do them in this order.

| # | Milestone | Likely files | Steps | Tests | Done when |
|---|---|---|---|---|---|
| 1 | **Version control + green CI** | `frontend/src/lib/scanLine.ts`, `frontend/src/pages/LoginPage.tsx`, git | Run prettier; rename branch to `main`; first commit; create GitHub repo; push | Existing CI | All CI jobs green on GitHub |
| 2 | Serve the prerendered page in Docker | `frontend/nginx.conf` | `try_files $uri $uri.html /index.html` | Curl `/login` from the container shows `<h1>` | Container serves prerendered HTML |
| 3 | Security headers + hide docs | `frontend/nginx.conf`, `backend/app/main.py` | Add CSP, HSTS (when TLS), frame-ancestors, Referrer-Policy; disable docs outside dev | New API test for headers and `/docs` 404 | Headers present; test passes |
| 4 | Registration gate | `app/core/config.py`, `app/api/auth.py`, `.env.example`, `LoginPage.tsx` (invite field only if gated) | `DEVPILOT_INVITE_CODE`; reject register without it when set | API test: with and without code | Unknown visitors cannot register |
| 5 | Secure cookies enforced | `app/core/config.py` | Refuse to start in production with `cookie_secure=false` | Settings unit test | Misconfigured prod fails fast |
| 6 | DB-backed rate limits | `app/core/ratelimit.py`, new migration | Table of hits with timestamps, or a counter per window | Test across two app instances | Limits survive restart |
| 7 | Compose smoke run | `docker-compose.yml`, `.github/workflows/ci.yml` | Postgres password from env; add a CI job that builds and runs compose, then Playwright | The new CI job | Stack verified in CI |
| 8 | Scheduled cleanup | `app/workers/queue.py`, `app/cli.py` | Run snapshot + session cleanup daily from the worker | Unit test with a fake clock | Old snapshots and sessions disappear |
| 9 | Backups | `scripts/backup.sh`, `docs/` | Nightly `pg_dump` + volume tarball; restore doc | Manual restore drill | Restore reproduces data |
| 10 | Live LLM health | `app/main.py` (next to `/api/settings`), `SettingsPage.tsx` | Ping provider with a short timeout | Mocked provider test | Settings shows connected / unavailable truthfully |
| 11 | Real GitHub verification | `.env`, docs | Create OAuth app, run the flow against a public repo and PR | Manual checklist | GitHub status moves from 2 to 1 |
| 12 | Account lifecycle | `app/api/auth.py`, migration, UI | Password change and account deletion (reset needs email; defer) | API tests | Users can leave and remove their data |

## 11. The single most important next step

**Milestone 1: format the two files, rename the branch to `main`, make the first commit, and push to
a new GitHub repository so CI runs.** Nothing in the project is under version control yet, so every
later fix is unrecorded and unreviewable, and the existing CI (which already covers lint, types,
tests, audits and end-to-end) has never proven anything. It is also the smallest step: two
formatting fixes and git commands.
