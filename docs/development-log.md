# Development log

All entries are from the initial build session on 2026-10-17 (single session, AI-assisted with
Claude Code). Git history starts after this session; nothing here is reconstructed from memory.

## 1. Environment and plan

- Found: Windows 11, Python 3.13 and 3.12, uv 0.13.1, Node 22.14, Git 2.49, Docker CLI 28 with
  the daemon **not running**, no PostgreSQL, no LLM API key in the environment.
- Consequences decided up front: SQLite for development/tests, PostgreSQL only via compose;
  LLM path built against a provider interface and tested with replayed responses; Docker files
  validated but not run.
- MVP slice chosen: ZIP/local import → index → analyzers → findings UI, then LLM, then GitHub.

## 2. Backend foundation

- Files: `app/core/*`, `app/models.py`, `alembic/`.
- Decisions: server-side sessions (hashed tokens) instead of JWTs, so logout really revokes;
  Fernet for GitHub tokens; `review_jobs` doubles as the queue (ADR 0004).
- Bug: `DEVPILOT_ALLOWED_LOCAL_ROOTS` crashed settings loading because pydantic-settings parses
  list fields as JSON. Fixed with `NoDecode` + a splitting validator.

## 3. Ingestion, chunking, diffs, analyzers

- Files: `services/ingestion.py`, `services/chunking.py`, `services/diff.py`, `analyzers/*`.
- Sampled real Ruff and Bandit JSON output before writing the adapters, to map fields exactly.
- Bug (caught by `test_export_and_diff_local_repo`): `safe_extract_zip` always stripped a single
  top-level folder; `git archive` of a repo whose only top-level entry was `pkg/` lost that
  directory. Made stripping opt-in (`strip_top`) for uploads and GitHub zipballs.
- Wrong expectations in the first version of the chunking tests (function end lines) fixed after
  checking the source.

## 4. LLM review

- Files: `ai/schema.py`, `ai/context.py`, `ai/provider.py`, `services/findings.py`, `services/review.py`.
- Checked the installed Anthropic SDK (1.15.0) signature for `messages.parse(output_format=...,
  output_config=...)` and its schema transform before relying on it.
- Bug (caught by `test_full_review_with_ai_validates_and_dedupes`): a replayed model finding cited
  line 26 for code on line 27; the evidence check accepted it (±2 slack), but it then failed to
  dedupe against Bandit's line-27 finding. Added `_realign` to move ranges onto the quoted code.
- Decision: provider failure never fails the job; it is recorded in `stats.ai`.

## 5. API, worker, GitHub

- 33 endpoints. Ownership checks return 404.
- Bug: tests leaked queued jobs into each other through the shared DB; the worker picked another
  test's job. Added a fixture that clears pending jobs per test.
- GitHub client takes an injectable `httpx` transport so it can be tested without network.
- Result: backend 59 passing, then ruff/mypy cleanup (mypy found `Optional` handling gaps in
  `review.py` and `deps.py`; fixed with explicit checks).

## 6. Frontend

- React + Vite + Tailwind 4 + TanStack Query; pages for login, repositories, repository, review,
  settings.
- Manual check in the browser found two issues:
  1. Bare `except` (Ruff E722) was rated "low" because the severity rule only looked at the
     prefix letter. Now medium. Findings are also sorted by severity in the API.
  2. The monospace font rendered `>=` as a `≥` ligature in the diff view, hiding the exact
     operator in exactly the defect being reviewed. Disabled ligatures for code.
- Playwright e2e: first runs failed on Windows because Vite bound to IPv6 `localhost` while
  Playwright waited on `127.0.0.1`; bound explicitly. Two selector ambiguities fixed.

## 7. Evaluation

- 17 synthetic cases. First static-only run: precision 0.778, recall 0.538; both false positives
  were Bandit B603/B607 on a safe list-form subprocess call. Skipped those rules; second run
  precision 1.0, recall unchanged. Recorded that this was tuned on the evaluation set.
- `ai` and `combined` not run: no API key.

## 8. Packaging and docs

- Dockerfiles, compose (Postgres + API + worker + nginx), CI workflow. `docker compose config`
  passes; nothing built. pip-audit and npm audit: no known vulnerabilities.
- Documentation written against the final code.

## Next steps

