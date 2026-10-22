# Data model

Defined in `backend/app/models.py`; schema created by Alembic migration
`backend/alembic/versions/3c3abb209ebc_initial_schema.py`. The test suite runs that migration
(not `create_all`) so the migration is exercised on every test run (SQLite). It has not yet been
run against PostgreSQL.

## Entity relationships

```
users 1─* sessions
users 1─0..1 github_accounts
users 1─* repositories 1─* code_chunks
                     │ 1─* pull_requests
                     │ 1─* review_jobs 1─* changed_files
                     │                 1─* findings 1─* finding_feedback *─1 users
                     │                 1─* test_suggestions *─0..1 findings
users 1─* audit_events (user_id SET NULL on delete)
```

## Tables

| Table | Purpose | Key columns and constraints |
|---|---|---|
| `users` | Accounts | `email` UNIQUE, `password_hash` (argon2id) |
| `sessions` | Login sessions | `token_hash` UNIQUE (SHA-256 of the cookie token), `expires_at`, FK user CASCADE, index on `user_id` |
| `github_accounts` | Linked GitHub identity | `user_id` UNIQUE FK CASCADE, `encrypted_token` (Fernet), `scopes` |
| `repositories` | Imported repositories | UNIQUE(`owner_id`, `name`), `source_type` archive/local/github, `source_ref`, `ai_review_allowed`, `index_status`, `index_error`, `file_count`, `total_bytes`, `skipped` JSON, `snapshot_dir` |
| `code_chunks` | Search index | FK repo CASCADE, `path`, `language`, `start_line`, `end_line`, `content`, `symbols`; index (`repository_id`, `path`) |
| `pull_requests` | PR metadata seen by a user | UNIQUE(`repository_id`, `number`), `base_sha`, `head_sha`, `title`, `author`, `url` |
| `review_jobs` | Reviews and the job queue | FK repo CASCADE, FK PR SET NULL, `kind`, refs, `use_ai`, `status`, `stage`, `error`, timestamps, `stats` JSON; index (`status`, `created_at`) for claiming |
| `changed_files` | Files in a diff/PR review | FK review CASCADE, `status`, `additions`, `deletions`, `patch` (≤200 KB) |
| `findings` | Normalized findings | FK review CASCADE, `source` static/ai, `analyzer`, `analyzer_version`, `rule_id`, `severity`, `category`, `path`, `start_line`, `end_line`, `evidence`, `reasoning`, `suggested_fix`, `suggested_test`, `confidence`, `limitations`, `doc_url` |
| `finding_feedback` | User verdicts | UNIQUE(`finding_id`, `user_id`) (re-rating updates), denormalized `repository_id`, `review_id`, `analyzer`, `analyzer_version` |
| `test_suggestions` | Suggested tests | FK review CASCADE, `source`, `target`, `path`, `start_line`, `rationale`, `test_code`, optional FK finding SET NULL |
| `audit_events` | Security-relevant actions | `action` (user.register, user.login, repository.create/delete/ai_consent, review.create, github.connect/disconnect), `detail` JSON |

All timestamps are timezone-aware UTC (`created_at` on most tables).

### Why the denormalized columns in `finding_feedback`

Feedback must still say which analyzer/model version it judged even if findings are later
re-generated or the analyzer is upgraded. Copying `analyzer` and `analyzer_version` makes the
evaluation query (`GET /api/feedback/summary`) a single-table aggregate.

### JSON columns

Used only where the shape varies and the value is read whole: `review_jobs.stats` (timings,
analyzer versions, LLM usage, rejected findings), `repositories.skipped` (reason → count),
`audit_events.detail`. Nothing filters on them. They map to `JSON` (JSONB-compatible) on PostgreSQL.

## Deletion behavior

Deleting a repository cascades to chunks, PRs, reviews, changed files, findings, feedback and
test suggestions (FK `ON DELETE CASCADE`; SQLite enforces it because `PRAGMA foreign_keys=ON` is
set on every connection). The API also removes `data/snapshots/<repo id>/` from disk.
Tested by `test_delete_repository_cascades`.

## Migration strategy

- Change `app/models.py`, then `uv run alembic revision --autogenerate -m "..."`, review the
  generated file, commit it.
- `alembic upgrade head` runs at container start (`backend/Dockerfile`) and in the test session.
- `render_as_batch` is not enabled yet; column alterations on SQLite will need it.

## Retention and sensitive data

| Data | Where | Retention |
|---|---|---|
| Repository snapshot (source files) | `data/snapshots/<repo>/current` | Until the repository is deleted (needed for search and file views). |
| Per-review snapshots (diff/PR) | `data/snapshots/<repo>/review-<id>` | Deleted by `python -m app.cli cleanup` after `DEVPILOT_RETENTION_DAYS` (14). |
| Code chunks | DB | Until repository deletion. |
| Findings incl. evidence excerpts (≤2 KB each) | DB | Until repository deletion. |
| Expired sessions | DB | Deleted by `cleanup`. |
| GitHub tokens | DB, Fernet-encrypted | Until disconnect or user deletion. |
| Passwords | DB, argon2id hash only | — |
| Secret files in imports (`.env`, keys, …) | Written by extraction, then deleted from the snapshot by discovery before indexing or analysis; never in the DB | — |

`cleanup` has to be scheduled externally (cron, a scheduled container); nothing runs it automatically.
