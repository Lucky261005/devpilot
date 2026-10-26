# Feature status

Updated 2026-10-17 (after the post-build audit, see [audit-report.md](audit-report.md)); Phase 4 security rows added 2026-10-24. "Verified" means exercised by an automated test that passed and/or checked by
hand in the running app, as noted.

## Implemented and verified

| Feature | Evidence |
|---|---|
| Registration, login, logout, session cookie flags, expiry handling | `test_auth_flow_and_session_cookie`, e2e register; manual in browser |
| Per-user isolation (404 for others' resources) | `test_other_users_cannot_see_or_touch_repository` |
| CSRF header requirement, request size limit | `test_csrf_header_required_for_mutations`, `test_oversized_request_rejected` |
| ZIP import with traversal/symlink/zip-bomb/size checks | `test_ingestion.py`, e2e upload |
| Local Git import under allowed roots, `git archive` export | `test_local_diff_review_reports_only_changed_lines`; manual in browser |
| Secret, binary, oversized file exclusion | `test_discovery_deletes_secrets_and_skips_binary` |
| Chunking with exact line provenance; text and definition search | `test_units.py`, `test_import_index_search_and_file_view`, e2e search |
| Ruff and Bandit findings, normalized with rule ID, version, evidence, docs link; DevPilot rule DP001 (`ast_rules.py`) and Ruff SIM115 | `test_full_review_static_only`, e2e; `test_ast_rules.py`; label-blind benchmark 9/13 |
| Whole-repo and `base..head` reviews; changed-line filtering | API tests; manual in browser |
| Background worker, stages, failure recording, stale-job recovery | `test_worker_recovers_stale_and_records_internal_errors`, `test_bad_ref_fails_job_with_clear_error` |
| Review dashboard: status polling, run summary, severity/category/source filters, source view with highlighted lines, diff view, test suggestions, history | e2e test; `ui.test.tsx`; manual in browser |
| Finding feedback (4 verdicts), stored with analyzer version, re-rating | `test_full_review_with_ai_validates_and_dedupes`, e2e |
| Deterministic test suggestions: test gaps, or complete tests from docstring examples | `test_test_suggestions.py`, `test_static_test_suggestions_cover_untested_changed_functions`; manual (live review 2026-10-26) |
| LLM opt-in per repository, enforced in API and worker | `test_ai_review_requires_consent` |
| Model output validation (schema, path, lines, evidence) and dedupe | unit + API tests with replayed responses |
| App remains usable without an LLM key (skipped, analyzers still run) | `test_ai_unconfigured_is_skipped_not_failed`, manual |
| Prompt fencing / tag neutralization | `test_context_neutralizes_tag_injection_and_marks_changed_lines` |
| Log redaction | `test_log_redaction_removes_tokens` |
| Repository delete with cascade and snapshot removal | `test_delete_repository_cascades` |
| Alembic migration (SQLite) | runs at the start of every test session |
| Evaluation harness, analyzer-only baseline | real runs; reports in `evaluation/reports/` |
| Light/dark theme | manual |
| Registration modes `open` / `invite` / `closed`, generic duplicate-email answer | `test_registration.py`, `LoginPage.test.tsx` |
| Operator account creation (`python -m app.cli create-user`) | `test_cli_create_user.py`; run as a process against a throwaway SQLite database |
| Secure cookies required outside development; Compose settings consistent with it | `test_cookie_security.py` |
| Sign-in throttling: 10/min per IP (database), 5 failures per 15 min per account | `test_login_throttle.py`, `test_ip_rate_limit.py`, `test_proxy_trust.py` |
| Repository import quota: 20 per user per rolling hour (database, survives restarts) | `test_import_quota.py` |
| Per-user review quota: `DEVPILOT_REVIEWS_PER_HOUR` (30) per rolling hour (database), independent of the installation cap | `test_review_quota.py` |
| Repository Q&A (Ask tab): keyword retrieval from the repository's own index (with light stemming and a small synonym map, e.g. authentication → auth/login/session), answer with citations checked against the code shown to the model, honest status when there are no matches, AI is off, no provider is configured or the provider fails | `test_repo_qa.py` (fake model), `test_repo_qa_retrieval.py`, `AskRepository.test.tsx`; checked in a browser on 2026-10-25 (statuses, loading state, citation highlighting, phone width) with one live answer from local Ollama `qwen2.5-coder:3b` |
| Installation-wide review cap (60 per hour) next to the per-user quota | `test_global_review_cap.py` (concurrency on SQLite) |
| Worker cleanup of expired sessions and sign-in attempt records | `test_session_cleanup.py`, `test_login_attempt_cleanup.py` |
| GitHub disconnect: local tokens deleted first, then grant revocation reported honestly | `test_github_disconnect.py` (mocked GitHub) |
| Security headers on API responses; API docs hidden outside development | `test_security_headers.py`; web-app CSP checked in a browser on the production sign-in page |

## Implemented but incompletely verified

| Feature | What's missing |
|---|---|
| LLM review with Ollama (`OllamaProvider`) | Runs end to end with `qwen2.5-coder:3b` (valid, citation-checked output). In the corrected label-blind benchmark it found 0/13 seeded defects alone and added nothing over the analyzers (3 runs per configuration). Larger local models untested. |
| LLM review with Anthropic (`AnthropicProvider`) | Only mocked/replayed responses. Never called the real API (no key). Prompt quality, token use, cost and the schema's acceptance by the API are unmeasured. |
| `ai` and `combined` evaluation configurations | Implemented; not run (no key). |
| GitHub App connect, repository listing, branch listing, commit-pinned import | Verified once against real GitHub on 2026-10-23 (App `devpilot-lucky-local`, record in the local `docs/github-app.md`); automated tests use a mocked transport. Token renewal after expiry not yet seen live. |
| GitHub PR list/detail and PR review | Verified once against a real PR on 2026-10-25: `Lucky261005/pitwall` #1 (temporary, closed unmerged), review pinned to head `0d002ab` with base `0f72b54`, both matching GitHub; findings limited to the changed file (ruff F401 at `lap_stats.py:3`), 2 test suggestions; LLM stage (local `qwen2.5-coder:3b`) completed but missed the seeded divide-by-zero. Automated coverage: `test_github_import_pulls_and_pr_review` (mocked). |
| PostgreSQL support and multi-worker `SKIP LOCKED` claiming | Code path exists; never run against PostgreSQL. |
| Docker images and docker-compose stack | `docker compose config` validates and `nginx -t` passes on the real `nginx.conf` (with the upstream name mapped); the stack has been started on a disposable setup for the backup, restore and recovery drill (2026-10-25), including a fresh-database start (`test_services_start_in_order_on_a_fresh_database` covers the start order). Unverified at runtime: loopback-only publishing, nginx trusting `X-Forwarded-For` only from the Docker gateway, live headers, `create-user` against PostgreSQL, worker cleanup in its container. |
| HTTPS reverse proxy in front of the Compose stack | Documented in [security.md](security.md); not configured or run. nginx does not forward `X-Forwarded-Proto`, so GitHub callbacks behind such a proxy are unverified. |
| GitHub authorization revocation on disconnect | Implemented against GitHub's documented endpoint; tested only with a mocked transport. |
| CI workflow | Passed on GitHub Actions for the last pushed commit (`4028ca0`, 2026-10-23). Later work is uncommitted and has not been through CI. |
| Retention cleanup command | Session and sign-in-record parts tested; old review-snapshot removal not covered by a test. |
| Standalone worker process (`python -m app.workers.queue`) | Same loop as the tested in-process worker; the entry point itself not run. |

### Repository Q&A limitations
- Retrieval is keyword-based (stemming plus a short synonym list), not semantic: questions must use
  words that appear in the code, files or names.
- Excerpts are index chunks: a constant or import just above the matched lines may be missing, and
  the model then says it is "not defined" (seen in the live check).
- The answer is generated inside the request (up to `DEVPILOT_LLM_TIMEOUT_S`); a small local model took
  about a minute. No streaming, no saved history, no follow-up questions.
- Not yet run against the Anthropic API.

## Planned or not implemented

- Static analyzers for languages other than Python (files are indexed and searchable only).
- Tree-sitter parsing; semantic/embedding search.
- Real-world (non-synthetic) benchmark cases; multiple runs per case for LLM variance.
- Posting review comments back to GitHub PRs; webhooks.
- Email verification, password reset, MFA. (A temporary per-account sign-in throttle exists; there is
  no permanent lockout.)
- Organizations/teams, billing.
- Sandboxed execution of suggested tests (deliberately not done).
- OpenTelemetry tracing (structured JSON logs with request IDs exist; no traces/metrics export).
- Background (async) indexing for large repositories.
- Prompt caching and refusal fallback for the Anthropic provider.
