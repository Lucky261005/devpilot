# API reference

Base path `/api`. JSON unless noted. Interactive OpenAPI docs are served at `/docs` by FastAPI.

## Conventions

- **Authentication:** session cookie `devpilot_session` (httpOnly, SameSite=Lax), set by
  register/login. Endpoints marked 🔒 return `401 {"detail": "Not signed in."}` without it.
- **CSRF:** every `POST`, `PUT`, `PATCH`, `DELETE` must send `x-devpilot-csrf: 1`, otherwise
  `403 {"detail": "Missing CSRF header."}`.
- **Ownership:** resources that belong to another user return `404` (not 403).
- **Errors:** `{"detail": "<message>", "request_id": "<id>"}`. Validation errors:
  `422 {"detail": "Invalid request.", "errors": [{"loc": [...], "msg": "..."}]}`.
- **Request size:** bodies over `DEVPILOT_MAX_UPLOAD_BYTES + 1 MB` (by `Content-Length`) → `413`. Multipart uploads without `Content-Length` → `411`.
- **Request ID:** every response carries `x-request-id` (echoes the request header if sent).
- **Pagination:** only the review history is paginated (`limit` ≤ 200, `offset`). Other lists are bounded by nature.

## Health and settings

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | — | `{"status": "ok"}` after a `SELECT 1`. |
| GET | `/api/settings` | — | Non-secret server configuration the UI shows. |

```json
GET /api/settings
{
  "llm": {"provider": null, "model": null, "configured": false},
  "github": {"configured": false, "scopes": "(public, read-only)"},
  "limits": {"max_upload_bytes": 52428800, "max_repo_bytes": 209715200, "max_file_bytes": 524288, "reviews_per_hour": 30},
  "local_import_enabled": true,
  "retention_days": 14
}
```

## Auth

| Method | Path | Auth | Body | Success | Errors |
|---|---|---|---|---|---|
| POST | `/api/auth/register` | — | `{"email", "password"}` (password 10–256 chars) | `201 {"id", "email"}` + cookie | 409 email exists, 422, 429 (10/min/IP) |
| POST | `/api/auth/login` | — | `{"email", "password"}` | `200 {"id", "email"}` + cookie | 401 `Incorrect email or password.`, 429 |
| POST | `/api/auth/logout` | — | — | `204`, session row deleted, cookie cleared | — |
| GET | `/api/auth/me` | 🔒 | — | `200 {"id", "email"}` | 401 |

Emails are lower-cased. Unknown-email logins still run an argon2 verification so timing does not
reveal which emails exist.

## Repositories

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/repositories` | 🔒 | Current user's repositories, newest first. |
| POST | `/api/repositories/archive` | 🔒 | Multipart `name`, `file` (ZIP). Imports and indexes synchronously. |
| POST | `/api/repositories/local` | 🔒 | `{"name", "path"}`. Path must be a Git repo under `DEVPILOT_ALLOWED_LOCAL_ROOTS`. Exports `HEAD`. |
| POST | `/api/repositories/github` | 🔒 | `{"full_name": "owner/name"}`. Needs a connected GitHub account. Downloads the default branch. |
| GET | `/api/repositories/{id}` | 🔒 | One repository. |
| PATCH | `/api/repositories/{id}` | 🔒 | `{"ai_review_allowed": bool}`. Audited. |
| DELETE | `/api/repositories/{id}` | 🔒 | `204`. Cascades everything and removes snapshots from disk. |
| GET | `/api/repositories/{id}/files?prefix=` | 🔒 | Indexed file paths. |
| GET | `/api/repositories/{id}/file?path=` | 🔒 | `{"path", "language", "content", "line_count"}` from the current snapshot. |
| GET | `/api/repositories/{id}/search?q=&mode=text\|identifier` | 🔒 | Up to 50 matching lines. |
| GET | `/api/repositories/{id}/stats` | 🔒 | `{"languages": {"python": 4, ...}}` (file counts). |

Repository object:

```json
{
  "id": 1, "name": "inventory-demo", "source_type": "local",
  "source_ref": "/path/to/devpilot-demo-repo",
  "ai_review_allowed": false, "index_status": "ready", "index_error": null,
  "indexed_at": "2026-10-17T08:01:12Z", "file_count": 6, "total_bytes": 1912,
  "skipped": {}, "created_at": "2026-10-17T08:01:12Z"
}
```

Import errors: `400` (invalid local path, GitHub name), `404` (GitHub repo not found or no
access), `409` (name already used), `413` (upload too large), `429` (20 imports/hour). A
**rejected archive** (unsafe paths, symlinks, too large, not a ZIP) returns `201` with
`index_status: "failed"` and `index_error` explaining why, so the failure is visible in the list.

Search example:

```json
GET /api/repositories/1/search?q=apply_discount&mode=identifier
{"query": "apply_discount", "mode": "identifier",
 "results": [{"path": "inventory/pricing.py", "line": 4, "text": "def apply_discount(price, quantity):",
              "language": "python", "chunk_start": 4, "chunk_end": 8}]}
