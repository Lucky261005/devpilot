# ADR 0004: Database-backed job queue with an in-process or standalone worker

**Status:** accepted (2026-10-17)

**Context.** A review runs git, two analyzers and possibly a minute-long model call. That cannot
run inside an HTTP request. The MVP has one server and low volume.

**Options.** FastAPI `BackgroundTasks`; Celery/RQ with Redis; a database table as the queue.

**Decision.** `review_jobs` is the queue. A worker claims the oldest queued job with
`SELECT ... FOR UPDATE SKIP LOCKED`, runs it, and records status, stage and stats. The worker runs
as a thread in the API process by default, or as `python -m app.workers.queue` (docker-compose).

**Benefits.** No extra service. Job state and results commit to the same database. Restarts lose
nothing that was queued. `BackgroundTasks` was rejected because jobs would be lost on restart and
could not be inspected.

**Costs.** Polling (1 s) instead of push. No priorities, retries or scheduling. A stuck Python
thread cannot be killed; overlong jobs are failed by stale-job recovery at the next worker start.
SQLite has no row locks, so only one worker there.

**Revisit if** throughput needs many workers, job retries with backoff, or cancellation. Then
Redis plus a task framework is worth its operational cost.
