# Implementation guide

How the code actually works, module by module. Paths are relative to the repository root.
Functions marked ⚠ are security-sensitive; read them before changing anything nearby.

## Backend layout

```
backend/app/
  main.py               app, middleware, exception handlers, /health, /settings
  core/                 config, db engine/session, security (hashing, crypto), logging
  models.py             SQLAlchemy models (all tables)
  schemas.py            Pydantic request/response models
  api/                  routers: auth, repositories, reviews, github; deps.py (auth/ownership)
  services/             ingestion, chunking, indexing, diff, findings, test_suggestions, review
  analyzers/            base interface + Ruff/Bandit adapters
  ai/                   schema, context/prompt, provider
  integrations/github.py
  workers/queue.py      DB-backed queue and worker
  cli.py                retention cleanup
```

---

## Configuration — `app/core/config.py`

- `Settings` (pydantic-settings) reads `DEVPILOT_*` env vars and `backend/.env`.
  `ANTHROPIC_API_KEY` is read under its standard name.
- `allowed_local_roots` is annotated `NoDecode` so a `;`-separated string is split by
  `_split_roots` instead of being parsed as JSON (a bug found by the test suite).
- `get_settings()` is cached and refuses to start when `env != development` and no secret key is set.

## Database — `app/core/db.py`, `app/models.py`

- `make_engine` turns on `PRAGMA foreign_keys=ON` for SQLite connections, otherwise cascades
  would silently not happen in development.
- `SessionLocal(expire_on_commit=False)` so objects stay readable after commit in the worker.
- Models use SQLAlchemy 2 typed `Mapped[...]` columns. See [database.md](database.md).

## Auth — `app/api/auth.py`, `app/api/deps.py`, `app/core/security.py`

- Register/login: `hash_password` / `verify_password` (argon2-cffi). Unknown emails are verified
  against `_DUMMY_HASH` so response time doesn't reveal account existence.
- `_start_session`: random 32-byte token (`secrets.token_urlsafe`) in an httpOnly cookie; only
  `hash_token(token)` (SHA-256) is stored. A fast hash is fine because the token has 256 bits of
  entropy; argon2 is for low-entropy passwords.
- ⚠ `current_user` (deps.py): cookie → session row → expiry check (deletes expired) → user.
- ⚠ `owned_repo` / `owned_review`: load the row, compare `owner_id` with the current user, raise
  404 on mismatch. Every resource route calls one of these.
- `encrypt_secret` / `decrypt_secret`: Fernet (AES-128-CBC + HMAC) with `DEVPILOT_SECRET_KEY`.

**Test/debug:** `tests/test_api.py::test_auth_flow_and_session_cookie`,
`test_other_users_cannot_see_or_touch_repository`.

## Middleware — `app/main.py::guard`

Order per request: assign/echo request ID (stored in a `ContextVar` for log lines) → reject
`Content-Length` above the limit (413) and multipart bodies with no `Content-Length` (411) → require `x-devpilot-csrf: 1` on unsafe methods (403) →
call the route → add `x-request-id` and `x-content-type-options`. Exception handlers turn
`HTTPException` into `{"detail", "request_id"}`, validation errors into a compact list, and
anything else into a generic 500 while logging the traceback.

## Ingestion — `app/services/ingestion.py`

