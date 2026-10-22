# Interview guide and handover package

Everything here describes the code as it exists. Where something is untested, it says so. Before
an interview, work through section 10 and make sure you can answer from the code, not from this
page.

**Honesty note for interviews:** this project was built with an AI coding assistant (Claude Code).
Say so if asked. What you can credibly claim is the understanding you have built by reviewing,
running and modifying it. Section 10 is there to make that understanding real.

---

## 1. Five-minute explanation

> DevPilot reviews code changes and reports likely defects with exact file and line citations.
> The idea is to run cheap, reliable checks first, and only then use an LLM, under supervision.
>
> You import a repository as a ZIP, a local Git path, or from GitHub. The backend extracts it
> safely, removes secret files, and indexes it into chunks that remember their line ranges, so
> search results and findings always point at real lines.
>
> A review is a background job. The worker builds a snapshot of the code being reviewed, parses
> the diff to know which lines changed, and runs Ruff and Bandit. For a change review, it keeps
> only findings on changed lines. If the user enabled it for that repository, it then builds a
> bounded, line-numbered context of the changed functions and asks Claude for structured findings.
> Every model finding is checked: the file has to be one we sent, the lines have to exist and be
> ones the model saw, and the quoted evidence has to actually be in those lines. Anything else is
> dropped and counted. Then findings are deduplicated, with analyzer results winning, and saved.
>
> The UI shows status while the job runs, then findings with severity, source, evidence, the
> highlighted source, fixes, test suggestions, and buttons to say whether the finding was right.
>
> I also built an evaluation harness: 17 small synthetic cases with labeled defects, run through
> the real pipeline in three configurations. The analyzer-only baseline found 7 of 13 seeded
> defects with no false positives. The LLM configurations haven't been measured yet because I
> didn't have an API key, and I report them as not run rather than guessing.

## 2. Fifteen-minute architecture walkthrough

1. **Shape (1 min).** Modular monolith: FastAPI app, one SQL database, a worker that's a thread
   in the API or its own process, React SPA. Draw the diagram from the README.
2. **Data model (2 min).** users → repositories → reviews → findings → feedback; cascades on
   delete. `review_jobs` is also the queue. `stats` JSON holds per-run telemetry.
3. **Ingestion (3 min).** Why the repository is hostile input. ZIP checks in
   `safe_extract_zip` (paths, symlinks, real decompressed size). Local import restricted to
   admin roots and done with `git archive` with hooks disabled. Secret files deleted. Nothing is
   executed.
4. **Review job (3 min).** Claim with `SKIP LOCKED`; stages; diff parsing to added lines;
   analyzers via subprocess with JSON output normalized into `NormalizedFinding`; changed-line filter.
5. **LLM stage (4 min).** Consent gate; context selection (enclosing function + padding, char
   budget, omitted files reported); trusted system prompt vs fenced untrusted content;
   `messages.parse` into Pydantic; retry once on invalid output; validation (path, range,
   context, evidence) and realignment; dedupe where analyzers win.
6. **Frontend (1 min).** TanStack Query polling, review page layout, LLM hypothesis labeling.
7. **Evaluation and honesty (1 min).** Three configs, matching rule, results, what's not run.

## 3. End-to-end request walkthrough: "Review HEAD~1..HEAD with LLM"

1. Browser `POST /api/repositories/1/reviews` with `{"kind":"diff","base_ref":"HEAD~1",
   "head_ref":"HEAD","use_ai":true}` and header `x-devpilot-csrf: 1`
   (`frontend/src/pages/RepositoryPage.tsx::StartReview` → `lib/api.ts::createReview`).
2. `main.py::guard` assigns a request ID, checks size and CSRF header.
3. `api/reviews.py::create_review` → `deps.current_user` (cookie → `sessions.token_hash`) →
   `owned_repo` (404 if not yours) → checks: indexed, local repo for `diff`, consent, rate limit
   → inserts `ReviewJob(status="queued")` and an audit event → `202`.
4. UI navigates to `/reviews/<id>`; `ReviewPage` polls `GET /api/reviews/<id>` every 1.5 s.
5. Worker thread (`workers/queue.py::Worker.run`) calls `run_once` → `claim_next` → status
   `running`.
6. `process_job` → `services/review.py::run_review`:
   - `_prepare_local_diff`: `validate_local_path` → `resolve_ref` ×2 → `export_git_tree(head)`
     into `data/snapshots/1/review-<id>` → `git_diff` → `parse_unified_diff`.
   - `discover_files`; `ChangedFile` rows.
   - Ruff and Bandit on changed `.py` files; `in_changed_lines` filter.
   - `build_context` → `AnthropicProvider.review(SYSTEM_PROMPT, prompt)` →
     `validate_ai_findings` → `deduplicate` → insert `Finding` and `TestSuggestion` rows,
     write `stats`.
7. `process_job` sets `completed`, commits. Next poll returns `completed`; the page loads
   findings (sorted by severity), changed files and test suggestions.
8. Clicking a finding calls `GET /api/reviews/<id>/file?path=...` → `read_snapshot_file`
   (resolved path must stay inside the snapshot) → `CodeView` highlights the lines.
