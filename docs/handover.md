# Handover

State of DevPilot on 2026-10-17, after the post-build audit.

## Works and verified (by tests that ran and/or by hand in the running app)
Accounts and sessions; per-user isolation; CSRF and size limits; ZIP and local-Git import with
safe extraction; secret/binary filtering; indexing and search; whole-repo and `base..head`
reviews in the background worker; Ruff and Bandit findings; changed-line filtering; findings UI
with filters, highlighted source, diffs and test suggestions; feedback; history; LLM consent gate;
graceful behavior with no LLM key; model-output validation and dedupe (with replayed responses);
stale-job recovery; the static-only benchmark.

## Works but not fully verified
Real Anthropic calls; GitHub OAuth, import and PR reviews (mocked HTTP only); PostgreSQL and
multi-worker claiming; Docker images and compose (including three compose fixes made in the
audit); the CI workflow; retention cleanup; login throttling.

## Incomplete
Non-Python analyzers; real-world benchmark cases; LLM benchmark runs; streaming GitHub downloads;
background indexing; GitHub PR comments; password reset/MFA; tracing export.

## Tests executed (final run)
Backend 65 passed (1 live-LLM test deselected); frontend 7 passed; Playwright 2 passed; ruff,
mypy, Bandit, ESLint (0 errors), Prettier, typecheck, build: clean; pip-audit and npm audit: no
known vulnerabilities. Full log: [verification-report.md](verification-report.md).

## Defects fixed in the audit
Compose data directory (high); chunked-upload spooling; repos stuck in `indexing`; client IP
behind nginx; nginx Host header port; CI `python` dependency (medium); OAuth callback docs; dead
code (low). Details: [audit-report.md](audit-report.md#9-defects-by-priority).

## Outstanding risks
Analyzer subprocesses not sandboxed; GitHub downloads buffered in memory; in-memory, per-process
rate limits; no job pre-emption; prompt injection that suppresses findings is undetectable;
nothing tested on PostgreSQL or in Docker. Full list: [security.md](security.md#known-gaps-and-remaining-risks).

## Run locally
```bash
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8000
cd frontend && npm ci && npm run dev        # http://localhost:5173
```
Copy `.env.example` to `backend/.env` first and set `DEVPILOT_ALLOWED_LOCAL_ROOTS` for local imports.

## Demonstrate a review
[demo.md](demo.md): build the sample repo with `scripts/make_demo_repo.py`, import it, run a
whole-repo review (3 findings), then `HEAD~1..HEAD` (0 findings: the bugs are logic errors).

## Benchmark
17 synthetic cases. Static-only: precision 1.0, recall 0.538, 0/4 clean-case false positives,
reproduced on two runs. LLM-only and combined: not run (no key). p95 latency not reported
(needs ≥20 cases). [evaluation.md](evaluation.md).

## Read these five files first
1. `backend/app/services/review.py`: the whole review pipeline.
2. `backend/app/services/ingestion.py`: how hostile input is handled.
3. `backend/app/services/findings.py`: model-output validation and dedupe.
4. `backend/app/ai/context.py`: exactly what the model sees.
5. `backend/app/workers/queue.py`: jobs, failures and recovery.

Then [walkthrough.md](walkthrough.md) and the questions in [interview-guide.md](interview-guide.md).

## Next milestone
**"Measured and deployed once":** run `pytest -m live_llm` and the `ai`/`combined` benchmark with
a real key (record cost); run CI on GitHub with a PostgreSQL service; bring up the compose stack
and complete one review in it. Those three turn every "not verified" item above into a measured one.