1. Run `pytest -m live_llm` and the `ai`/`combined` evaluation with a real key; record cost.
2. Push to GitHub so CI runs; add a PostgreSQL service to the backend job.
3. Build and run the compose stack.
4. Add real-world benchmark cases from permissively licensed projects.

## 9. Post-build audit

Same day, after the build. Details in [audit-report.md](audit-report.md) and [verification-report.md](verification-report.md).

- Re-ran everything from the lockfiles. `npm ci` failed once because the running Vite server held
  files in `node_modules`; stopped it and re-ran.
- Confirmed and fixed:
  1. Compose overrode the snapshot directory with `.env`'s `./data` (seen in `docker compose config`). `docker-compose.yml` now pins `/data`.
  2. Chunked multipart uploads bypassed the `Content-Length` cap and were spooled to disk (reproduced with a 60 MB upload). Now 411.
  3. Unexpected errors during indexing left repositories stuck in `indexing`. Now marked `failed`.
  4. Login throttling would have keyed on nginx's IP. uvicorn now reads `X-Forwarded-For`.
  5. nginx dropped the port from `Host`, breaking OAuth redirect URIs in compose.
  6. CI end-to-end setup called `python`, which Ubuntu runners may not have.
  7. Wrong OAuth callback URL in the docs.
- Removed dead code: `CATEGORIES`, `enclosing_definition` (and its test), the unused `api.files`.
- Added tests for fixes 2 and 3. Backend: 64 before the audit, +2 new, −1 removed with dead code = 65 passed.
- Exercised authorization, invalid refs, path traversal, missing credentials and CSRF against the live server with curl (results in the verification report).
- Benchmark re-run: identical static results.
- Not fixed: in-memory GitHub downloads, synchronous indexing, unpruned rate-limiter keys.

## 10. Ollama provider (free local review)

- Goal: make AI review real on a zero budget. Nothing was installed or downloaded.
- `backend/app/ai/provider.py`: `OllamaProvider` calls `/api/chat` with httpx, passes the
  `AIReview` JSON schema as `format`, `stream: false`, `temperature: 0`, and an explicit
  `num_ctx`. Same result type and retry rules as the Anthropic provider; transport errors are not
  retried. `get_provider` picks it when `DEVPILOT_LLM_PROVIDER=ollama`.
- Decision: refuse prompts estimated above 75% of `num_ctx`, because Ollama truncates the start of
  an over-long prompt silently, which would drop the system prompt's rules.
- `backend/app/core/config.py`: `ollama_url`, `ollama_model`, `ollama_num_ctx`; `active_llm_model`;
  `llm_is_local` (true only for a loopback URL). `/api/settings` exposes `local`.
- UI: Settings and the repository consent text say when the model is local and no longer only
  tell users to set `ANTHROPIC_API_KEY`.
- Evaluation: cost `0.0` for local runs; provider and model in each row; failure-rate column.
  Bug found while checking this change: with Ollama unreachable, the AI row looked like a real
  result (recall 0.0, cost 0.0). A configuration whose LLM calls all failed is now reported as
  `failed` with the reason.
- Tests: 12 new in `tests/test_ollama_provider.py`. The queue-clearing fixture moved from
  `test_api.py` to `conftest.py` so new test files cannot pick up another test's jobs.
- Results: backend 77 passed (2 live tests deselected), frontend 7, e2e 2; ruff, format, mypy,
  typecheck, build clean.
- Not done: installing Ollama, pulling a model, any live run.

## 11. UI polish pass

- Design tokens in `frontend/src/index.css`: navy/charcoal dark theme and a refined light theme;
  semantic colors (ok, warn, danger, info, ai) each with a soft background; a type scale
  (`text-display` 28-38px responsive, `text-title` 22px, `text-body` 15px, `text-label`);
  control and card radii; card and popover shadows; one focus ring.
- `frontend/src/components/ui.tsx`: new `PageHeader`, `Card` (with optional header), `Tabs`
  (replaces three hand-written tab bars), `Stat`, `Pill`, `Label`, `Notice`; restyled buttons
  (two sizes), badges, inputs, empty, loading and error states. All hardcoded Tailwind palette
  colors were replaced with tokens.
- Pages restyled on the shared components: sign-in, repositories (summary metrics computed from
  the real repository list), repository detail, review, settings (grouped into Integrations,
  LLM review, Limits and retention).
- Bug fixed while checking in the browser: opening a review scrolled the whole page down to the
  code, because `scrollIntoView` also scrolls the window. `CodeView` now scrolls only its own panel.
