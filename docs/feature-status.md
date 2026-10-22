# Feature status

Updated 2026-10-17 (after the post-build audit, see [audit-report.md](audit-report.md)). "Verified" means exercised by an automated test that passed and/or checked by
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
| Deterministic test-suggestion skeletons | `test_static_test_suggestions_cover_untested_changed_functions`; manual |
| LLM opt-in per repository, enforced in API and worker | `test_ai_review_requires_consent` |
| Model output validation (schema, path, lines, evidence) and dedupe | unit + API tests with replayed responses |
| App remains usable without an LLM key (skipped, analyzers still run) | `test_ai_unconfigured_is_skipped_not_failed`, manual |
| Prompt fencing / tag neutralization | `test_context_neutralizes_tag_injection_and_marks_changed_lines` |
| Log redaction | `test_log_redaction_removes_tokens` |
| Repository delete with cascade and snapshot removal | `test_delete_repository_cascades` |
| Alembic migration (SQLite) | runs at the start of every test session |
| Evaluation harness, analyzer-only baseline | real runs; reports in `evaluation/reports/` |
| Light/dark theme | manual |

## Implemented but incompletely verified

| Feature | What's missing |
|---|---|
| LLM review with Ollama (`OllamaProvider`) | Runs end to end with `qwen2.5-coder:3b` (valid, citation-checked output). In the corrected label-blind benchmark it found 0/13 seeded defects alone and added nothing over the analyzers (3 runs per configuration). Larger local models untested. |
| LLM review with Anthropic (`AnthropicProvider`) | Only mocked/replayed responses. Never called the real API (no key). Prompt quality, token use, cost and the schema's acceptance by the API are unmeasured. |
| `ai` and `combined` evaluation configurations | Implemented; not run (no key). |
| GitHub OAuth connect | State validation tested; full redirect/exchange never run against github.com (no OAuth app configured). |
| GitHub repo import, PR list/detail, PR review | Tested with a mocked HTTP transport only. |
| PostgreSQL support and multi-worker `SKIP LOCKED` claiming | Code path exists; never run against PostgreSQL. |
| Docker images and docker-compose stack | `docker compose config` validates; images not built (Docker daemon not running). The audit fixed three compose defects (data directory, proxy client IP, Host header) that are therefore also unverified at runtime. |
| CI workflow | Written; not run (repository not on GitHub yet). |
| Retention cleanup command | Written; not covered by a test. |
| Login/register throttling | Implemented; not directly tested. |
| Standalone worker process (`python -m app.workers.queue`) | Same loop as the tested in-process worker; the entry point itself not run. |

## Planned or not implemented

- Static analyzers for languages other than Python (files are indexed and searchable only).
- Tree-sitter parsing; semantic/embedding search.
- Real-world (non-synthetic) benchmark cases; multiple runs per case for LLM variance.
- Posting review comments back to GitHub PRs; webhooks.
- Email verification, password reset, MFA, account lockout.
- Organizations/teams, billing.
- Sandboxed execution of suggested tests (deliberately not done).
- OpenTelemetry tracing (structured JSON logs with request IDs exist; no traces/metrics export).
- Background (async) indexing for large repositories.
- Security headers (CSP etc.) in nginx.
- Prompt caching and refusal fallback for the Anthropic provider.
