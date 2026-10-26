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
| Session theft impact | httpOnly, SameSite=Lax cookie; only SHA-256 of token stored; 7-day expiry; logout deletes the row; `Secure` flag required outside development (the API and worker refuse to start if `DEVPILOT_COOKIE_SECURE` is not true; Compose sets it) | `auth.py`, `config.check_environment` | `test_auth_flow_and_session_cookie`, `test_cookie_security.py` |
| Public sign-up abuse | `DEVPILOT_REGISTRATION`: `open` (development default), `invite` (default elsewhere; code compared in constant time; an empty or unset code admits nobody) or `closed`. Existing accounts can always sign in. The operator creates accounts on the server with `python -m app.cli create-user` (no HTTP route) | `auth.register`, `cli.create_user` | `test_registration.py`, `test_cli_create_user.py` |
| Account discovery through sign-up | Registration answers `202` with the same message for new and already-registered emails and starts no session | `auth.register` | `test_duplicate_email_gets_the_same_answer_as_a_new_one` |
| Password storage | argon2id (argon2-cffi defaults); 10-char minimum; uniform timing for unknown emails | `security.py`, `auth.py` | `test_short_password_and_bad_email_rejected` |
| Brute force | Per IP: 10 accepted login and 10 accepted register requests per rolling minute, stored in the database as a keyed hash of the address (never the address) and shared by all API processes; refused requests use no slot. Per account: 5 failed sign-ins per rolling 15 minutes, then `429` until the oldest failure leaves the window; stored in the database as a keyed hash of the normalized email (never the email), applied to unknown emails too so the answer does not reveal accounts; a successful sign-in clears earlier failures | `auth._throttle`, `auth._reserve_login_attempt` | `test_login_throttle.py`, `test_ip_rate_limit.py` |
| Spoofed client IP (to dodge per-IP limits) | Uvicorn honours `X-Forwarded-For` only from nginx's address (`FORWARDED_ALLOW_IPS`, set in Compose; never `*`). nginx takes the client IP from `X-Forwarded-For` only on connections from the Docker gateway (`set_real_ip_from 172.30.0.1`, `real_ip_recursive off`) | `backend/Dockerfile`, `docker-compose.yml`, `frontend/nginx.conf` | `test_proxy_trust.py` |
| Expensive-operation abuse | Per user: 20 repository imports per rolling hour (database, shared by all API processes; an admitted import counts even if it then fails, a refused one uses no slot) and `DEVPILOT_REVIEWS_PER_HOUR` (30) reviews per rolling hour (database, shared by all API processes; a review refused by the installation cap gives the user's slot back). Whole installation (database): `DEVPILOT_REVIEWS_GLOBAL_PER_HOUR` (60) new reviews per rolling hour across all users and processes, `429` with `Retry-After`; deleting repositories does not free capacity | `repositories._check_quota`, `reviews._admit_user_review`, `reviews._admit_review` | `test_import_quota.py`, `test_review_quota.py`, `test_global_review_cap.py` |
| Oversized requests | `Content-Length` cap in middleware; multipart uploads without `Content-Length` (chunked) rejected with 411; streaming upload cap | `main.guard`, `import_archive` | `test_oversized_request_rejected`, `test_chunked_upload_without_length_rejected` |
| GitHub token leakage | Fernet-encrypted at rest; never returned by the API. User tokens come from a GitHub App and reach only repositories the user can see that the App is installed on; the App's permissions are set in its GitHub settings, not by DevPilot (recommended read-only Contents, Metadata, Pull requests, see [github-app.md](github-app.md)); DevPilot itself only reads repositories (GET requests) and refuses imports outside the user's installation grants | `security.encrypt_secret` | `test_github_import_pulls_and_pr_review` (round trip) |
| Stale GitHub access after disconnect | Disconnect deletes DevPilot's stored access and refresh tokens first, then asks GitHub to revoke the App authorization (`DELETE /applications/{client_id}/grant`). The response says whether GitHub confirmed it (204) and otherwise links to GitHub's settings | `github_tokens.disconnect`, `github.revoke_grant` | `test_github_disconnect.py` |
| OAuth CSRF / code injection | Random state bound to the user ID in an httpOnly cookie, compared in constant time | `api/github.py` | `test_oauth_state_is_validated` |
| Secrets in logs | Log formatter redacts `sk-ant-…`, `gh*_…` tokens and `password/token/secret/api_key=` values | `core/logging.py` | `test_log_redaction_removes_tokens` |
| Internal details in errors | Generic 500 body with request ID; job errors name the stage only | `main.unhandled`, `queue.process_job` | `test_worker_recovers_stale_and_records_internal_errors` |
| Prompt injection from repository content | Content fenced in `<repository_content>`, tag-breaking neutralized, system prompt marks it untrusted, model has no tools | `ai/context.py` | `test_context_neutralizes_tag_injection_and_marks_changed_lines` |
| Hallucinated / malicious model output | Pydantic schema; path, line range, context and evidence checks; analyzer findings never pass through the model | `services/findings.py` | `test_validation_accepts_grounded_and_rejects_hallucinated`, `test_full_review_with_ai_validates_and_dedupes` |
| Sending private code to a third party without consent | Per-repository opt-in (audited); the UI states what is sent and to whom; nothing sent if no key | `api/reviews.py`, `services/review.py` | `test_ai_review_requires_consent` |
| Clickjacking, content sniffing, script injection in the web app | API responses: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; …`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` (also on early rejections). Web app (nginx): CSP allowing only same-origin scripts, styles and connections, plus inline style attributes for the prerendered page; `frame-ancestors 'none'` | `main._security_headers`, `frontend/nginx.conf` | `test_security_headers.py` |
| API surface disclosure | `/docs`, `/redoc` and `/openapi.json` return 404 outside development | `main.guard` | `test_production_hides_docs_and_schema` |
| Downgrade to HTTP | `Strict-Transport-Security` is opt-in: sent on API responses only outside development and only when `DEVPILOT_HSTS_SECONDS` > 0 | `main._security_headers` | `test_hsts_only_outside_development_and_only_when_configured` |
| Plain-HTTP exposure of the Compose stack | The web UI is published on `127.0.0.1:8080` only; access from other machines is meant to go through an HTTPS reverse proxy on the host (see Deployment assumptions) | `docker-compose.yml` | `test_web_ui_is_published_on_loopback_only` |
| Accumulating stale credentials | The worker deletes expired sessions and sign-in attempt records older than the 15-minute window in batches of 500, at start and then at most hourly while idle; failures are logged without tokens or account keys | `workers/queue.Worker.maybe_cleanup`, `services/maintenance.py` | `test_session_cleanup.py`, `test_login_attempt_cleanup.py` |
| Vulnerable dependencies | `pip-audit` and `npm audit` in CI | `.github/workflows/ci.yml` | ran locally 2026-10-17: none found |

## Deployment assumptions (docker compose)

- Compose forces `DEVPILOT_ENV=production` and `DEVPILOT_COOKIE_SECURE=true` and reads the
  repository-root `.env` (`backend/.env` is excluded from the image). The first account is created
  with `docker compose exec backend python -m app.cli create-user --email …`, which runs inside the
  backend container and so uses its database.
- Plain HTTP is published on the host's loopback only. Browsers accept `Secure` cookies on
  `http://localhost`, which is why local use works. For other machines, run an HTTPS reverse proxy
  on the same host that forwards to `http://127.0.0.1:8080`, passes the original `Host` header and
  sets `X-Forwarded-For` to the client address; set `DEVPILOT_PUBLIC_ORIGIN` to the HTTPS address
  and, once HTTPS is the only way in, `DEVPILOT_HSTS_SECONDS`. No TLS configuration ships with
  DevPilot.
- Trust chain for client IPs: host proxy → nginx (believes `X-Forwarded-For` only from the Docker
  gateway `172.30.0.1`) → API (believes it only from nginx `172.30.0.10`). The subnet
  `172.30.0.0/24` and both addresses are fixed in `docker-compose.yml`; change them together if the
  subnet collides with a host network. A deployment without this compose file must set
  `FORWARDED_ALLOW_IPS` to its own proxy's address.

## Known gaps and remaining risks

- **Analyzer parsers are attack surface.** Ruff and Bandit parse hostile files. They run with
  timeouts but without OS-level sandboxing (no container, seccomp or resource limits per run).
- **Git is attack surface.** `git archive` / `git diff` on an admin-allowed directory; repository
  config other than the overridden keys still applies. Local import is meant for trusted
  self-hosted use and is off by default.
- **GitHub zipballs are read into memory** before the size check (`download_zipball`).
- **All rate limits are stored in the database** (per-IP sign-in/registration, per-account sign-in,
  per-user imports and reviews, installation-wide reviews), so they survive restarts and apply across
  API processes. Each adds a short per-key lock on PostgreSQL; requests for the same key wait in line.
- **nginx's access log records client IP addresses** (its default log format, including the
  `X-Forwarded-For` value) to the frontend container's output. The API and worker never log or
  store raw IPs. Change `access_log` in `frontend/nginx.conf` if addresses must not be kept.
