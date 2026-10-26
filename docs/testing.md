# Testing

## Results (actual run)

Local run on 2026-10-26, on the uncommitted working tree: Windows 11 (10.0.26200), Python 3.12.2
via uv 0.13.1, Node 22.14.0, Chromium from Playwright 1.64.1.

| Suite | Command | Result |
|---|---|---|
| Backend unit + integration + security | `cd backend && uv run pytest -q` | 310 passed, 4 deselected (opt-in `live_llm` and `live_github`), 0 failed |
| Backend lint / format / types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` | clean |
| Backend security lint | `uv run bandit -q -r app -s B404,B603,B607` | no issues |
| Frontend unit | `cd frontend && npm test` | 41 passed (12 files) |
| Frontend lint / format / types | `npx eslint . && npx prettier --check src tests && npm run typecheck` | 0 errors, 5 warnings (fast-refresh, pre-existing), formatted, typecheck clean |
| Frontend build | `npm run build` | succeeds |
| End-to-end | `cd frontend && npx playwright test` | 2 passed |
| Dependency audit | `uvx pip-audit`, `npm audit` | not run locally on 2026-10-26; passed in CI for commit `4028ca0` |

Earlier local run, 2026-10-17: backend 77 passed, frontend 7, end-to-end 2.

**CI.** The workflow (`.github/workflows/ci.yml`) runs all of the above on Ubuntu, plus the
static-only evaluation. Its latest run passed on commit `4028ca0` (2026-10-23). The changes made
since then are uncommitted and have not been through CI; the results above are local only.

## Backend tests (`backend/tests`)

`conftest.py` points the app at a temporary SQLite DB and data directory, **runs the Alembic
migration** (so migrations are tested), allows a temporary local-import root, sets fake GitHub
OAuth credentials, and clears `ANTHROPIC_API_KEY`. Helpers create test users, sample ZIPs from
`fixtures/sample_repositories/inventory_service`, and a two-commit local Git repo.

| File | Level | What it verifies |
|---|---|---|
| `test_ingestion.py` | unit / security | ZIP traversal, absolute paths, NTFS streams, symlinks, size and count limits, non-ZIP input, top-folder stripping, secret-file deletion, binary skipping, allowed local roots, ref validation (option injection), `git archive` export and diff, snapshot path escape. |
| `test_units.py` | unit | Python chunking keeps exact line ranges; window chunking overlaps; unified-diff parsing (add/modify/delete/rename, added-line numbers, `\ No newline`); context neutralizes prompt-injection tags and marks changed lines; budget omission is reported; model-output validation (accept grounded, reject wrong path, out-of-range, unseen lines, invented evidence); zero findings is valid; dedupe rules; static test suggestions are test gaps without placeholder code; log redaction. |
| `test_provider.py` | unit (SDK mocked) | Request shape (model, effort, schema), usage recording, one retry on schema violation, give-up after two, no retry on auth errors (and no key in message), refusal and truncation handling, rate-limit mapping, missing key → `ProviderUnavailable`. Optional live test (marker `live_llm`). |
| `test_api.py` | integration (HTTP + DB + real Ruff/Bandit) | Auth flow and cookie flags; validation; CSRF; oversized requests; import → index → search → file view; failed imports recorded; cross-user isolation on every repo route; full review lifecycle with real analyzers; AI review with a replayed model response (validation, dedupe vs Bandit, prompt contents, feedback upsert and summary, AI test suggestions); AI failure keeps static results; AI unconfigured → skipped; local diff review restricted to changed lines; invalid refs fail the job safely; rate limit; cascade delete; worker hides internal error text and recovers stale jobs; GitHub import, PR listing, PR review via mocked transport; GitHub input validation; OAuth state validation; chunked uploads without Content-Length rejected (411); unexpected indexing errors leave the repo `failed`, not stuck. |
| `test_ollama_provider.py` | unit + integration (HTTP mocked) | Provider selection and the "local" flag; exact `/api/chat` request (model, messages, schema `format`, `stream: false`, options); parsing and token counts; missing counts; one retry on invalid or truncated output; no retry on connection refused, timeout, 404 missing model, 500; oversized prompt refused without a call; a full review with Ollama down still completes with Ruff/Bandit findings. Optional live test. |
| `test_eval_scoring.py` | unit | Benchmark matching (TP/FP/FN/duplicates, tolerance) and percentiles. |

### Mocked vs real

| Dependency | In tests |
|---|---|
| SQLite + Alembic | Real |
| Git, Ruff, Bandit | Real subprocesses |
| Anthropic API | Never called. `StaticReplayProvider` replays a fixed JSON review through the real validation path; `test_provider.py` replaces the SDK client object. |
| GitHub API | `httpx.MockTransport` returning recorded-shape JSON and a real ZIP built from the fixture. |
| PostgreSQL | Not tested. |

### Optional live LLM test

```bash
cd backend
DEVPILOT_LIVE_ANTHROPIC_KEY=sk-ant-... uv run pytest -m live_llm
```

Not run so far (no key available).

Ollama (free; needs Ollama running with the model pulled):

```bash
DEVPILOT_LIVE_OLLAMA=1 uv run pytest -m live_llm -k ollama
```

Not run so far (Ollama not installed).

## Frontend tests

- `src/lib/filters.test.ts`: finding filters AND across dimensions and OR within one.
- `src/components/ui.test.tsx`: LLM findings labeled as hypotheses; API error shows request ID;
  byte formatting; `CodeView` highlights exactly the cited lines; `DiffView` numbers old/new lines
  correctly.

## End-to-end tests (`frontend/tests/e2e`)

`playwright.config.ts` starts a fresh backend on port 8001 (new SQLite DB, migrations applied,
no LLM key) and Vite on 5174. `global-setup.ts` zips the sample fixture.

`review-flow.spec.ts`:
1. Register → empty state shown.
2. Upload the sample ZIP → repository page shows indexed files.
3. Definition search for `apply_discount` → `inventory/pricing.py:4`.
4. Start a whole-repository review → status reaches `completed`.
5. Open the Bandit B602 finding → `inventory/store.py:27` with exactly one highlighted source line
   containing `shell=True`.
6. Filter by `high` → one finding. Mark it Useful → persisted across reload.
7. Back to the repository → review appears in history.

Plus: unauthenticated navigation redirects to `/login`.

## Bugs the tests caught during development

- `safe_extract_zip` stripped a "single top-level folder" from `git archive` output, deleting the
  `pkg/` directory level. Made stripping opt-in (`strip_top`) for uploads and GitHub zipballs only.
- Model findings off by one line escaped deduplication against the matching Bandit finding.
  Added `_realign` to snap ranges to the quoted evidence.
- Queue state leaking between tests (jobs from one test processed in another). Added a fixture
  that clears pending jobs.

## Known gaps

- No PostgreSQL run; `SKIP LOCKED` concurrency with multiple workers is untested.
- No test sends a real request to Anthropic or GitHub.
- Docker images and compose stack not built or run.
- Rate limiting on login/register is not directly tested (only the review limiter is).
- Frontend component coverage is thin: pages are covered only by the end-to-end test.
- No load or performance testing.
- Coverage percentage is not measured.
