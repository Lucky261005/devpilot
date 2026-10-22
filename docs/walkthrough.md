# Code walkthrough

A guided tour of how DevPilot actually works, in the order data flows through it. Each section
lists the real files and functions, the call sequence, the key idea, and the alternatives.
Open the files next to this page; the explanations assume you are reading the code.

---

## 1. How the frontend starts and talks to the backend

**Files:** `frontend/src/main.tsx`, `App.tsx`, `lib/api.ts`, `vite.config.ts`.

```
main.tsx: createRoot(...).render(<App/>)
App.tsx:  QueryClientProvider → BrowserRouter → Routes
            /login → LoginPage
            /*     → Authed: useQuery(['me'], api.me)
                       401 → <Navigate to="/login">
                       ok  → <Layout> + page routes
```

- Every request goes through `request()` in `lib/api.ts`: `fetch(path, {credentials:
  'same-origin'})` plus the header `x-devpilot-csrf: 1`. A non-2xx response becomes
  `ApiError(status, detail, request_id)`.
- In development Vite proxies `/api` to `127.0.0.1:8000` (`vite.config.ts`). The browser only
  ever sees one origin, so cookies just work and no CORS setup is needed.
- **TanStack Query** caches server data by key (e.g. `['review', id]`). `refetchInterval` makes
  the review page poll every 1.5 s while the job is `queued`/`running`, and stop afterwards.
- *Alternative:* WebSockets/SSE to push job progress. Polling is simpler and fine at this scale.

## 2. Authentication and authorization

**Files:** `backend/app/api/auth.py`, `api/deps.py`, `core/security.py`, `models.py` (`User`, `UserSession`).

```
POST /api/auth/login
  auth.login → _throttle (10/min/IP)
             → verify_password(user.hash or _DUMMY_HASH, pw)   # argon2
             → _start_session: token = token_urlsafe(32)
                               DB stores sha256(token), expires in 7 days
                               Set-Cookie devpilot_session=token; HttpOnly; SameSite=Lax

Any protected route
  Depends(current_user): cookie → sha256 → sessions row → not expired → User
  owned_repo(id, db, user): repo.owner_id == user.id else 404
```

- *Authentication* = who you are (the session). *Authorization* = what you may touch (the owner check).
- Why store only a hash of the token: if the database leaks, the attacker can't use the hashes as cookies.
- Why 404, not 403, for someone else's repo: 403 would confirm the ID exists.
- *Alternative:* JWTs. They avoid a DB lookup per request but can't be revoked before expiry; a
  DB session makes logout immediate.

## 3. How a repository enters the system

**Files:** `api/repositories.py`, `services/ingestion.py`, `services/indexing.py`.

```
POST /api/repositories/archive
  import_archive: stream upload to a temp file (stop at max_upload_bytes → 413)
  _new_repo: insert row, status "indexing", audit event
  _index_or_fail(fill = safe_extract_zip(..., strip_top=True))
      new_snapshot_dir → data/snapshots/<repo>/current
      safe_extract_zip:   1) count + declared size limits
                          2) every name through _safe_member_path, reject symlinks
                          3) then write, counting real bytes (zip bomb guard)
      index_snapshot → discover_files → chunk_file → code_chunks rows → status "ready"
      on IngestionError: status "failed" + message; on anything else: generic message, re-raise
```

Local Git import calls `validate_local_path` (must be under `DEVPILOT_ALLOWED_LOCAL_ROOTS`) and
`export_git_tree` (`git archive` with hooks disabled). GitHub import validates `owner/name`,
checks access with `GitHubClient.repo`, and downloads a zipball.

- **Key idea:** treat everything in a repository as hostile. Check all paths *before* writing
  anything; never run code from it.
- *Alternative:* `git clone`. Rejected: cloning runs more of Git's machinery and needs URL
  validation; `git archive` of a local commit exports tracked files only.

## 4. How files are parsed and indexed