```

File reads: `404` if the path escapes the snapshot or doesn't exist, `410` if the snapshot was
removed by retention cleanup, `413` if the file is larger than `DEVPILOT_MAX_FILE_BYTES`.

## Reviews

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/repositories/{id}/reviews` | 🔒 | Queue a review. `202` with the review object. |
| GET | `/api/repositories/{id}/reviews?limit=&offset=` | 🔒 | History, newest first. |
| GET | `/api/reviews/{id}` | 🔒 | Status, stage, error, stats, severity counts. |
| GET | `/api/reviews/{id}/findings?severity=&category=&source=` | 🔒 | Findings, most severe first. Filters repeatable. |
| GET | `/api/reviews/{id}/changed-files` | 🔒 | Files and patches (diff / PR reviews). |
| GET | `/api/reviews/{id}/test-suggestions` | 🔒 | Static and AI test suggestions. |
| GET | `/api/reviews/{id}/file?path=` | 🔒 | File content from the snapshot the review analyzed. |

Create body:

```json
{"kind": "diff", "base_ref": "HEAD~1", "head_ref": "HEAD", "use_ai": false}
{"kind": "full", "use_ai": true}
{"kind": "pull_request", "pr_number": 7, "use_ai": true}
```

Rules: repository must be indexed (`409`); `diff` needs a local repository and `pull_request` a
GitHub repository (`400`); the PR must have been opened via `GET .../pulls/{n}` first (`404`);
`use_ai` requires `ai_review_allowed` (`400`); `DEVPILOT_REVIEWS_PER_HOUR` per user (`429`).
Invalid refs are not rejected at creation; the job fails with `Invalid Git ref: ...`.

Review object (completed, abbreviated):

```json
{
  "id": 2, "repository_id": 1, "kind": "diff", "base_ref": "HEAD~1", "head_ref": "HEAD",
  "use_ai": false, "status": "completed", "stage": null, "error": null,
  "severity_counts": {"high": 1, "medium": 1},
  "pr_number": null, "pr_title": null,
  "stats": {
    "base_sha": "da38467...", "head_sha": "67f7082...",
    "timings": {"prepare_ms": 900, "static_ms": 1300, "total_ms": 2300},
    "analyzers": {"ruff": {"version": "0.17.1", "files": 1, "status": "ok", "raw_findings": 0},
                  "bandit": {"version": "1.9.4", "files": 1, "status": "ok", "raw_findings": 0}},
    "ai": {"status": "not_requested"},
    "files_reviewed": 1, "duplicates_dropped": 0, "findings": {"static": 0, "ai": 0}
  }
}
```

`stats.ai` when the LLM ran: `{status, model, provider, latency_ms, input_tokens, output_tokens,
attempts, context_chars, files_in_context, files_omitted, summary, returned, accepted, rejected:
[{title, reason}]}`. When skipped or failed: `{status, reason}`.

Finding object:

```json
{
  "id": 14, "review_id": 1, "source": "static", "analyzer": "bandit", "analyzer_version": "1.9.4",
  "rule_id": "B602", "title": "B602: subprocess_popen_with_shell_equals_true",
  "description": "subprocess call with shell=True identified, security issue. (CWE-78)",
  "severity": "high", "category": "security", "path": "inventory/store.py",
  "start_line": 27, "end_line": 27,
  "evidence": "    return subprocess.call(\"generate-report \" + name, shell=True)",
  "reasoning": null, "suggested_fix": null, "suggested_test": null, "confidence": "high",
  "limitations": "Pattern-based check; it cannot see whether input is trusted.",
  "doc_url": "https://bandit.readthedocs.io/...", "my_feedback": null
}
```

## Feedback

| Method | Path | Auth | Description |
|---|---|---|---|
| PUT | `/api/findings/{id}/feedback` | 🔒 | `{"verdict": "useful"\|"incorrect"\|"duplicate"\|"not_actionable", "comment"?}` → `204`. Idempotent per user (re-rating replaces). |
| GET | `/api/feedback/summary` | 🔒 | `{"<analyzer>": {"<verdict>": count}}` for the current user. |

## GitHub

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/github/status` | 🔒 | `{"configured", "connected", "login", "scopes"}` |
| GET | `/api/github/oauth/start` | 🔒 | `307` to GitHub; sets state cookie. `503` if OAuth isn't configured. |
| GET | `/api/github/oauth/callback?code=&state=` | 🔒 | Validates state, stores encrypted token, redirects to `/settings?github=connected`. `400` on state mismatch. |
| DELETE | `/api/github/account` | 🔒 | Removes the stored token. `204`. |
| GET | `/api/github/repos` | 🔒 | Up to 100 repos the token can see. |
| GET | `/api/repositories/{id}/pulls?state=open` | 🔒 | Open PRs of a GitHub repository. |
| GET | `/api/repositories/{id}/pulls/{number}` | 🔒 | PR metadata plus changed files and patches (≤300 files). Records the PR. |

GitHub errors are mapped: token rejected → `401`; rate limit exhausted → `429` with the reset
time; not found / no access → `404`; other API errors → `502`.
