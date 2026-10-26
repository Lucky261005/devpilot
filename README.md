# DevPilot

DevPilot reviews code changes in a repository and reports potential defects with exact file and
line citations. It combines deterministic analyzers (Ruff, Bandit) with an optional LLM review,
and it keeps the two apart: analyzer results are labeled with their rule IDs, and model output is
labeled as a hypothesis and shown only after it is checked against the source.

It is a student portfolio project, built as a working MVP. It has not been used by real teams, and
the evaluation numbers below come from a small synthetic benchmark.

## What problem it solves

Code review catches defects late and inconsistently, and LLM reviewers tend to produce confident
comments that cite lines that don't exist. DevPilot runs the cheap, reliable checks first, gives
the model a bounded and line-numbered view of the change, and throws away model findings whose
path, line range or quoted evidence don't match the code.

**Intended users:** individual developers and small teams who want a second pass on a branch or
pull request, with findings they can verify in a few seconds.

## Features (MVP)

Status of every item, with what is and isn't verified, is in [docs/feature-status.md](docs/feature-status.md).

- Email/password accounts, server-side sessions in httpOnly cookies, per-user data isolation.
  Registration can be `open`, `invite`-only or `closed`; the server operator can always create
  accounts with `python -m app.cli create-user`.
- Import a repository from a **ZIP upload**, a **local Git path** (inside admin-approved
  directories), or **GitHub** (GitHub App sign-in; only repositories you install the App on, any branch,
  imported at that branch's exact commit).
- Safe ingestion: traversal/symlink/zip-bomb checks, size limits, binary and secret-file exclusion.
- Code search by text or definition name, with file/line results and a source viewer.
- Reviews of a whole snapshot, a local `base..head` range, or a GitHub pull request; run by a
  background worker with queued → running → completed/failed states.
- Ruff + Bandit findings normalized into one format with rule IDs, versions, evidence and docs links.
  Ruff rules that indicate a likely runtime defect are labeled `bug`; the rest (for example B905,
  `zip()` without `strict=`) are labeled `maintainability`, and no confidence is claimed for them.
- Optional LLM review with structured output, through either Anthropic Claude (paid API) or a
  local model served by Ollama (free, code stays on the machine), with citation validation,
  deduplication against analyzer findings, token/latency accounting and a per-repository opt-in.
  Files too large for the context budget are sent as line-numbered excerpts, and the review page
  shows how many files the model saw whole, in part, or not at all.
- Test suggestions for public functions no test references. A complete test is generated only
  from doctest examples in the docstring; otherwise the suggestion is a **test gap** that names
  the function, its signature and the exceptions it raises. Model-written tests with placeholders
  are dropped. Nothing is executed.
- Repository Q&A (**Ask** tab): keyword retrieval over the indexed code, an answer from the LLM
  that cites file and line ranges, and citations checked against the excerpts it was given.
- Home page with recent reviews across your repositories; review progress by worker stage.
- Feedback on each finding (useful / incorrect / duplicate / not actionable), stored with the
  analyzer or model version.
- Database-backed limits: sign-in throttling per account and per IP, imports and reviews per user
  per hour, and an installation-wide review cap.
- An evaluation harness comparing analyzer-only, LLM-only and combined configurations.

## Architecture

```
 Browser (React + TanStack Query)
        │  /api  (JSON, session cookie, CSRF header)
        ▼
 FastAPI app ── auth · repositories · reviews · github routers
        │                │
        │                ├── ingestion (zip / git archive / GitHub zipball) → snapshot dir
        │                └── indexing (chunks with path + line ranges) → code_chunks
        ▼
 SQL database (PostgreSQL in Docker, SQLite locally)  ◄── review_jobs is also the job queue
        ▲
        │ claim (FOR UPDATE SKIP LOCKED)
 Review worker (thread in the API, or its own process)
   prepare snapshot + diff → Ruff/Bandit → [LLM: context → structured output → validate] → dedupe → save
```

Details: [docs/architecture.md](docs/architecture.md).

## Technology choices

| Area | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic | Typed request/response validation and OpenAPI docs with little code. |
| ORM / migrations | SQLAlchemy 2 + Alembic | Mature, works on PostgreSQL and SQLite; migrations are tested by the suite. |
| Database | PostgreSQL (SQLite for dev) | Relational data with FKs and cascades; `SKIP LOCKED` makes the DB a safe job queue. |
| Analyzers | Ruff, Bandit | Fast, well-known, JSON output, permissive licenses (MIT / Apache-2.0). |
| Source parsing | Python `ast` | Function boundaries for Python without a native dependency (see [ADR 0005](docs/decisions/0005-parsing-and-search.md)). |
| LLM | Anthropic SDK `messages.parse`, or Ollama `/api/chat` via httpx | Both constrained to the same JSON schema and validated into the same Pydantic models. |
| Frontend | React, Vite, TypeScript, Tailwind, TanStack Query | Standard, fast feedback; Query handles polling and caching. |
| Tests | pytest, Vitest + Testing Library, Playwright | Unit/integration, component, and browser end-to-end. |

ADRs: [docs/decisions/](docs/decisions/).

## Getting started (local, no Docker)

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, Git. Commands below are for
PowerShell on Windows; in Git Bash or on macOS/Linux use `cp` instead of `Copy-Item`.

**1. Backend** (terminal 1). The API runs the review worker in the same process by default.

```powershell
cd backend
Copy-Item ..\.env.example .env   # settings are read from backend\.env; see "Configuration"
uv sync
uv run alembic upgrade head      # creates backend\devpilot.db (SQLite)
uv run uvicorn app.main:app --port 8000
```

**2. Frontend** (terminal 2):

```powershell
cd frontend
npm install
npm run dev                      # http://localhost:5173, proxies /api to :8000
```

**3. First account.** Open http://localhost:5173 and choose **Create one**; registration is open in
development. Or, from `backend`: `uv run python -m app.cli create-user --email you@example.com`.

**4. A repository to review.** Upload a ZIP of any Python project, or build the synthetic sample
(with seeded defects, listed in `fixtures/sample_repositories/inventory_service/SEEDED_DEFECTS.md`)
as a Git repository and import it through **Local Git path**. From the repository root:

```powershell
python scripts/make_demo_repo.py ..\devpilot-demo-repo
```

Local import reads only below `DEVPILOT_ALLOWED_LOCAL_ROOTS`, so set it in `backend\.env` to the
parent folder of `devpilot-demo-repo` and restart the API. A step-by-step demo is in
[docs/demo.md](docs/demo.md).

**Stopping and restarting.** Press Ctrl+C in both terminals; data stays in `backend\devpilot.db` and
`backend\data`. Start again with the same `uvicorn` and `npm run dev` commands. After pulling new
code, back up the database (copy `devpilot.db` while the API is stopped) and run
`uv run alembic upgrade head` before starting the API.

### LLM review (optional)

Without a configured provider, reviews run the analyzers only and the Ask tab explains that no
model is configured; everything else works. `.env.example` selects `anthropic`, which stays
disabled until `ANTHROPIC_API_KEY` is set. For a free local model:

1. Install [Ollama](https://ollama.com) and run `ollama pull qwen2.5-coder:3b` (about 1.9 GB).
2. In `backend\.env` set `DEVPILOT_LLM_PROVIDER=ollama`, then restart the API.
3. On a repository page, tick **Allow LLM review for this repository**; code is sent to the model
   only after that.

A 3B local model is fast enough to try but finds few defects; see "Known limitations".

## Getting started (Docker Compose)

```bash
cp .env.example .env    # in the repository root; set DEVPILOT_SECRET_KEY (required in this mode)
docker compose up --build
# UI on http://localhost:8080 (this machine only)
docker compose exec backend python -m app.cli create-user --email you@example.com   # first account
```

Compose runs PostgreSQL, the API, a separate worker process and nginx serving the built UI. It
forces production settings (`DEVPILOT_ENV=production`, `DEVPILOT_COOKIE_SECURE=true`), so public
registration defaults to `invite` and the first account is created with the command above. The UI
is published on `127.0.0.1:8080` only; to use it from other machines, put an HTTPS reverse proxy on
the host in front of it, as described under Deployment assumptions in
[docs/security.md](docs/security.md).
The stack has been started on a disposable setup for the backup and restore drill
([docs/backup-restore.md](docs/backup-restore.md)); the HTTPS-proxy path and the remaining
hardening checks are configuration-only (see [docs/feature-status.md](docs/feature-status.md)).

## Configuration

All settings are environment variables, documented in [.env.example](.env.example). The ones
that matter most:

| Variable | Default | Purpose |
|---|---|---|
| `DEVPILOT_DATABASE_URL` | `sqlite:///./devpilot.db` | SQLAlchemy URL. Compose uses PostgreSQL. |
| `DEVPILOT_SECRET_KEY` | empty | Fernet key for encrypting GitHub tokens. Required outside development. |
| `DEVPILOT_ALLOWED_LOCAL_ROOTS` | empty (disabled) | `;`-separated directories that local import may read. |
| `DEVPILOT_LLM_PROVIDER` | `anthropic` | `anthropic`, `ollama` or `none`. |
| `ANTHROPIC_API_KEY` | empty | Enables Claude review when the provider is `anthropic`. |
| `DEVPILOT_OLLAMA_URL` / `_MODEL` / `_NUM_CTX` | `http://127.0.0.1:11434` / `qwen2.5-coder:3b` / `16384` | Local model settings when the provider is `ollama`. |
| `DEVPILOT_LLM_MODEL` | `claude-opus-5-5` | Model ID. |
| `DEVPILOT_GITHUB_CLIENT_ID` / `_SECRET` | empty | GitHub App user-authorization credentials; callback is the UI address + `/api/github/oauth/callback` (dev: `http://localhost:5173/...`). See [docs/github-app.md](docs/github-app.md). |
| `DEVPILOT_GITHUB_APP_SLUG` | empty | The App's URL name, for the "choose repositories" link. |
| `DEVPILOT_REGISTRATION` | `open` in development, `invite` elsewhere | `open`, `invite` or `closed`. Existing accounts can always sign in. |
| `DEVPILOT_INVITE_CODE` | empty | Required for `invite` mode; empty means nobody can register over HTTP. |
| `DEVPILOT_COOKIE_SECURE` | `false` | Must be `true` outside development, or the API and worker refuse to start. Compose sets it. |
| `DEVPILOT_HSTS_SECONDS` | `0` (off) | `Strict-Transport-Security` max-age, sent outside development only. Set only when every request arrives over HTTPS. |
| `DEVPILOT_PUBLIC_ORIGIN` | empty (`http://localhost:8080`) | Compose only: the HTTPS address users open when a reverse proxy serves DevPilot. |
| `DEVPILOT_REVIEWS_PER_HOUR` / `_GLOBAL_PER_HOUR` | `30` / `60` | New reviews per hour: per user, and for the whole installation. |
| `DEVPILOT_RUN_WORKER_IN_PROCESS` | `true` | Run the review worker as a thread in the API process. |

## Commands

| Task | Command |
|---|---|
| Backend tests | `cd backend && uv run pytest` |
| Backend lint / types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` |
| Frontend unit tests | `cd frontend && npm test` |
| Frontend lint / types | `npx eslint . && npm run typecheck` |
| End-to-end tests | `cd frontend && npx playwright test` (starts its own backend on :8001 and UI on :5174) |
| Evaluation | `cd backend && uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined` |
| Standalone worker | `cd backend && uv run python -m app.workers.queue` |
| Retention cleanup (old review snapshots, expired sessions and sign-in records) | `cd backend && uv run python -m app.cli cleanup` |
| Create an account (any registration mode) | `cd backend && uv run python -m app.cli create-user --email you@example.com` |
| New migration | `cd backend && uv run alembic revision --autogenerate -m "..."` |

## Test and evaluation results

- **Tests.** CI (`.github/workflows/ci.yml`) runs backend lint, types, Bandit, pytest and a
  dependency audit; frontend ESLint, Prettier, type check, Vitest, build and `npm audit`;
  Playwright end-to-end tests; and the static-only evaluation. Live-model and live-GitHub tests
  are marked and skipped by default (`-m live_llm`, `-m live_github` to run them).
  Current counts and dates are recorded in [docs/verification-report.md](docs/verification-report.md).
- **Evaluation** (17 synthetic cases, 13 seeded defects, 4 clean cases), analyzer-only: precision
  1.0, recall 0.692 (9/13 after adding Ruff SIM115 and DevPilot rule DP001, which were chosen after
  looking at misses on this same set; 7/13 before), no false positives on the clean cases. In
  label-blind runs the local model `qwen2.5-coder:3b` found **0/13** on its own in all 6 runs, and
  combined runs matched analyzer-only results. Claude was not run. Full report and caveats:
  [docs/evaluation.md](docs/evaluation.md).

## Known limitations

- **The local model finds little.** `qwen2.5-coder:3b` often returns no findings, even when it is
  shown the code an analyzer flagged; a larger model may do better but has not been measured.
  "No findings" never means the code was proven defect-free, and the review page says so.
- **Context coverage.** The LLM sees what fits the context budget: whole files first, then
  line-numbered excerpts of larger files (around analyzer findings and the start of the file).
  Code outside those excerpts is not reviewed by the model; the review page reports the coverage.
- **Analyzer labels are conservative.** Only Ruff rules listed as likely defects are labeled
  `bug`; any other Ruff rule is labeled `maintainability`, which can under-state an occasional
  real defect. Static analysis covers Python only; other languages are indexed and searchable,
  and only the LLM reviews them.
- **Test suggestions are mostly test gaps.** Complete tests are generated only from docstring
  examples or by the model; DevPilot cannot infer expected results, and it never runs tests.
- **Pull requests:** files whose diff GitHub omits (very large changes) cannot be scoped to changed
  lines, and only the first 300 files of a pull request are read; both are reported on the review.
- The benchmark is small and synthetic, and two analyzer rules were tuned on it.
- Search and Q&A retrieval are lexical (keywords, `LIKE`), fine for small repositories, not for
  very large ones.
- Single worker by default; repository import and indexing run inside the HTTP request.

More: [docs/security.md](docs/security.md) (remaining risks) and [docs/feature-status.md](docs/feature-status.md).

## Documentation

| Document | Contents |
|---|---|
| [architecture.md](docs/architecture.md) | Components, request lifecycles, jobs, failure handling, trade-offs |
| [implementation-guide.md](docs/implementation-guide.md) | Module-by-module walkthrough of the actual code |
| [ai-review-pipeline.md](docs/ai-review-pipeline.md) | Context assembly, prompts, schema, validation, dedupe |
| [database.md](docs/database.md) | ER diagram, tables, constraints, retention |
| [backup-restore.md](docs/backup-restore.md) | Backing up PostgreSQL and snapshots, restore drill, recovery |
| [api-reference.md](docs/api-reference.md) | Every endpoint with examples and errors |
| [security.md](docs/security.md) | Threat model, trust boundaries, controls, open risks |
| [testing.md](docs/testing.md) | Test suites, what they verify, gaps, results |
| [evaluation.md](docs/evaluation.md) | Benchmark method, metrics, results, limitations |
| [evaluation/README.md](evaluation/README.md) | How evaluation artifacts are generated, tracked and reproduced |
| [decisions/](docs/decisions/) | Architecture decision records |
| [development-log.md](docs/development-log.md) | Milestones, bugs found, fixes |
| [feature-status.md](docs/feature-status.md) | Verified / partly verified / not implemented |
| [interview-guide.md](docs/interview-guide.md) | Learning and handover package |
| [walkthrough.md](docs/walkthrough.md) | Beginner-friendly tour of the ten main workflows |
| [audit-report.md](docs/audit-report.md) | Post-build audit: defects found and fixed |
| [verification-report.md](docs/verification-report.md) | Commands run and their actual results |
| [handover.md](docs/handover.md) | Final handover summary |
| [demo.md](docs/demo.md) | Reproducible demo script |

## Third-party software

Ruff (MIT), Bandit (Apache-2.0), FastAPI (MIT), SQLAlchemy (MIT), Alembic (MIT), Pydantic (MIT),
argon2-cffi (MIT), cryptography (Apache-2.0/BSD), httpx (BSD), Anthropic Python SDK (MIT), React
(MIT), TanStack Query (MIT), React Router (MIT), Tailwind CSS (MIT), Vite (MIT), Vitest (MIT),
Playwright (Apache-2.0). With the `anthropic` provider, LLM review calls Anthropic's hosted API and its terms and
data policies apply. With `ollama`, the model runs locally through Ollama (MIT); model licenses vary (Qwen2.5-Coder 3B is
released under its own Qwen license, check it before redistributing).
