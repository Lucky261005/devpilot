# ADR 0002: PostgreSQL as the system of record, SQLite for local development

**Status:** accepted (2026-10-17)

**Context.** Data is relational: users own repositories, which own reviews, which own findings and
feedback. Deleting a repository must remove everything below it. Reviews need a queue.

**Options.** PostgreSQL only; SQLite only; a document store.

**Decision.** SQLAlchemy models targeting PostgreSQL (used in docker-compose); SQLite allowed for
local development and tests. Alembic migrations, run by the test suite.

**Benefits.** Foreign keys and cascades express ownership; `FOR UPDATE SKIP LOCKED` makes the jobs
table a safe multi-worker queue (ADR 0004). SQLite means zero setup for contributors and fast tests.

**Costs.** Two engines behave differently (SQLite ignores row locks; ALTER TABLE support is
limited). The PostgreSQL path has not been exercised yet, which is a real risk until CI runs
against it.

**Revisit if** tests should run on PostgreSQL in CI (recommended next step: a service container).
