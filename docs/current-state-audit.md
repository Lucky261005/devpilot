# DevPilot current-state audit

**Date:** 2026-10-23. **Method:** read the code and git state, ran every check below, compared
with the phase reports. No source code or configuration was changed for this audit.

## 1. Verified architecture

| Layer | As built (checked in code) |
|---|---|
| Frontend | React 19.3, TypeScript 5.8, Vite 6.4, Tailwind 4.3, TanStack Query 5, React Router 7. `/login` prerendered at build and hydrated; signed-in pages lazy-loaded |
| API | FastAPI 0.143, Python 3.12.2 (uv 0.13.1). Routes: auth, repositories, reviews, GitHub, `/api/settings`, `/api/health` |
| Database | SQLAlchemy 2.1 + Alembic 1.20, **2 migrations** (initial; GitHub token expiry + `source_branch`/`source_sha`). SQLite locally, PostgreSQL 16 in compose. `alembic check`: no drift |
| Jobs | `review_jobs` table, `SKIP LOCKED` claiming, worker in-process locally or a separate compose service |
| Analyzers | Ruff 0.17.1 (`--isolated`), Bandit 1.9.4, DevPilot DP001 (AST) |
| AI | `LLMProvider` protocol: Ollama (`qwen2.5-coder:3b`, httpx, JSON-schema output) and Anthropic (SDK 1.15, never run live). Findings validated against path, lines and quoted code. Prompt `v1`/`v2` and context `changed`/`repo` are settings; defaults v1/changed. Context budget now fits the Ollama window (`Settings.context_chars`) |
| Repository tools | `app/ai/tools.py`: read-only symbol search, snippet read, call/caller lookup, confined to the review snapshot (uncommitted, see section 2) |
| GitHub | GitHub App user-authorization flow; expiring tokens with rotating refresh, Fernet-encrypted; repositories listed from the user's installations only; branch picked in UI; import pinned to a commit SHA |
| Deployment | Backend and frontend Dockerfiles, nginx config, `docker-compose.yml` (Postgres, API, worker, web). **Never built or run** (Docker daemon off) |
| CI | `.github/workflows/ci.yml` (lint, types, bandit, tests, pip-audit, npm audit, Playwright, evaluation). **Never run**: no remote |

## 2. Git and working tree

*Updated 2026-10-23 after the commit task below; the audit itself was first written while this
work was uncommitted.*

- Branch `main`, the only branch. **No remote.** Working tree clean apart from this document.
- Commits:
  - `d1c8eea` initial commit
  - `c1aeb3f` certifi fix, nginx `login.html`, baseline report
  - `a6964fd` GitHub App integration
  - `caba0f3` **feat: add repository-aware review evaluation** (66 files): `app/ai/tools.py`,
    `ai/context.py`, `ai/schema.py`, Phase 3 parts of `core/config.py` (prompt version, context
    mode) and `services/review.py` (tools, prompt selection, telemetry), `tests/test_repo_context.py`,
    `.env.example`, `evaluation/scripts/run_eval.py`, `run_phase3.sh`, `summarize_phase3.py`,
    `evaluation/datasets/v2/`, `evaluation/reports/experiments/phase3/`, `docs/phase-3-evaluation.md`,
    `frontend/src/lib/types.ts`, `pages/ReviewPage.tsx`
  - `159ca99` **fix: fit review context within model limits** (3 files): `Settings.context_chars`
    in `core/config.py`, the budget argument in `services/review.py`, and its test in
    `tests/test_ollama_provider.py`
- The two shared files were split by content, not by filename: the Phase 3 versions of
  `config.py` and `review.py` were staged without the `context_chars` property and with the
  original `llm_max_context_chars` argument, which is the state Phase 3 was evaluated with.
- Local, ignored and never committed (checked with `git check-ignore`): `backend/.env` (includes
  `DEVPILOT_LLM_TIMEOUT_S=300`), local SQLite databases and `eval.db` files, `backend/data/`
  snapshots, per-run console logs, `CONTEXT.md`, `frontend/.shots/`.

## 3. Test results observed (2026-10-23)

Phase 3 alone (index exported to a temporary folder before `caba0f3`): backend **124 passed**,
ruff, format, mypy, bandit clean; `summarize_phase3.py` regenerated `SUMMARY.md` byte-for-byte from
the staged JSON; frontend (identical in both commits) eslint 0 errors, prettier, typecheck, 7 unit
tests, build and 2 Playwright tests passed. After `159ca99` (full tree), as below:

| Check | Result |
|---|---|
| `uv run pytest -q` | **125 passed**, 4 deselected (2 `live_llm`, 2 `live_github`) |
| `pytest -m live_github` | 2 **skipped** (no `DEVPILOT_TEST_GITHUB_*` variables) |
| ruff / ruff format / mypy / bandit | clean / 55 files formatted / no issues (39 files) / exit 0 |
| `alembic upgrade head` + `alembic check` | no drift |
| `pip-audit --strict` | no known vulnerabilities |
| eslint / prettier / typecheck | 0 errors (5 existing warnings) / clean / 0 errors |
| vitest | **7 passed** |
| `npm run build` | built, `dist/login.html` prerendered |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Playwright | **2 passed** |
| `summarize_phase3.py` | regenerates `SUMMARY.md` from tracked JSON |