9. Clicking *Useful* → `PUT /api/findings/<fid>/feedback` → upsert in `finding_feedback` with
   the analyzer and version.

## 4. Twenty likely questions, with answers grounded in the code

1. **Why not just send the diff to an LLM?** Analyzers are deterministic, free and precise on
   pattern bugs (7/7 correct on the benchmark), and they work without a key. LLM output needs
   verification; giving it analyzer results also stops it repeating them. ADR 0003.
2. **How do you stop the model inventing line numbers?** `validate_ai_findings`: path must be in
   the context, lines must exist and overlap the shown ranges, and the quoted evidence must be in
   the cited lines ±2. Failures are recorded with a reason. Test:
   `test_validation_accepts_grounded_and_rejects_hallucinated`.
3. **What if the model is right but off by one line?** `_realign` moves the range to the lines
   that contain the evidence. It exists because a test showed an off-by-one finding escaping
   dedupe.
4. **How do you handle prompt injection?** Content is fenced in `<repository_content>`, closing
   tags inside it are neutralized, the system prompt says it's untrusted, the model has no tools,
   and outputs are validated. Limitation: an injection that suppresses findings isn't detectable.
5. **What happens if the LLM is down?** The SDK retries 429/5xx twice; then the provider returns
   an error string, `stats.ai.status = "failed"`, and analyzer findings are still saved.
6. **Why a database table as a queue?** One fewer service, transactional with results, survives
   restarts; `FOR UPDATE SKIP LOCKED` lets multiple Postgres workers claim safely. Change to
   Redis + a task framework when you need retries, priorities, high throughput. ADR 0004.
7. **What does SKIP LOCKED do?** The `SELECT ... FOR UPDATE` locks the row it returns; other
   workers' identical query skips locked rows instead of waiting, so each job is claimed once.
   Not tested on Postgres yet; SQLite ignores it, so one worker there.
8. **How do you prevent zip slip?** Normalize separators, reject absolute/drive/`..`/`:` names,
   reject symlinks, and check the resolved target `is_relative_to(dest)`, all before writing.
9. **Zip bombs?** Count limit, declared total size limit, and counting real bytes while
   streaming each member, aborting past the limit (headers can lie).
10. **How is a user prevented from reading another user's review?** Every route goes through
    `owned_repo`/`owned_review`, which compare `owner_id` and return 404. Tested on all repo routes.
11. **Why 404 instead of 403?** 403 confirms the ID exists; 404 reveals nothing.
12. **How are sessions stored?** Random 256-bit token in an httpOnly SameSite=Lax cookie; DB
    stores SHA-256 of it. Logout deletes the row, so revocation is immediate (unlike stateless JWTs).
13. **CSRF?** Lax cookies aren't sent on cross-site POSTs, and every unsafe request must carry
    `x-devpilot-csrf: 1`, which a cross-site form can't set without a CORS preflight that would fail.
14. **How do you map findings to changed lines?** `parse_hunks` tracks the new-side line counter
    through `@@` headers, `+`, `-` and context lines; `added_lines` is a set; `in_changed_lines`
    checks intersection. O(lines in patch).
15. **How does search work, and what's its complexity?** SQL `LIKE` narrows chunks, then a regex
    finds matching lines and converts to absolute line numbers. Linear in the repo's chunks per
    query; fine for small repos, replace with trigram/FTS for large ones. ADR 0005.
16. **How do you deduplicate?** Exact duplicates among analyzer findings; then AI findings sorted
    by severity are dropped if they overlap an existing finding on the same file and share the
    category or have ≥0.4 Jaccard similarity of title+description tokens. O(n²) in findings per
    review, small n.
17. **Why is chunking by function for Python?** Search hits and review context make more sense as
    whole functions; `ast` gives exact start/end lines (including decorators) without native deps.
18. **How did you evaluate it, and what are the numbers?** Seventeen synthetic before/after
    cases; match by path + overlapping lines ±2. Static: P = 1.0, R = 0.538, 0/4 clean-case FPs.
    LLM configs not run. Caveats: synthetic, small, one setting tuned on the same set.
19. **What would you change for production?** Run on Postgres in CI; sandbox analyzer
    subprocesses; move rate limits to shared storage; background indexing; real benchmark data;
    measure LLM cost/quality; security headers; observability exports.
20. **What was the hardest bug?** Either the `strip_top` bug (a heuristic for GitHub zipballs
    silently dropped a directory level in `git archive` output, found by a test), or the ligature
    issue (the UI displayed `>=` as `≥` in a code review tool, found only by looking at the page).

## 5. Difficult trade-offs

| Choice | Alternative | What we gave up |
|---|---|---|
| Evidence must be quoted verbatim | Trust model line numbers | Some correct findings are rejected when the model paraphrases |
| One LLM call per review with a char budget | Per-file calls | Large changes get truncated (reported to the user) |
| Analyzer findings win in dedupe | Prefer the model's richer explanation | Model's reasoning text is lost for those issues |
| Changed-lines-only filter for diffs | Report everything in changed files | Misses pre-existing issues next to the change, by design |
| Import/index in the request | Background indexing | Slow for big repos, request may time out |
| Lexical search | Embeddings | No semantic search |
| In-memory rate limiting | Redis | Doesn't work across replicas |
| Per-repo LLM consent | Global setting | One more click, but explicit data-flow control |