- Mobile fixes found at 375px: header clipped its buttons, pills wrapped out of their height,
  long titles broke mid-word next to action buttons.
- The e2e test looked for the old lowercase text "files indexed"; updated to the new label.
- Checks: ESLint 0 errors (5 existing warnings), Prettier, typecheck, 7 unit tests, build, 2 e2e
  tests pass. No backend, API or test-logic changes.

## 12. First real benchmark with a local model

- Connected Ollama to the app (`backend/.env`: `DEVPILOT_LLM_PROVIDER=ollama`). Fixed a test-isolation
  bug: `tests/conftest.py` now pins `DEVPILOT_LLM_PROVIDER=anthropic`, because the tests had started
  reading the developer's `.env` and one test called the real local model.
- Ran `DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined`
  with no code or prompt changes. 51 jobs, 34 model calls, all completed in 4 min 6 s.
- Result: `qwen2.5-coder:3b` returned no findings in AI-only mode and only repeated analyzer issues in
  combined mode. Valid output and citations, zero hallucinated findings, zero added value.
- Raw outputs kept in `evaluation/reports/20261017T131333Z*`. Analysis in `docs/evaluation.md`.

## 13. Prompt experiment: checklist system prompt

- Added `--system-prompt-file` to `evaluation/scripts/run_eval.py`. It replaces the system prompt
  only inside the benchmark process and records the prompt source and a sha256 prefix in every
  report (production prompt: `5c21f3eb540ed09c`). The application code was not changed.
- Variant `evaluation/prompts/system_v2_checklist.txt`: same rules plus a 7-item defect checklist
  and "trace a triggering input". Two items were generalized before running because they matched
  specific seeded cases.
- Result with qwen2.5-coder:3b: 0 findings in all 34 calls (baseline combined mode had 4 repeats of
  analyzer issues). No improvement; production prompt kept. Report:
  `evaluation/reports/experiments/v2-checklist/REPORT.md`.

## 14. Experiment v3: two-step reasoning

- `evaluation/scripts/two_step.py`: `TwoStepOllamaProvider` (plain-text analysis, then the normal
  structured call with fenced notes). Plugged in only through `run_eval.py --strategy two-step`
  using the pipeline's existing `provider_factory` parameter; no application code changed.
- Tests: `backend/tests/test_two_step.py` (request shapes, notes fencing, step-A failures, malformed
  step-B output). Backend suite 81 passed.
- First combined attempt aborted: GPU held at 300 MHz under load, calls timed out. Re-run after the
  clock recovered; aborted data kept as evidence only.
- Result: AI-only 2/13 (first model-only detections), combined no gain, ~7x latency, one HTTP 500.
  Not adopted. Report: `evaluation/reports/experiments/v3-two-step/REPORT.md`.

## 15. v3 repeated runs (stopped)

- Added `evaluation/scripts/repeat_v3.sh`: one folder per run, never overwrites, samples the GPU and
  aborts on throttling or repeated HTTP 500.
- The first run aborted after ~7 min: GPU at 300 MHz under load (reasons 0x24, software power cap +
  thermal slowdown). Remaining runs not started. Same HTTP 500 on the same case as before.
- No code, prompt, model, dataset or scoring changes. Report:
  `evaluation/reports/experiments/v3-two-step/repeats/REPORT.md`.

## 16. v3 repeated runs completed, and a harness flaw found

- After performance mode and better cooling, ran 3 AI-only and 3 combined two-step runs one at a
  time with cool-downs (`repeat_v3.sh <run>`). No throttling (1,680-1,785 MHz under load).
- Ollama restarted in a visible terminal with debug logging. The HTTP 500 is
  `prediction aborted, token repeat limit reached`: the model loops on one case every time.
- Results: AI-only 2/13 in all three runs; combined 7, 8, 7. No false positives.
- Found: the harness names test repositories `<config>-<case id>` and the name appears in the
  prompt, so defect-describing case IDs leaked into every LLM run. Not fixed during the experiment;
  proposed fix: neutral repository names, then rerun. Report:
  `evaluation/reports/experiments/v3-two-step/repeats/REPORT.md`.

## 17. Label leak fixed; corrected benchmark

