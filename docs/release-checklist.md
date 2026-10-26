# Release checklist

Status as of 2026-10-26, for publishing the repository as a portfolio project. ✅ done and verified,
with the evidence named · ⬜ not done.

## Release blockers (portfolio publication)

- ✅ Full local suites on the working tree, 2026-10-26: backend 310 passed (4 deselected), ruff,
  mypy, Bandit clean; frontend 41 passed, ESLint 0 errors, Prettier, type check and build clean;
  Playwright 2 passed. Recorded in [verification-report.md](verification-report.md).
- ⬜ Commit the work and get CI green on GitHub. The last pushed commit (`4028ca0`) passed CI;
  everything since is uncommitted. `docs/current-state-audit.md` and `docs/github-app.md` have
  local edits that are meant to stay out of the commit.
- ⬜ Add [testing.md](testing.md) rows for the test files added since 2026-10-17 (rate limits,
  Q&A, recent reviews, context excerpts, Ruff classification, test suggestions, PR review scope).
- ⬜ README screenshots or a short demo recording, taken from a throwaway instance with sample data.

## Supported setup path

- ✅ Local, no Docker, Windows PowerShell: README "Getting started". Commands checked against the
  source on 2026-10-26 (`.env` read from `backend`, CLI `create-user`/`cleanup`, standalone worker,
  `make_demo_repo.py <target-dir>`, Ollama settings). A clean-machine install from the README has
  not been repeated since 2026-10-17.
- ✅ Docker Compose started on a disposable setup for the backup, restore and recovery drill
  (2026-10-25); fresh-database start order covered by `test_services_start_in_order_on_a_fresh_database`.

## Core workflows

- ✅ Import (ZIP, local Git, GitHub) → index → search → review → findings → feedback, in the browser.
- ✅ Whole-repository review with the local model, `qwen2.5-coder:3b` (2026-10-26): an oversized
  file was sent as an excerpt (31 418 prompt characters, 2 of 4 files, 1 partial) instead of being
  dropped; the model still returned no findings; B905 labeled maintainability/low; test
  suggestions were test gaps.
- ✅ Repository Q&A with one live local-model answer, citations opening the code viewer (2026-10-25).
- ✅ Pull-request review against a real GitHub pull request (`pitwall` #1, 2026-10-25). The later
  head re-check, patchless-file and truncation records are covered by mocked tests only
  (`test_pr_review.py`).
- ⬜ LLM review against the Anthropic API (`pytest -m live_llm`, then a manual review); no budget.

## Evidence quality

- ✅ Evaluation: 17 synthetic cases, analyzer-only recall 9/13 with two rules tuned on the set;
  local model 0/13 label-blind. Limits stated in [evaluation.md](evaluation.md).
- ⬜ (optional) Recall on defects the rules were not tuned on; a model larger than 3B.

## Security and hygiene

- ✅ Dependency audits clean in CI (pip-audit, `npm audit`) as of the last pushed commit.
- ✅ No secrets, local databases, data directories or machine-specific paths in tracked or untracked
  files (pattern scan of names and contents, 2026-10-26); `.env`, `*.db`, `backend/data/`,
  `CONTEXT.md` and `.claude/` are ignored.
- ✅ Startup refuses production settings without a secret key or with `DEVPILOT_COOKIE_SECURE=false`
  (`test_cookie_security.py`).
- ✅ Registration policy, sign-in throttles (per account and per IP), import and review quotas,
  installation-wide review cap, forwarded-IP trust limited to nginx, security headers, API docs
  hidden outside development (automated tests; see [security.md](security.md)).
- ✅ User isolation: another user gets 404 for repositories, pull requests, reviews and their
  findings (`test_pr_review.py`, `test_recent_reviews.py`, existing API tests).
- ✅ Backup and restore documented ([backup-restore.md](backup-restore.md)); drilled once on a
  disposable Compose stack (2026-10-25).

## Deployment (only if you host it; not needed for the portfolio)

- ⬜ `DEVPILOT_SECRET_KEY` generated and stored in a password manager, apart from the backups.
- ⬜ First account created with `python -m app.cli create-user`; registration `invite` or `closed`.
- ⬜ HTTPS reverse proxy in front of `127.0.0.1:8080`, `DEVPILOT_PUBLIC_ORIGIN` set; then
  `DEVPILOT_HSTS_SECONDS`.
- ⬜ Runtime check of loopback binding, client-IP trust and live headers behind the proxy.
- ⬜ Snapshot retention `cleanup` and backups scheduled on the host, with a restore drill from the
  deployment's own backup.