- **The per-account throttle can be triggered by anyone who knows an email address**, locking that
  account out of sign-in for up to 15 minutes. There is no permanent lockout.
- **No email verification, password reset or MFA.** In `invite` mode, anyone holding the invite code
  can create accounts until the code is changed or registration is closed.
- **Development encryption key.** If `DEVPILOT_SECRET_KEY` is empty in development, a fixed
  key is derived from a constant. Production mode refuses to start without a key. Rotating the key
  makes stored GitHub tokens unreadable (users must reconnect).
- **Prompt injection that suppresses findings** cannot be detected (see ai-review-pipeline.md).
- **Deployment hardening is configured, only partly run.** The Compose stack has been started on a
  disposable setup for the backup, restore and recovery drill (2026-10-25, see backup-restore.md),
  which exercised fresh-database start-up order and PostgreSQL. Not checked at runtime: the
  loopback binding, the gateway-only `X-Forwarded-For` trust (which assumes connections through the
  published port reach nginx from `172.30.0.1`), the live headers and the HTTPS proxy path are
  checked only as configuration (`docker compose config`, `nginx -t` with the upstream name mapped).
- **`X-Forwarded-Proto` is not forwarded** by nginx, so behind an HTTPS proxy the API sees `http`;
  the GitHub sign-in callback address it builds may then not match the App's HTTPS callback.
- **GitHub revocation has limits.** It has not been run against github.com. GitHub may refuse it for a
  fully expired authorization (the user is told to revoke it on GitHub), and an import or review
  that already holds an access token can finish with it unless revocation succeeds.
- **Cleanup needs a running worker.** With no worker (in-process or standalone), expired sessions and
  sign-in records stay until `python -m app.cli cleanup` is run; that command also removes old
  per-review snapshots, which the worker does not.
- **Concurrency guarantees** of the sign-in throttle and the review cap are tested on SQLite only.
- **Snapshot isolation is per directory**, not per OS user. Anyone with server file access can
  read all snapshots.
- **LLM provider retention** is governed by the provider's policy, not DevPilot.
- The PostgreSQL deployment path and the Docker images have not been run.
