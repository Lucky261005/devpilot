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
- Import a repository from a **ZIP upload**, a **local Git path** (inside admin-approved
  directories), or **GitHub** (OAuth, default branch).
- Safe ingestion: traversal/symlink/zip-bomb checks, size limits, binary and secret-file exclusion.
- Code search by text or definition name, with file/line results and a source viewer.
- Reviews of a whole snapshot, a local `base..head` range, or a GitHub pull request; run by a
  background worker with queued → running → completed/failed states.
- Ruff + Bandit findings normalized into one format with rule IDs, versions, evidence and docs links.
- Optional LLM review with structured output, through either Anthropic Claude (paid API) or a
  local model served by Ollama (free, code stays on the machine), with citation validation,
  deduplication against analyzer findings, token/latency accounting and a per-repository opt-in.
- Test suggestions: deterministic pytest skeletons for changed functions no test references, plus
  model-written tests when the LLM review runs. Shown for copying, never executed.
- Feedback on each finding (useful / incorrect / duplicate / not actionable), stored with the
  analyzer or model version.
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

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22, Git.

```bash
cd backend
cp ../.env.example .env          # then edit; see "Configuration"
uv sync
uv run alembic upgrade head      # creates the SQLite database
uv run uvicorn app.main:app --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173, proxies /api to :8000
```

Register an account in the UI. To try it without your own code, build the sample repository
(synthetic, with seeded defects) and import it through **Local Git path**:

```bash
python scripts/make_demo_repo.py ../devpilot-demo-repo
```

For that, `DEVPILOT_ALLOWED_LOCAL_ROOTS` must include the parent directory. A step-by-step demo is
in [docs/demo.md](docs/demo.md).

## Getting started (Docker Compose)

```bash
cp .env.example .env    # set DEVPILOT_SECRET_KEY (required in this mode)
docker compose up --build
# UI on http://localhost:8080
```

Compose runs PostgreSQL, the API, a separate worker process and nginx serving the built UI.
The compose file validates with `docker compose config`, but the stack has not yet been run end to
end (see [docs/feature-status.md](docs/feature-status.md)).

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
| `DEVPILOT_GITHUB_CLIENT_ID` / `_SECRET` | empty | GitHub OAuth app; callback is the UI address + `/api/github/oauth/callback` (dev: `http://localhost:5173/...`). |
| `DEVPILOT_GITHUB_OAUTH_SCOPES` | empty | Empty = public repos, read-only. `repo` for private repos. |
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
| Retention cleanup | `cd backend && uv run python -m app.cli cleanup` |
| New migration | `cd backend && uv run alembic revision --autogenerate -m "..."` |

## Test and evaluation results

Measured on 2026-10-17, Windows 11, Python 3.12.2 / Node 22.14:

- Backend: **77 passed** (2 live-model tests, Anthropic and Ollama, deselected by default). Ruff, ruff format, mypy, Bandit: clean.
- Frontend: **7 passed** (Vitest). ESLint: 0 errors, 5 fast-refresh warnings. Production build succeeds.
- End-to-end (Playwright, Chromium): **2 passed**.
- Dependency audit: pip-audit and `npm audit` report no known vulnerabilities.
- Evaluation, 17 synthetic cases, analyzer-only configuration: precision 1.0, recall 0.692
  (9 of 13 seeded defects, after adding Ruff SIM115 and DevPilot rule DP001; 7 of 13 before), 0 of 4 clean cases with false positives. In label-blind runs (after fixing a
  benchmark flaw that leaked case names into prompts), the local model `qwen2.5-coder:3b` found
  **0/13** on its own and added nothing over the analyzers when combined (7/13), in 3 of 3 runs per
  configuration. Claude was not run (zero budget). Full report and caveats:
  [docs/evaluation.md](docs/evaluation.md).

## Known limitations

- Static analysis covers Python only. Other languages are indexed and searchable, and the LLM can
  review them, but no analyzer runs on them.
- The LLM path is tested against recorded/mocked responses only. Neither the Anthropic API nor a
  real Ollama model has been run in this environment yet.
- GitHub integration is tested with a mocked HTTP transport; it has not been run against github.com.
- The benchmark is small and entirely synthetic, and one analyzer setting was tuned on it.
- Search is lexical (`LIKE`), fine for small repositories, not for very large ones.
- Single worker by default; repository import and indexing run inside the HTTP request.

More: [docs/security.md](docs/security.md) (remaining risks) and [docs/feature-status.md](docs/feature-status.md).

## Documentation

| Document | Contents |
|---|---|
| [architecture.md](docs/architecture.md) | Components, request lifecycles, jobs, failure handling, trade-offs |
| [implementation-guide.md](docs/implementation-guide.md) | Module-by-module walkthrough of the actual code |
| [ai-review-pipeline.md](docs/ai-review-pipeline.md) | Context assembly, prompts, schema, validation, dedupe |
| [database.md](docs/database.md) | ER diagram, tables, constraints, retention |
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
