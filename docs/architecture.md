# Architecture

DevPilot is a modular monolith: one FastAPI application, one database, and a review worker that
runs either as a thread inside the API process or as its own process. There is no message broker.

## Components

| Component | Code | Responsibility |
|---|---|---|
| Web UI | `frontend/src` | React SPA. Talks only to `/api`. Polls job status. |
| API | `backend/app/main.py`, `backend/app/api/*` | HTTP, validation, authN/authZ, rate limits, error mapping. |
| Auth | `app/api/auth.py`, `app/api/deps.py`, `app/core/security.py` | Accounts, argon2 hashes, session tokens, ownership checks. |
| Ingestion | `app/services/ingestion.py` | ZIP extraction, `git archive` export, file discovery and filtering. |
| Indexing / search | `app/services/chunking.py`, `app/services/indexing.py` | Chunks with path + line range; lexical search. |
| Diff processing | `app/services/diff.py` | Unified diff → changed files, hunks, added line numbers. |
| Analyzers | `app/analyzers/*` | Ruff and Bandit adapters producing `NormalizedFinding`. |
| LLM review | `app/ai/*`, `app/services/findings.py` | Context, prompt, provider call, validation, dedupe. |
| GitHub | `app/integrations/github.py`, `app/api/github.py` | OAuth, repo/PR metadata, zipball download. |
| Worker | `app/workers/queue.py`, `app/services/review.py` | Claim jobs and run the review pipeline. |
| Evaluation | `evaluation/` | Benchmark cases, runner, reports. |

## How the frontend talks to the backend

- Every call goes through `frontend/src/lib/api.ts` → `fetch('/api/...')` with
  `credentials: 'same-origin'` and the header `x-devpilot-csrf: 1`.
- In development, Vite proxies `/api` to `127.0.0.1:8000`; in Docker, nginx does. The browser
  therefore sees one origin, so the session cookie can be `SameSite=Lax` and no CORS is needed.
- Errors come back as `{"detail": "...", "request_id": "..."}`. `ApiError` carries both, and
  `ErrorBox` displays the request ID so a user can quote it.
- TanStack Query caches reads. Review pages poll every 1.5 s while a job is `queued`/`running`.

## Request lifecycles

### Import a ZIP archive

```
POST /api/repositories/archive (multipart: name, file)
  guard middleware: request id, Content-Length cap, CSRF header
  current_user (session cookie → sessions.token_hash)
  rate limit: 20 imports / hour / user
  stream upload to temp file, abort past DEVPILOT_MAX_UPLOAD_BYTES       → 413
  insert repositories row (index_status=indexing), audit event
  safe_extract_zip(strip_top=True) into data/snapshots/<repo>/current
  discover_files: delete secret files, skip binary/large/unsupported
  chunk + insert code_chunks, update counts, index_status=ready
  on IngestionError: index_status=failed, index_error=<safe message>    → 201 with failed status
```

The repository row is kept on failure so the user sees why the import was rejected.

### Run a review

```
POST /api/repositories/{id}/reviews {kind, base_ref?, head_ref?, pr_number?, use_ai}
  ownership check (404 if not owner), repo must be indexed
  use_ai requires repository.ai_review_allowed                            → 400
  rate limit: DEVPILOT_REVIEWS_PER_HOUR per user                          → 429
  insert review_jobs (status=queued)                                      → 202

Worker loop (every 1 s when idle):
  claim_next: SELECT ... WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED
  status=running, stage=preparing
  run_review():
    full         → use the repository snapshot
    diff         → resolve refs, git archive head into review-<id>/, git diff base head
    pull_request → GitHub PR files (+patches) and zipball of head SHA into review-<id>/
    discover files; store changed_files
    stage=static_analysis → Ruff, Bandit on target Python files
       diff/PR: keep only findings touching added lines
    stage=ai_review (if requested) → see ai-review-pipeline.md
    stage=saving → dedupe, insert findings + test_suggestions, write stats
  status=completed | failed (error message is user-safe)

UI polls GET /api/reviews/{id} until completed, then loads findings, changed files, tests.
```

