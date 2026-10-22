# Security model

## Assets

User accounts and sessions; GitHub access tokens; private source code in snapshots; the LLM API
key; review results (which can describe vulnerabilities in a user's code).

## Trust boundaries

```
 Browser ──(1)──▶ API ──(2)──▶ DB / snapshot dir
                   │
                   ├──(3)── repository content (ZIP, local Git, GitHub)  ← untrusted
                   ├──(4)──▶ git, Ruff, Bandit subprocesses
                   ├──(5)──▶ GitHub API
                   └──(6)──▶ LLM provider  ◀── model output is untrusted
```

1. Every request is unauthenticated until the session cookie is validated.
2. Server-side storage is trusted; secrets in it are encrypted or hashed.
3. **Repository content is hostile input**: archive structure, file names, file contents, Git
   config and hooks, and text aimed at the model.
4. Subprocesses receive argument lists (never a shell) and run with timeouts.
5. GitHub responses are trusted for metadata but downloads are size-limited and re-validated by
   the same ZIP checks as uploads.
6. Model output is treated as untrusted data and validated before storage.

## Threats and controls

| Threat | Control | Code | Test |
|---|---|---|---|
| Path traversal / absolute paths in ZIP (`../`, `C:/`, `/etc`, `a:b` streams) | `_safe_member_path` rejects; final resolved path must stay under destination | `ingestion.safe_extract_zip` | `test_rejects_traversal_and_absolute_paths` |
| Symlinks in ZIP | Rejected by mode bits; discovery also deletes symlinks | same | `test_rejects_symlinks` |
| Zip bombs / huge repos | Declared-size and file-count limits, plus counting actual decompressed bytes while writing | same | `test_enforces_size_and_count_limits` |
| Malformed archives | `BadZipFile` → user-safe error, repository marked failed | same | `test_rejects_non_zip`, `test_malformed_archive_is_recorded_as_failed` |
| Reading arbitrary server paths (local import) | Disabled unless `DEVPILOT_ALLOWED_LOCAL_ROOTS`; resolved path must be under a root and be a Git repo | `validate_local_path` | `test_local_path_must_be_under_allowed_root` |
| Malicious Git config/hooks executing | Only `git archive`, `rev-parse`, `diff`; `core.hooksPath=/dev/null`, `core.fsmonitor=false`, `diff.external=` empty, `--no-ext-diff --no-textconv`; tracked files only | `ingestion._git` | `test_export_and_diff_local_repo` |
| Option injection via refs (`--upload-pack=...`) | Ref regex, no leading `-`, `--end-of-options` | `resolve_ref` | `test_rejects_option_like_or_shell_refs`, `test_bad_ref_fails_job_with_clear_error` |
| SSRF via repository URLs | Users never supply URLs: only `owner/name` (validated) placed into fixed API paths; redirects followed only to `api.github.com`/`codeload.github.com`/`github.com` over HTTPS | `integrations/github.py` | `test_github_errors_and_input_validation` |
| Executing repository code | Nothing is imported or run; analyzers parse files. Test suggestions are displayed, never executed. | — | — |
| Secrets in imported repos | `.env*`, keys, `credentials*`, `.npmrc`, etc. deleted from the snapshot before indexing, analysis or LLM context | `discover_files` | `test_discovery_deletes_secrets_and_skips_binary` |
| Reading files outside a snapshot via the file API | Resolve + `is_relative_to(snapshot)` | `read_snapshot_file` | `test_import_index_search_and_file_view` |
| Unauthorized access to other users' data | `owned_repo` / `owned_review` on every route; 404 for foreign IDs | `api/deps.py` | `test_other_users_cannot_see_or_touch_repository` |
| CSRF | SameSite=Lax cookie + required custom header on unsafe methods | `main.guard` | `test_csrf_header_required_for_mutations` |
| Session theft impact | httpOnly cookie, only SHA-256 of token stored, 7-day expiry, logout deletes the row | `auth.py` | `test_auth_flow_and_session_cookie` |
| Password storage | argon2id (argon2-cffi defaults); 10-char minimum; uniform timing for unknown emails | `security.py`, `auth.py` | `test_short_password_and_bad_email_rejected` |
| Brute force | 10 login/register attempts per minute per IP (behind nginx the real IP comes from `X-Forwarded-For` via uvicorn `--proxy-headers`) | `auth._throttle` | — (limiter covered via review limit test) |
| Expensive-operation abuse | 20 imports/hour, `DEVPILOT_REVIEWS_PER_HOUR` reviews/hour per user | `ratelimit.py` | `test_review_rate_limit` |
| Oversized requests | `Content-Length` cap in middleware; multipart uploads without `Content-Length` (chunked) rejected with 411; streaming upload cap | `main.guard`, `import_archive` | `test_oversized_request_rejected`, `test_chunked_upload_without_length_rejected` |
| GitHub token leakage | Fernet-encrypted at rest; never returned by the API; least-privilege scope by default (none = public read) | `security.encrypt_secret` | `test_github_import_pulls_and_pr_review` (round trip) |
| OAuth CSRF / code injection | Random state bound to the user ID in an httpOnly cookie, compared in constant time | `api/github.py` | `test_oauth_state_is_validated` |
| Secrets in logs | Log formatter redacts `sk-ant-…`, `gh*_…` tokens and `password/token/secret/api_key=` values | `core/logging.py` | `test_log_redaction_removes_tokens` |
| Internal details in errors | Generic 500 body with request ID; job errors name the stage only | `main.unhandled`, `queue.process_job` | `test_worker_recovers_stale_and_records_internal_errors` |
| Prompt injection from repository content | Content fenced in `<repository_content>`, tag-breaking neutralized, system prompt marks it untrusted, model has no tools | `ai/context.py` | `test_context_neutralizes_tag_injection_and_marks_changed_lines` |
| Hallucinated / malicious model output | Pydantic schema; path, line range, context and evidence checks; analyzer findings never pass through the model | `services/findings.py` | `test_validation_accepts_grounded_and_rejects_hallucinated`, `test_full_review_with_ai_validates_and_dedupes` |
| Sending private code to a third party without consent | Per-repository opt-in (audited); the UI states what is sent and to whom; nothing sent if no key | `api/reviews.py`, `services/review.py` | `test_ai_review_requires_consent` |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI | `.github/workflows/ci.yml` | ran locally 2026-10-17: none found |

## Known gaps and remaining risks

- **Analyzer parsers are attack surface.** Ruff and Bandit parse hostile files. They run with
  timeouts but without OS-level sandboxing (no container, seccomp or resource limits per run).
- **Git is attack surface.** `git archive` / `git diff` on an admin-allowed directory; repository
  config other than the overridden keys still applies. Local import is meant for trusted
  self-hosted use and is off by default.
- **GitHub zipballs are read into memory** before the size check (`download_zipball`).
- **Rate limits are in-memory** and per process; they reset on restart and don't coordinate
  across replicas.
- **No account lockout, email verification or password reset.** No MFA.
- **Development encryption key.** If `DEVPILOT_SECRET_KEY` is empty in development, a fixed
  key is derived from a constant. Production mode refuses to start without a key. Rotating the key
  makes stored GitHub tokens unreadable (users must reconnect).
- **Prompt injection that suppresses findings** cannot be detected (see ai-review-pipeline.md).
- **No CSP header** is set by the API; nginx config does not add security headers yet.
- **Snapshot isolation is per directory**, not per OS user. Anyone with server file access can
  read all snapshots.
- **LLM provider retention** is governed by the provider's policy, not DevPilot.
- The PostgreSQL deployment path and the Docker images have not been run.
