# ADR-0002: PostgreSQL-backed job queue

- Status: accepted

## Decision
A `core_job` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`, 30-minute leases, exponential backoff, max attempts, unique idempotency keys and a global limit on concurrently running *heavy* jobs (OCR/conversion, default 1). Implemented in `apps/core/jobs.py` and tested for lease recovery, idempotency, retry and the heavy limit.

## Alternatives
Celery/RQ need Redis (another service). django-tasks backends were not mature enough to rely on for leasing semantics at decision time.

## Consequences
Jobs enqueued inside a transaction become visible only on commit (`transaction.on_commit`). Handlers must be idempotent and re-check permissions/state at execution.