### View a finding

`GET /api/reviews/{id}/findings` (sorted by severity) → user selects one →
`GET /api/reviews/{id}/file?path=...` reads the file from that review's snapshot (path is
resolved and must stay inside the snapshot) → `CodeView` highlights `start_line..end_line`.

### GitHub connect

`GET /api/github/oauth/start` sets a 10-minute httpOnly cookie `"<user id>:<random state>"` and
redirects to GitHub. The callback compares the cookie with `"<current user id>:<state>"` using
`hmac.compare_digest`, exchanges the code, fetches `/user`, and stores the token Fernet-encrypted.

## Database

See [database.md](database.md). Key points: every user-owned row hangs off `repositories.owner_id`,
deletes cascade, `review_jobs` doubles as the job queue, and JSON columns are used only for
`stats`, `skipped` and audit `detail`, which are read as a whole and never filtered on.

## Background jobs

- **Why**: a review runs git, two analyzers and possibly a 30–120 s model call. Doing that inside
  an HTTP request would tie up a server worker and fail on proxy timeouts. See
  [ADR 0004](decisions/0004-background-jobs.md).
- **Queue**: the `review_jobs` table. On PostgreSQL, `FOR UPDATE SKIP LOCKED` lets several workers
  claim jobs without double-processing. SQLite ignores that clause, so with SQLite run one worker
  (the default in-process thread).
- **Recovery**: on worker start, jobs that have been `running` longer than `DEVPILOT_JOB_TIMEOUT_S`
  (default 600 s) are marked failed with an explanatory message.
- **Timeouts**: subprocesses have hard timeouts (git 60–120 s, each analyzer batch 120 s); the
  model client has `DEVPILOT_LLM_TIMEOUT_S` (120 s). A running Python thread cannot be killed, so
  the job-level timeout is enforced by stale-job recovery rather than preemption.

## Authentication and authorization boundaries

- Authentication: session cookie → `sessions` row (SHA-256 of the token) → user. 7-day expiry.
- Authorization: every repository/review/finding route goes through `owned_repo` or
  `owned_review`, which return **404** for other users' resources so IDs are not confirmed.
- The worker trusts the job row; jobs can only be created through the authorized endpoint.

## Error handling, retries, recovery

| Failure | Behavior |
|---|---|
| Rejected input (bad ZIP, path outside roots, bad ref) | `IngestionError` → 400 or a failed job with the message. |
| Analyzer crash or timeout | Recorded in `stats.analyzers.<name>.status=failed`; other analyzers continue. |
| LLM unavailable / not configured | `stats.ai.status=skipped`; analyzer findings still saved. |
| LLM returns invalid schema | One retry, then `stats.ai.status=failed` with the reason. |
| LLM 429/5xx/connection | SDK retries twice with backoff; then `failed`. |
| Unexpected exception in a job | Rolled back; job `failed` with stage name only; traceback in server log. |
| Unexpected exception in a request | 500 `{"detail": "Internal server error.", "request_id"}`; traceback logged. |
| Worker died mid-job | Stale-job recovery marks it failed on next start. |

## Trade-offs and alternatives

| Decision | Alternative | Why this one | When to change |
|---|---|---|---|
| DB table as queue | Redis + RQ/Celery | One fewer service; transactional with job data. | Many workers, high job rates, scheduling needs. |
| Import/index in the request | Background indexing job | Simpler; MVP repos are small. | Large repos or slow GitHub downloads. |
| Lexical search | Embeddings / pg_trgm / FTS | No extra infra; exact identifiers matter most in code. | Measured need for fuzzy or semantic recall. |
| Python `ast` for structure | Tree-sitter | No native build; Python is the only analyzed language. | Adding analyzers for other languages. |
| In-memory rate limiter | Redis/DB counters | Zero dependencies. | More than one API process. |
| One LLM call per review | Per-file calls / agent loop | Predictable cost and latency; easy to validate. | Repos where one context window is too small. |