## 6. Most important source files

| File | Why it matters |
|---|---|
| `backend/app/services/review.py` | The whole pipeline in one function; start here. |
| `backend/app/services/ingestion.py` | All hostile-input handling. |
| `backend/app/ai/context.py` | What the model sees and the exact system prompt. |
| `backend/app/services/findings.py` | Hallucination filter and dedupe. |
| `backend/app/ai/provider.py` | Provider abstraction and failure handling. |
| `backend/app/workers/queue.py` | Job claiming, failure recording, recovery. |
| `backend/app/services/diff.py` | Changed-line mapping. |
| `backend/app/api/deps.py` | Authentication and ownership checks. |
| `backend/app/analyzers/python_tools.py` | How external tools become normalized findings. |
| `frontend/src/pages/ReviewPage.tsx` | The main UI. |
| `evaluation/scripts/run_eval.py`, `scoring.py` | How the numbers are produced. |

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UI says "Cannot reach the DevPilot API" | Backend not running on :8000 | Start uvicorn; check `DEVPILOT_API` for Vite |
| Every request 403 "Missing CSRF header" | Calling the API without `x-devpilot-csrf: 1` | Add the header (the UI does this) |
| Local import "disabled on this server" | `DEVPILOT_ALLOWED_LOCAL_ROOTS` empty | Set it in `backend/.env`, restart |
| Local import "outside the directories" | Path not under an allowed root | Fix the path or the root |
| Review stuck in `queued` | Worker not running (`DEVPILOT_RUN_WORKER_IN_PROCESS=false` with no standalone worker) | Start `python -m app.workers.queue` or enable in-process |
| Review stuck in `running` | Server restarted mid-job | Restart; stale-job recovery fails it after `DEVPILOT_JOB_TIMEOUT_S` |
| LLM "skipped: No LLM provider is configured" | No `ANTHROPIC_API_KEY` | Set it in the backend environment |
| LLM "failed: provider rejected credentials" | Bad key | Check the key |
| Analyzer `failed` in run summary | Ruff/Bandit missing or timed out | `uv sync`; check the error tooltip and server logs |
| `RuntimeError: DEVPILOT_SECRET_KEY must be set` | `DEVPILOT_ENV` not `development` | Generate a Fernet key (see `.env.example`) |
| GitHub "rejected the stored token" | Token revoked/expired | Disconnect and reconnect in Settings |
| Playwright webServer timeout on Windows | Vite bound to IPv6 | Config already uses `--host 127.0.0.1`; check ports 8001/5174 are free |
| 500 with a request ID | Unhandled exception | Search server logs for that request ID |

## 8. Reproducible demo checklist

- [ ] `backend/.env` exists, `DEVPILOT_ALLOWED_LOCAL_ROOTS` covers the demo repo's parent.
- [ ] `python scripts/make_demo_repo.py ../devpilot-demo-repo` (fresh directory).
- [ ] `uv run alembic upgrade head`, start API, start Vite.
- [ ] `uv run pytest -q` passes (65) — have the output ready.
- [ ] Follow [demo.md](demo.md) steps 1–7.
- [ ] Have `evaluation/reports/latest.md` open.
- [ ] If showing the LLM stage: key set, consent ticked, expect 30–120 s per review.

## 9. Limitations to disclose

- LLM review has never been run against the real API; all LLM numbers are unmeasured.
- GitHub integration only tested against mocks; PostgreSQL and Docker paths never run.
- Benchmark: 17 synthetic cases, written by the same author, one setting tuned on it.
- Python-only static analysis.
- Lexical search; synchronous import/indexing; in-memory rate limits; single worker on SQLite.
- Analyzer subprocesses are not sandboxed.
- Built with an AI coding assistant.

## 10. Self-assessment checklist

You're ready when you can do each of these without looking at the docs:

- [ ] Draw the architecture and explain why there's no Redis.
- [ ] Trace a review from button click to saved findings, naming the functions.
- [ ] Explain all four checks in `validate_ai_findings` and give an example each one catches.
- [ ] Explain how `parse_hunks` computes new-side line numbers; do it by hand for a small hunk.
- [ ] Explain three ZIP attacks and the line of code that stops each.
- [ ] Explain why `git archive` is used, and which git config options are overridden and why.
- [ ] Explain the session design and why logout is immediate.
- [ ] Explain the dedupe rule and one case where it would wrongly drop a finding.
- [ ] Recite the evaluation numbers and three caveats.
- [ ] Explain what `SKIP LOCKED` does and why SQLite needs a single worker.
- [ ] Change something small (e.g. add a Ruff rule family), run the tests, and explain the diff.
- [ ] Run the e2e test and explain what it checks.
- [ ] Name five limitations without prompting.
