# Audit report

Post-build audit of the DevPilot MVP, 2026-10-17. Everything below was checked by reading the code
and running commands; the commands and their output are in [verification-report.md](verification-report.md).

## 1. Technologies and versions (from the lockfiles, as installed)

| Backend (Python 3.12.2, `backend/uv.lock`) | Version | Frontend (Node 22.14, `frontend/package-lock.json`) | Version |
|---|---|---|---|
| fastapi | 0.143.3 | react / react-dom | 19.3.1 |
| uvicorn | 0.54.0 | react-router-dom | 7.18.4 |
| sqlalchemy | 2.1.5 | @tanstack/react-query | 5.104.3 |
| alembic | 1.20.0 | vite | 6.4.4 |
| pydantic / pydantic-settings | 2.14.1 / 2.16.0 | tailwindcss | 4.3.3 |
| argon2-cffi | 25.1.0 | typescript | 5.8.3 |
| cryptography | 50.0.2 | vitest | 5.0.5 |
| httpx | 0.28.1 | @playwright/test | 1.64.1 |
| python-multipart | 0.0.32 | eslint | 9.39.5 |
| ruff / bandit (also used as analyzers) | 0.17.1 / 1.9.4 | | |
| anthropic | 1.15.0 | | |
| psycopg | 3.3.6 | | |
| pytest / mypy | 9.1.1 / 2.4.0 | | |

Infrastructure files: `docker-compose.yml` (postgres:16, API, worker, nginx), `backend/Dockerfile`,
`frontend/Dockerfile`, `.github/workflows/ci.yml`.

## 2. Implemented features and entry points

| Feature | Backend entry point | Frontend entry point |
|---|---|---|
| Accounts and sessions | `app/api/auth.py` | `pages/LoginPage.tsx`, `components/Layout.tsx` (sign out) |
| Ownership checks | `app/api/deps.py::owned_repo`, `owned_review` | — |
| ZIP / local Git / GitHub import | `app/api/repositories.py::import_archive`, `import_local`, `import_github` | `pages/RepositoriesPage.tsx::ImportForm` |
| Indexing and search | `services/indexing.py::index_snapshot`, `search` | `pages/RepositoryPage.tsx::Search` |
| Reviews (full, diff, PR) | `api/reviews.py::create_review` → `workers/queue.py` → `services/review.py::run_review` | `RepositoryPage.tsx::StartReview`, `pages/ReviewPage.tsx` |
| Ruff / Bandit | `analyzers/python_tools.py` | Review page |
| LLM review | `ai/context.py`, `ai/provider.py`, `services/findings.py` | Consent toggle, run summary |
| Test suggestions | `services/test_suggestions.py` | Review page, "Test suggestions" tab |
| Feedback | `api/reviews.py::give_feedback`, `feedback_summary` | `ReviewPage.tsx::Feedback` |
| GitHub OAuth, PRs | `api/github.py`, `integrations/github.py` | `SettingsPage.tsx`, `RepositoryPage.tsx::Pulls` |
| Evaluation | `evaluation/scripts/run_eval.py` | — |
| Retention cleanup | `app/cli.py` | — |

## 3. Incomplete, mocked or missing

- **LLM review:** never called against the real API (no key). Tested with `StaticReplayProvider`
  and a mocked SDK client. The `ai` and `combined` benchmark configurations have not run.
- **GitHub:** OAuth exchange, repo import and PR review are tested only against
  `httpx.MockTransport`.
- **PostgreSQL, Docker images, compose stack, CI:** never run (Docker daemon not running; repo not
  on GitHub).
- **Unused by the UI:** `GET /api/repositories/{id}/files` and `/stats`, and the
  `test_suggestions.finding_id` column (never set). Kept: they are harmless API surface, and
  removing the column needs a migration.
- Missing, by design for the MVP: non-Python analyzers, real-world benchmark cases, posting
  comments to GitHub, password reset/MFA, OpenTelemetry export.

## 4. Architectural inconsistencies and unnecessary complexity

- Reviews are background jobs, but **import and indexing run inside the HTTP request**
  (`_index_or_fail`). A large repo or slow GitHub download blocks a server worker. Documented;
  not changed in this audit.
- **Dead code removed:** `CATEGORIES` in `analyzers/base.py` (never read),
  `enclosing_definition` in `services/chunking.py` (only its own test used it), the
  `api.files` client in `frontend/src/lib/api.ts` (never called).
- The rest of the structure (routers → services → analyzers/ai, one worker module) has no
  layers that exist only for show.

## 5. Security concerns

- **No secrets found in the repository.** `backend/.env` holds only a local path, and `.env`,
  `*.db`, `backend/data/` are git-ignored (checked with `git check-ignore` and `git add -n`).