| Function | Input → output | Notes |
|---|---|---|
| ⚠ `_safe_member_path(name)` | archive member name → `PurePosixPath` or `None` | Normalizes `\` to `/`; rejects absolute, drive-letter, `..`, `:` and NUL. |
| ⚠ `safe_extract_zip(zip, dest, settings, strip_top=False)` | ZIP → files on disk | Checks count and declared size first, validates every path and rejects symlinks **before writing anything**, then writes while counting real bytes (zip-bomb guard). Files above `max_file_bytes` are skipped. `strip_top` removes a single wrapping folder (GitHub zipballs, zipped folders). |
| ⚠ `validate_local_path(raw)` | user path → resolved `Path` | Must resolve under an allowed root and contain `.git`. |
| ⚠ `_git(repo, *args)` | runs git | Argument list, timeout, `core.hooksPath=/dev/null`, `core.fsmonitor=false`, empty `diff.external`. Errors become `IngestionError` with git's last stderr line. |
| ⚠ `resolve_ref(repo, ref)` | ref → commit SHA | Regex, no leading `-`, `rev-parse --verify --end-of-options ref^{commit}`. |
| `export_git_tree` | SHA → snapshot | `git archive --format=zip` then `safe_extract_zip` (no stripping). Exports tracked files only; never touches the working tree or `.git`. |
| `git_diff` | base, head → unified diff text | `--no-ext-diff --no-textconv -M`. |
| `discover_files(root)` | snapshot → `Discovery(files, skipped, total_bytes)` | Prunes `EXCLUDED_DIRS`, deletes symlinks and secret files, skips unknown extensions, oversized and binary files (NUL byte or invalid UTF-8 in the first 8 KiB). |

Why `git archive` instead of copying the directory: it exports exactly the committed tree,
ignores untracked files (which often hold local secrets), and runs no hooks.

## Chunking and search — `app/services/chunking.py`, `app/services/indexing.py`

- `chunk_file(path, text, language)`: for Python, top-level functions/classes (including
  decorators) become chunks and the gaps between them are windowed; other languages use 60-line
  windows with 10 lines of overlap (`_windows`). Each `Chunk` keeps `start_line`/`end_line` and
  the text equals exactly those lines (tested).
- `symbols` = names after `def/class/function/func/fn/interface/type/const/let/var`, stored as
  `" name1 name2 "` so an identifier search is `LIKE '% name %'`.
- `python_definitions`: `ast` walk returning `(qualified_name, start, end)`;
  used for review context.
- `search(db, repo_id, q, mode)`: SQL `LIKE` narrows candidate chunks (all terms must appear for
  text mode), then a regex finds the exact matching lines and converts them to absolute line
  numbers (`chunk.start_line + offset`), deduplicating lines that appear in overlapping chunks.
  Complexity is O(chunks in repo) per query; acceptable for MVP-sized repos (see shortcut comment).
- `index_snapshot` replaces all chunks of a repository in one transaction.

## Diffs — `app/services/diff.py`

- `parse_unified_diff(text)` splits on `diff --git`, reads `---`/`+++`/`rename`/`new file`/
  `deleted file` headers, then `parse_hunks`.
- `parse_hunks(patch, fp)` walks lines tracking the new-side line number: `@@ -a,b +c,d @@` resets
  it to `c`; `+` lines are recorded in `added_lines` and advance it; `-` lines don't; context
  lines advance it; `\ No newline` is ignored. The same function parses GitHub's per-file `patch`.
- `in_changed_lines(fp, start, end)` is how diff/PR reviews keep only findings on changed lines.

## Analyzers — `app/analyzers/`

- `base.py`: `NormalizedFinding` dataclass (the one internal finding format), the `Analyzer`
  protocol (`name`, `languages`, `version()`, `run(root, files)`), `run_tool` (runs
  `python -m <tool>` from the backend's own environment with a timeout) and `evidence_from`.
- `python_tools.py`:
  - `RuffAnalyzer` runs `ruff check --isolated --select F,B,E9,E722,PLE,ASYNC,RUF006
    --output-format=json --exit-zero` in batches of 200 files. `--isolated` ignores the repo's own
    config so results are comparable across repos. Severity: a small set of definite errors →
    high, `F`/`B`/`E722` → medium, else low.
  - `BanditAnalyzer` runs `bandit -f json -q -s B403,B404,B101,B603,B607`. Severity and confidence
    come from Bandit; CWE is appended to the description. Skips are explained in a comment and in
    [evaluation.md](evaluation.md).
  - Both keep the tool's rule ID, version, docs URL, and a fixed limitation sentence.
- `ast_rules.py`: `AstRulesAnalyzer` (`devpilot-ast`) holds DevPilot's own syntax-tree rules for
    defects no installed tool covers. **DP001 index-equals-length** flags reads of `X[len(X)]` or
    `X[len(X) + k]` (k >= 0) where X is the same plain name or attribute chain (compared with
    `ast.dump`). Assignments, calls, slices and other arithmetic are deliberately ignored to keep
    false positives near zero. Added from benchmark evidence; see
    `evaluation/reports/experiments/label-blind-static-v2/REPORT.md`.
  - Ruff also runs `SIM115` (file opened without a context manager), mapped to category `resource`.
    Its findings carry a caveat from `RUFF_LIMITATIONS` because it also fires on files closed later
    or kept open on purpose (9 of 10 hits on mature libraries were deliberate).
- Adding a language: implement the protocol, set `languages`, add it to `default_analyzers()`.
  The pipeline routes files by language automatically.

## LLM review — `app/ai/`, `app/services/findings.py`

Covered in depth in [ai-review-pipeline.md](ai-review-pipeline.md). Key entry points:
`build_context`, `SYSTEM_PROMPT`, `AnthropicProvider.review`, `validate_ai_findings`, `_realign`,
`deduplicate`. `StaticReplayProvider` exists for tests and is never chosen at runtime
(`get_provider` only returns `AnthropicProvider` or raises `ProviderUnavailable`).

## Test suggestions — `app/services/test_suggestions.py`

`suggest_for_changes(root, changed, test_files)`: for each changed, non-test Python file, find
public functions overlapping added lines (or all, for whole-repo reviews) whose name does not
appear anywhere in the test files' text. If the docstring has `>>> name(...)` examples with a
literal expected output, emit a complete test asserting them; otherwise emit a test gap with empty
`test_code` and a rationale naming the signature and each exception class raised in the body (no
placeholder code). Limit 10. AI test suggestions containing `TODO` or `...` placeholders are
dropped in `validate_test_suggestions`. The name-in-text check is a heuristic: a
function mentioned in a comment counts as tested.

## Review pipeline — `app/services/review.py::run_review`

Stages and their stored outputs:

1. **preparing**: build the snapshot (`full`: repo snapshot; `diff`: `_prepare_local_diff`;
   `pull_request`: `_prepare_pull_request`) and the list of `FilePatch`es; `discover_files`;
   persist `ChangedFile` rows.
2. **static_analysis**: run each analyzer on its language's target files; analyzer failures are
   recorded, not raised. For diffs, drop findings not touching added lines.
3. **ai_review**: gates (consent, provider) → `build_context` → `provider.review` →
   `validate_ai_findings` → `validate_test_suggestions`. Every outcome is written to `stats.ai`.
4. **saving**: `deduplicate`, insert `Finding`s, static and AI `TestSuggestion`s, write
   `stats` (timings, analyzer info, counts).

`run_review` raises on fatal problems; it does not commit. `process_job` owns the transaction.

## Worker — `app/workers/queue.py`

- `claim_next`: oldest queued job `FOR UPDATE SKIP LOCKED`, mark running, commit.
- `process_job`: calls `run_review` with a `set_stage` callback that commits the stage so the UI
  can show progress. On `IngestionError` the message is shown to the user; on any other exception
  the transaction is rolled back and the job gets a generic message naming the stage (details go
  to the log). Commits the final status.
- `recover_stale_jobs`: marks long-running jobs failed (run at worker start).
- `Worker` thread: started by the FastAPI lifespan when `DEVPILOT_RUN_WORKER_IN_PROCESS=true`;
  `python -m app.workers.queue` runs the same loop standalone (used by docker-compose).

**Debugging a stuck review:** `GET /api/reviews/{id}` shows `status` and `stage`. If `running`
forever, the worker thread died or the server restarted: restart the API (stale recovery) and
check logs for `review job <id> failed`.

## GitHub — `app/integrations/github.py`, `app/api/github.py`

`GitHubClient` wraps `httpx.Client` with base URL, auth header and API version, and maps status
codes to `GitHubError(message, status)` in `_check`. `download_zipball` follows at most 3
redirects and only to GitHub hosts over HTTPS, without forwarding the token. OAuth helpers build
the authorize URL and exchange the code. The client takes an optional `transport` so tests inject
`httpx.MockTransport`.

## Frontend — `frontend/src`

| File | Role |
|---|---|
| `lib/api.ts` | Typed fetch wrapper; adds CSRF header; converts errors to `ApiError(status, message, requestId)`. |
| `lib/types.ts` | TypeScript mirrors of the API schemas. |
| `App.tsx` | Query client (no retries on 4xx), router, `Authed` gate that redirects to `/login` on 401. |
| `components/Layout.tsx` | Header, navigation, theme toggle (stored in `localStorage`, falls back to OS preference). |
| `components/ui.tsx` | Buttons, badges (`SeverityBadge`, `SourceBadge` labels LLM output as "LLM hypothesis"), `ErrorBox`, `Empty`, `Spinner`. |
| `components/CodeView.tsx` | `CodeView` (numbered source, highlighted range scrolled into view) and `DiffView` (old/new line numbers). Ligatures disabled in CSS so code shows exact characters. |
| `pages/RepositoriesPage.tsx` | List and three import methods with server-driven availability. |
| `pages/RepositoryPage.tsx` | Review launcher, LLM consent toggle with data-flow text, history (polls while running), search, pull requests. |
| `pages/ReviewPage.tsx` | Status/polling, run summary (analyzer versions, LLM usage, rejected findings), filters, finding list + detail with source, feedback, changed files, test suggestions. |
| `pages/SettingsPage.tsx` | GitHub connection, provider and data-flow disclosure, limits and retention. |

## Evaluation — `evaluation/`

`datasets/v1/cases.py` (cases), `scripts/run_eval.py` (runs `process_job` per case per
configuration against a throwaway DB), `scripts/scoring.py` (matching and metrics). See
[evaluation.md](evaluation.md).