## 4. Features: status against the goal

1 = done and verified end to end · 2 = partial · 5 = not implemented

| Goal | Status | Evidence / gap |
|---|---|---|
| Authenticate securely | 1 (local) | argon2, DB sessions, httpOnly cookie, CSRF header, tests. Gaps for public use: open registration, `Secure` cookie off by default, no password reset or account deletion |
| Connect GitHub with limited access | 1 | GitHub App, read-only permissions. **Verified live** on 2026-10-23 with account Lucky261005 (connection, 5 granted repositories, ungranted `octocat/Hello-World` refused). Recorded in commit `a6964fd` message only, not in a doc |
| Pick a public or private repository and branch | 1 | UI picker; live: private `Lucky261005/dgbf` |
| Import and index a specific commit | 1 | Live: `dgbf` at `main` = `11fcc666…`, SHA stored, 1 file indexed |
| **Ask AI questions grounded in repository code** | **5** | No question/chat endpoint or UI exists. Only review-time context |
| Run reviews, inspect findings and fixes | 1 | Analyzer reviews verified repeatedly; LLM findings show reasoning and suggested fix. Quality: AI adds 1 of 12 defects on held-out v2 (`docs/phase-3-evaluation.md`) |
| LLM review on large repositories | 2 | Was failing on prompt size; fixed (budget fits window, uncommitted). Then timed out at 120 s on battery power; timeout raised to 300 s locally. Not yet re-verified by a successful full-repository LLM review |
| Handle failures and revoked access | 1 (mocked), 2 (live) | Mocked tests cover revoked token, expired/rejected refresh, rate limits, retries, network errors. Live revocation not exercised |
| Disconnect and invalidate access | **2** | Disconnect deletes DevPilot's encrypted tokens. It does **not** revoke the grant on GitHub (`DELETE /applications/{client_id}/grant`); the user must do that in GitHub settings (documented) |
| Pull-request review | 2 | Mocked tests only with the GitHub App flow; not run against a real PR |
| Deployment (compose, CI) | 2 | Files exist; never run |

**Mocked vs real:** Ollama real; GitHub real (manual, one account) plus mocks in tests;
Anthropic fake client only; Git, Ruff, Bandit real.

## 5. Release blockers and security concerns

| # | Item | Severity |
|---|---|---|
| B1 | No remote; CI has never run | Blocker |
| B2 | ~~Phase 3 and the context-size fix uncommitted~~ Resolved: `caba0f3`, `159ca99` | Done |
| B3 | Open registration lets anyone spend compute or LLM budget | Critical for public deployment |
| B4 | No HTTPS story; `DEVPILOT_COOKIE_SECURE` defaults to false and is not enforced in production | Critical |
| B5 | Missing CSP, HSTS, frame-ancestors, Referrer-Policy; `/docs` public | High |
| B6 | Rate limits in process memory (lost on restart, not shared) | High |
| B7 | `--forwarded-allow-ips=*` in the backend image | High if the API is ever reachable without nginx |
| B8 | Compose stack and nginx `login.html` change never run | High |
| B9 | No backups; snapshot and session cleanup not scheduled | Medium |
| B10 | Disconnect does not revoke the GitHub grant | Medium |
| B11 | Repository Q&A not implemented | Feature gap |
| B12 | Full-repository LLM review not yet seen to succeed after the fixes | Verify |

Secrets: none found in tracked files (pattern scan at each commit). `backend/.env` holds the GitHub
client secret and is ignored; it was not printed.

## 6. Must be preserved

- Tests: everything under `backend/tests/` and `frontend/src/**/*.test.*`, `frontend/tests/e2e/`.
- Datasets: `evaluation/datasets/v1/cases.py` (never edit to change scores), `evaluation/datasets/v2/cases.py` (held out: never tune against it).
- Reports: `evaluation/reports/**` (historical, including pre-fix runs marked contaminated), `phase3/` raw runs, all `details.json`.
- Migrations: both files in `backend/alembic/versions/` (add new ones, never edit).
- Load-bearing code listed in `docs/phase-1-baseline.md` section 8, plus `app/ai/tools.py`, `app/services/github_tokens.py`, `app/integrations/github.py`.
- Local only, never commit: `backend/.env`, `*.db`, `backend/data/`, `CONTEXT.md`.

## 7. Recommended next phase

**Phase 4: "Lock in and verify", in this order. Nothing new is built until steps 1 to 3 pass.**

1. ~~Commit the uncommitted Phase 3 work and the context-size fix~~ Done: `caba0f3`, `159ca99`.
2. Re-verify a full-repository LLM review on `Lucky261005/dgbf` while plugged in, and record the
   live GitHub verification (account, repositories, SHA, refusal) in `docs/github-app.md`.
3. Create the GitHub remote, push `main`, and get CI green (closes B1, proves B8's nginx part only
   if the compose job is added).
4. Then build the missing goal feature: **repository Q&A** grounded in the indexed commit, reusing
   `app/ai/tools.py` for retrieval, the provider abstraction, citation validation and per-user
   isolation, with a small evaluation set of questions with known answers.
5. Production hardening (B3 to B7, B9, B10) before any public deployment.