- Concerns found and fixed are in section 9. Remaining risks: [security.md](security.md#known-gaps-and-remaining-risks).

## 6. Error handling and reliability weaknesses

- Fixed: an unexpected exception during indexing left the repository stuck in `indexing` (H/M, #3).
- Open: running jobs can't be pre-empted; timeouts are per subprocess/model call, and overlong
  jobs are only failed by stale-job recovery when a worker starts.
- Open: in-memory rate limiter keys are never pruned (memory grows by one small entry per user or
  IP); limits reset on restart and aren't shared across processes.
- Open: GitHub zipball downloads are read fully into memory before the size check
  (`integrations/github.py::download_zipball`).
- Open: SQLite with the in-process worker thread is untested under concurrent writes.

## 7. Testing gaps

PostgreSQL; real Anthropic and GitHub calls; Docker; login/register throttling; retention
cleanup; frontend page components (covered only by the e2e test); load. No coverage percentage
is measured. Details: [testing.md](testing.md#known-gaps).

## 8. Documentation inaccuracies found and corrected

- GitHub OAuth callback URL was documented as `http://localhost:8000/...`. The redirect URI is
  built from the request, so through the Vite proxy or nginx it is the **UI origin** + 
  `/api/github/oauth/callback` (e.g. `http://localhost:5173/...` in development,
  `http://localhost:8080/...` in compose). Fixed in README and `.env.example`.
- `implementation-guide.md` referenced the removed `enclosing_definition`. Fixed.
- Test counts updated everywhere (65 backend tests after this audit).

## 9. Defects, by priority

| # | Priority | Defect | Status |
|---|---|---|---|
| 1 | **High** | **Compose stores snapshots in the wrong place.** `env_file: .env` sets `DEVPILOT_DATA_DIR=./data` (from `.env.example`), which overrides the image's `/data`. The API and worker would write to their own `/app/data` (not the shared volume, and not writable by the non-root user), so every import in Docker would fail and the worker could never see snapshots. Confirmed with `docker compose config`. | Fixed: `docker-compose.yml` sets `DEVPILOT_DATA_DIR: /data` explicitly. Not run (no Docker). |
| 2 | Medium | **Unbounded chunked uploads.** The size cap in `main.py::guard` reads `Content-Length`; a chunked multipart upload has none, so the multipart parser spooled the whole body to disk before the handler's cap fired (reproduced with a 60 MB chunked upload). | Fixed: multipart requests without `Content-Length` get `411`. Test `test_chunked_upload_without_length_rejected`. |
| 3 | Medium | **Repository stuck in `indexing`.** `_index_or_fail` only caught expected errors; anything else (e.g. `OSError`) returned 500 and left the row `indexing` forever, with the partial snapshot on disk. | Fixed: unexpected errors mark it `failed` with a generic message, clean up, and re-raise. Test `test_unexpected_indexing_error_marks_repo_failed`. |
| 4 | Medium | **Login throttle shared by everyone behind nginx.** Throttling is per client IP; behind the proxy every request came from nginx's IP, so 10 failed logins per minute would lock out all users. | Fixed: nginx sends `X-Forwarded-For`; uvicorn runs with `--proxy-headers`. Not run (no Docker). The backend container is only reachable from the compose network, which is why trusting forwarded headers from any address is acceptable there. |
| 5 | Medium | **CI end-to-end job would fail.** `global-setup.ts` called `python`, which isn't guaranteed on Ubuntu runners. | Fixed: runs `uv run python` in `backend/`. E2E re-run locally: pass. |
| 6 | Medium | GitHub zipball read fully into memory before the size check. | Open (documented). Fix: stream with `httpx.stream` and stop at the limit. |
| 7 | Low | OAuth callback URL documented incorrectly. | Fixed (docs). |
| 8 | Low | Dead code (`CATEGORIES`, `enclosing_definition`, `api.files`). | Removed. |
| 9 | Low | Rate-limiter dictionary never pruned; per process. | Open (documented `shortcut:` comment in `core/ratelimit.py`). |
| 11 | Medium | **Compose OAuth redirect URI loses the port.** nginx forwarded `Host $host`, which has no port, so the callback would be `http://localhost/api/...` instead of `:8080`. | Fixed: `Host $http_host`. Not run. |
| 10 | Low | Text search with several words requires all of them per chunk but highlights lines matching only the first word. | Open. |

No critical defects were found.

## 10. Recommended next fixes

1. Run the stack once with Docker to confirm fixes 1 and 4 (`docker compose up --build`, import a ZIP, run a review).
2. Add a PostgreSQL service to the CI backend job and run the test suite against it.
3. Stream GitHub downloads (`backend/app/integrations/github.py::download_zipball`).
4. Move import/indexing into the job queue (`backend/app/api/repositories.py::_index_or_fail`).
5. Run the live LLM test and the `ai`/`combined` benchmark with a real key.
