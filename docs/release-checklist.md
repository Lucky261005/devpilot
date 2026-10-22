# Release checklist

Status as of 2026-10-17. ✅ done and verified · ⬜ not done.

## Code quality
- ✅ Backend tests pass (`uv run pytest`: 65 passed)
- ✅ Ruff, ruff format, mypy, Bandit clean
- ✅ Frontend unit tests, typecheck, ESLint (0 errors), Prettier, production build
- ✅ Playwright end-to-end tests pass locally
- ⬜ CI green on GitHub (workflow written; repository not pushed yet)

## Functionality
- ✅ Import (ZIP, local Git) → index → search → review → findings → feedback, checked in the browser
- ⬜ LLM review run against the real Anthropic API (`pytest -m live_llm`, then a manual review)
- ⬜ GitHub OAuth + PR review against github.com with a real OAuth app
- ⬜ Docker compose stack built and run; review completed on PostgreSQL with the standalone worker

## Security
- ✅ Dependency audits clean (pip-audit, npm audit)
- ✅ No secrets tracked (`.env`, databases and data directories are git-ignored)
- ⬜ `DEVPILOT_SECRET_KEY` generated and stored for the deployment
- ⬜ `DEVPILOT_COOKIE_SECURE=true` behind HTTPS
- ⬜ Security headers (CSP, HSTS) added at the proxy
- ⬜ Retention `cleanup` scheduled

## Evaluation and docs
- ✅ Static-only benchmark run and reported
- ⬜ `ai` and `combined` configurations run, with cost recorded
- ✅ README, architecture, implementation guide, API, database, security, testing, evaluation, ADRs, feature status, development log, interview guide, demo script
