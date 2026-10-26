# Verification report

## Latest local run: 2026-10-26

Windows 11 (10.0.26200), Python 3.12.2 (uv 0.13.1), Node 22.14.0, Playwright 1.64.1. Run on the
uncommitted working tree (HEAD `4028ca0` plus local changes). These are local results; GitHub
Actions has not run on these changes. Its latest run passed on `4028ca0` (2026-10-23).

| Step | Command | Outcome |
|---|---|---|
| Backend tests | `cd backend && uv run pytest -q` | **310 passed**, 4 deselected (`live_llm`, `live_github`), 0 failed |
| Lint / format | `uv run ruff check .`, `uv run ruff format --check .` | clean |
| Types | `uv run mypy app` | no issues |
| Security lint | `uv run bandit -q -r app -s B404,B603,B607` | no issues |
| Frontend tests | `cd frontend && npm test` | **41 passed** (12 files) |
| Frontend lint | `npx eslint .` | 0 errors, 5 pre-existing fast-refresh warnings |
| Frontend format / types | `npx prettier --check src tests`, `npm run typecheck` | clean |
| Build | `npm run build` | succeeds |
| E2E | `npx playwright test` | **2 passed**, after a test-only locator fix (`getByText('completed', { exact: true })`); the first attempt failed because the review stepper's screen-reader text also contains "completed" |

Not run on 2026-10-26: dependency audits (pip-audit, `npm audit`), the evaluation harness, and
Docker Compose.

## Earlier run: 2026-10-17

Run on 2026-10-17, Windows 11 (10.0.26200), Python 3.12.2 (uv 0.13.1), Node 22.14.0, Git 2.49.
Docker CLI 28.0.1 present but the **daemon was not running**; no PostgreSQL; no `ANTHROPIC_API_KEY`;
no GitHub OAuth app.

## 1. Environment and setup

| Step | Command | Outcome |
|---|---|---|
| Config | `backend/.env` from `.env.example` | Loads. Only `DEVPILOT_ALLOWED_LOCAL_ROOTS` set. `DEVPILOT_ENV=development` so no secret key required. |
| Backend deps | `uv sync --frozen` | exit 0 |
| Frontend deps | `npm ci` | **First attempt failed** (exit 127): the running Vite dev server locked files in `node_modules`, and `npm ci` had already deleted part of it. Stopped the dev server, re-ran: exit 0. |
| Database | `uv run alembic upgrade head` | Applied `3c3abb209ebc initial schema` (SQLite). |
| Services | uvicorn :8000, Vite :5173 | `GET /api/health` → `{"status":"ok"}`; UI returns 200. |
| Compose | `docker compose config` (with a temporary `.env`) | Valid. Revealed defect #1 (see audit). Stack **not run**. |

## 2. Static checks and automated tests (final run, after all fixes)

| Check | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 44 files already formatted |
| Types | `uv run mypy app` | no issues in 36 source files |
| Security lint | `uv run bandit -q -r app -s B404,B603,B607` | no issues |
| Backend tests | `uv run pytest -q` | **65 passed**, 1 deselected (`live_llm`) |
| Frontend lint | `npx eslint .` | 0 errors, 5 warnings (`react-refresh/only-export-components`, dev-only) |
| Frontend format | `npx prettier --check src tests` | clean |
| Frontend types | `npm run typecheck` | clean |
| Frontend tests | `npm test` | **7 passed** |
| Build | `npm run build` | succeeds |
| E2E | `npx playwright test` | **2 passed** |
| Dependencies | `uvx pip-audit --strict`, `npm audit --omit=dev` | no known vulnerabilities |

During the audit, `ruff format --check` and `prettier --check` failed once each, both on files
edited in this audit; they were formatted and re-checked. No test was skipped, weakened or
deleted except `test_enclosing_definition_returns_innermost`, which was removed together with the
dead function it tested.

## 3. Workflow against the live servers (curl, real implementation)

| # | Scenario | Expected | Observed |
|---|---|---|---|
| 1 | Other user `GET /api/repositories/1` | 404 | 404 |
| 2 | Other user `GET /api/reviews/1/findings` | 404 | 404 |
| 3 | No session `GET /api/repositories` | 401 | 401 |
| 4 | `use_ai` request | 400 without consent | 202 — **correct**: the audit log showed consent had been enabled for this repository from the UI earlier (events `repository.ai_consent allowed=True`). The 400 path is covered by `test_ai_review_requires_consent`. |
| 5 | Diff review with LLM, no key | completed, LLM skipped | `completed`, `stats.ai = {status: skipped, reason: "No LLM provider is configured..."}`, no findings (the change only contains logic bugs) |
| 6 | Diff review with ref `nope-ref` | job fails with clear message | `failed`, `git: fatal: Needed a single revision` |
| 7 | `GET .../file?path=../../../.env` | 404 | 404 |
| 8 | Local import of `C:/Windows` | 400 | "Path is outside the directories this server is allowed to read." |
| 9 | `POST /api/auth/logout` without CSRF header | 403 | 403 |
| 10 | Feedback on own finding; history | 204; history listed | 204; 7 reviews in history |
| 11 | Other user feedback on my finding | 404 | 404 |
| 12 | 60 MB chunked multipart upload (no Content-Length) | rejected early | Before fix: 413 only **after** the body was spooled to disk. After fix: 411 (test). |

Steps 1–10 of the requested workflow were also exercised end to end in the browser earlier
(import → index → whole-repo and `HEAD~1..HEAD` reviews → findings → highlighted source →
feedback → history) and by the Playwright test.

Not exercisable here: a real GitHub PR (mocked transport only), a real LLM review (replayed
responses only), malformed model output against the real provider (covered by
`test_ai_failure_keeps_static_results` and `test_provider.py` with mocks).

## 4. Benchmark

`uv run python ../evaluation/scripts/run_eval.py` (run 2026-10-17T09:01:04Z):

| Config | Result |
|---|---|
| static | precision 1.0, recall 0.538 (7/13), 0 FP on 4 clean cases, severity match 0.714, p50 1092 ms |
| ai | not run: `ANTHROPIC_API_KEY` is not set |
| combined | not run: `ANTHROPIC_API_KEY` is not set |

Identical to the previous run, so the static configuration is reproducible.

## 5. What was changed as a result

See [audit-report.md §9](audit-report.md#9-defects-by-priority) and
[development-log.md](development-log.md#9-post-build-audit).