**Files:** `services/ingestion.py::discover_files`, `services/chunking.py`, `services/indexing.py`.

- `discover_files` walks the snapshot, skips `EXCLUDED_DIRS` (`node_modules`, `.git`, …),
  **deletes** secret files (`.env`, keys) and symlinks, and skips unknown extensions, files over
  `max_file_bytes`, and binary files (a NUL byte or invalid UTF-8 in the first 8 KiB).
- `chunk_file`: for Python, `ast.parse` gives each top-level function/class with exact
  `lineno`/`end_lineno` (decorators included); gaps between them and all non-Python files are cut
  into 60-line windows overlapping by 10 lines (`_windows`).
- Each chunk stores `path`, `start_line`, `end_line`, `content` and `symbols` (defined names,
  space-padded so `LIKE '% name %'` is a whole-word match).
- **Search** (`indexing.search`): SQL `LIKE` finds candidate chunks, then a regex finds matching
  lines; absolute line = `chunk.start_line + offset`. A `seen` set removes lines that appear in two
  overlapping chunks.
- *Why overlap:* a match near a window edge still appears with context.
- *Alternatives:* Tree-sitter (structure for every language), FTS/trigram indexes, embeddings.
  Costs and triggers for switching: [ADR 0005](decisions/0005-parsing-and-search.md).

## 5. How a pull-request diff is analyzed

**Files:** `services/review.py::_prepare_local_diff`, `_prepare_pull_request`, `services/diff.py`.

- Local: `resolve_ref` turns `HEAD~1`/`HEAD` into SHAs (regex + `--end-of-options` stops option
  injection), `export_git_tree(head)` builds a snapshot of the new version, and `git_diff` gives
  the unified diff.
- GitHub: `pull_files` gives each file's `patch` (hunks only), and the head commit is downloaded
  as a zipball.
- `parse_hunks` is the core algorithm. Worked example:

```
@@ -3,3 +3,4 @@      → new-side counter = 3
 a                   context: line 3, counter → 4
-b                   removed: counter stays 4 (it's not in the new file)
+c                   added:   record 4, counter → 5
+d                   added:   record 5, counter → 6
 e                   context: line 6
added_lines = {4, 5}, hunks = [(3, 6)]
```

- `in_changed_lines(fp, start, end)` keeps a finding only if its range contains an added line.
  O(added lines) per finding.

## 6. How static-analysis findings are produced

**Files:** `analyzers/base.py`, `analyzers/python_tools.py`.

```
run_review → for analyzer in default_analyzers():           # [RuffAnalyzer, BanditAnalyzer]
               files = targets in analyzer.languages
               analyzer.run(root, files)
                  run_tool(["ruff", "check", "--isolated", "--output-format=json", ...])
                  json.loads(stdout) → NormalizedFinding(source="static", rule_id, severity, ...)
             (exception → stats.analyzers[name].status = "failed"; others continue)
```

- Both tools run as **subprocesses** of the backend's Python with a timeout, in batches of 200
  files, and only *parse* the code.
- `NormalizedFinding` is the one shape every source produces: path, line range, severity,
  category, evidence, rule ID, version, docs link, limitations.
- Ruff runs `--isolated` so a repository's own config can't change the rules.
- Some Bandit rules are skipped (`BANDIT_SKIP`) because they flag every subprocess call rather
  than defects; this came from the evaluation run.
- *Adding a language:* write a class with `name`, `languages`, `version()`, `run()` and add it to
  `default_analyzers()`.

## 7. How AI context is assembled and model output is validated

**Files:** `ai/context.py`, `ai/schema.py`, `ai/provider.py`, `services/findings.py`. Full detail:
[ai-review-pipeline.md](ai-review-pipeline.md).