- `evaluation/scripts/scoring.py`: `opaque_repo_name(case_id)` (sha256-based, stable across
  configurations). `run_eval.py`: opaque repository names and folders, one evaluation user per
  configuration, `"label_blind": true` in reports, `--dump-prompts` dry run.
- `backend/tests/test_eval_leakage.py`: 5 tests (opaque names, label changes do not change the prompt,
  no ID words in prompt metadata, same template for all cases, guard against the old scheme).
- Inspected dry-run prompts from the real pipeline. Static baseline re-run identical to history.
- `evaluation/scripts/run_label_blind.sh`: 13 runs with cool-downs and per-run abort rules; none
  aborted, no throttling.
- Result: AI-only 0/13 (single and two-step, 3x each); combined 7/13 (= analyzers, 3x each). The
  earlier 2/13 and 8/13 do not reproduce without the leak. HTTP 500 = Ollama repeat-limit abort on
  one case in combined two-step only.
- Docs: corrected results at the top of `docs/evaluation.md`; all earlier LLM results labelled as
  historical and potentially contaminated, with banners on the old experiment reports.

## 18. Static-analysis coverage from benchmark evidence

- Classified the six label-blind misses: four need intent or data-flow reasoning (left alone to avoid
  memorizing the benchmark), two are mechanical.
- Enabled Ruff `SIM115` (unclosed `open`). Added `backend/app/analyzers/ast_rules.py` with DP001
  index-equals-length, registered in `default_analyzers()`. 6 tests in `tests/test_ast_rules.py`.
- False-positive check on real code: DP001 0 hits in ~1.2M lines; SIM115 10 hits in ~589k lines,
  6 inspected, all deliberate patterns (kept, documented as a cost).
- Label-blind rerun (new folder `label-blind-static-v2`): analyzer-only 9/13 (from 7/13), precision
  1.0, 0 clean-case FPs; combined single (3x) and two-step (1x) also 9/13. No regressions.

## 19. Finalizing the static-analysis improvements

- Verified `label-blind-static-v2/combined-two-1` from its raw JSON and database: label-blind (opaque
  names), 9/13, precision 1.0, 0/4 clean FPs, 1 HTTP 500 on step A, no structured-output retries.
- Audit: no case IDs, paths, line numbers or dataset text in the rule code. DP001 now reports hits in
  source order (`ast.walk` is breadth-first). SIM115 findings carry a rule-specific caveat
  (`RUFF_LIMITATIONS`). 4 more tests (realistic safe/buggy code, pinned limitations): 10 rule tests.
- `evaluation/scripts/scan_real_code.py` makes the real-code scan reproducible and saves
  `scan.json`/`scan.md`. All 10 SIM115 hits read: 9 deliberate, 1 minor real (bandit, error path).
  This corrects an earlier statement based on 6 of 10.
- `evaluation/scripts/compare_runs.py` builds `evaluation/reports/experiments/COMPARISON.md` from raw
  runs (refuses any run without `label_blind: true`).
- No independent labelled corpus exists; validation plan added to the v2 report.

## 20. Evaluation artifacts and git policy (2026-10-18)

- Compared `eval.db` with each run's JSON. The databases held unique evidence (per-case attempts,
  tokens, model returned/accepted/rejected findings and summaries, duplicates removed, analyzer
  versions, stage timings, full finding text) but also absolute temp paths with the local username,
  generated emails and regenerable bulk.
- Decision: keep `*.db` ignored. Added `evaluation/scripts/run_details.py`, which exports the unique
  evidence to a deterministic, path-free `details.json` per run (30 exported, 932 KB). `run_eval.py`
  now writes it automatically. `compare_runs.py` reads only `latest.json` + `details.json`, checks
  they agree, refuses non-label-blind or incomplete runs, and writes UTF-8 explicitly. Its output is
  byte-identical to the earlier database-based version.
- `.gitignore`: added SQLite journals, per-run console logs, `CONTEXT.md` and `.claude/`.
- Privacy: removed the local demo password from `CONTEXT.md`; replaced a local path in
  `docs/api-reference.md`; made `ollama-serve-logged.ps1` take parameters.
- Saved the Ollama log lines behind the HTTP 500 diagnosis
  (`label-blind/ollama-repeat-limit-excerpt.log.txt`): 10 repeat-limit aborts plus one 120 s client
  timeout; consistent with every recorded failure.
- New `evaluation/README.md`; 7 tests in `tests/test_eval_artifacts.py`.