```
gates: repository.ai_review_allowed? provider configured? (else stats.ai = skipped)
build_context:
   order files (non-tests first, most added lines first)
   regions_for_patch: enclosing function (ast) + hunk ±15 lines, merged
   render "+    6 | code" lines, stop at the char budget, list omitted files
   wrap in <repository_content>, neutralize any tag inside it
provider.review(SYSTEM_PROMPT, prompt) → messages.parse(output_format=AIReview)
validate_ai_findings, per finding:
   path in shown? → lines exist, ≤80 lines? → overlap what was shown? → evidence in those lines (±2)?
   → _realign to the lines that actually contain the evidence
deduplicate: analyzer findings win; among AI, most severe wins
```

- **Key idea:** the model's claims are hypotheses. The checks make sure every shown finding points
  at code that really exists where it says.
- What validation **can't** catch: a correct quote with a wrong conclusion, or an injection that
  makes the model stay silent.

## 8. How findings are stored and displayed

**Files:** `services/review.py` (saving stage), `models.py::Finding`, `api/reviews.py`, `frontend/src/pages/ReviewPage.tsx`, `components/CodeView.tsx`.

- Findings, test suggestions and changed files are inserted in the job's transaction; `stats`
  (timings, versions, LLM usage, rejected findings) goes into the job row. `process_job` commits.
- `GET /api/reviews/{id}/findings` sorts by severity, then path and line, and adds the current
  user's feedback.
- The page filters on the client (`filterFindings`: OR within a dimension, AND across them).
  Selecting a finding loads the file from the **review's** snapshot and `CodeView` highlights and
  scrolls to the cited lines.
- Feedback is an upsert keyed by (finding, user), storing the analyzer and version.

## 9. Errors, retries and timeouts

| Layer | Mechanism | Code |
|---|---|---|
| HTTP | `HTTPException` → `{detail, request_id}`; unknown errors → generic 500, traceback in logs | `main.py` handlers |
| Input | Pydantic validation → 422; size → 413/411; CSRF → 403 | `schemas.py`, `main.py::guard` |
| Import | `IngestionError` → repo `failed` with message; other errors → `failed` + generic message | `_index_or_fail` |
| Subprocesses | git 60–120 s, analyzer batch 120 s timeouts | `ingestion._git`, `analyzers/base.run_tool` |
| LLM | SDK retries 429/5xx/connection twice; DevPilot retries once on invalid output; 120 s timeout; failure → `stats.ai.failed`, job still completes | `ai/provider.py` |
| GitHub | Status codes mapped to 401/404/429/502 with clear messages | `integrations/github.py::_check` |
| Jobs | `IngestionError` → message shown; other exception → rollback, "Internal error during '<stage>'"; stale `running` jobs failed at worker start | `workers/queue.py` |

*Trade-off:* Python threads can't be killed, so a job can't be stopped mid-way; the job timeout
is applied by stale-job recovery instead of pre-emption.

## 10. How the evaluation suite works

**Files:** `evaluation/datasets/v1/cases.py`, `evaluation/scripts/run_eval.py`, `scoring.py`.

```
run_eval.main:
  set env → throwaway SQLite DB and temp dirs (before importing the app)
  for each case: materialize → git repo with commit "before" and commit "after"
  for config in static, ai, combined:
     ai/combined without a key → {"status": "not_run", reason}
     for each case: create Repository + ReviewJob(kind="diff") → process_job (the real pipeline)
                    collect findings → score(preds, expected)
  write reports/<timestamp>.json, latest.json, latest.md
```

- `score`: a prediction matches a reference when the path is equal and the line ranges overlap
  with ±2 lines of tolerance; the first match is a TP, further matches are duplicates, unmatched
  predictions are FPs, unmatched references are FNs.
- *Limits:* synthetic cases written by one person; matching on location, not on the explanation;
  one run per case (LLM output varies). See [evaluation.md](evaluation.md).

---

Interview questions with answers are in [interview-guide.md §4](interview-guide.md#4-twenty-likely-questions-with-answers-grounded-in-the-code).
