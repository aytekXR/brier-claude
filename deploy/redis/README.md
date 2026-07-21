# OPTIONAL — moving the Brier worker's job queue to the shared redis

**Document only. This note changes nothing.** `brier-worker.service` and its code
are untouched by the nginx migration and keep using the **Postgres jobs table**.
This file records how the queue *could* move to the shared host redis later, and
why you might (not) bother.

## What Brier does today

`brier-worker.service` runs `python -m brier_pipeline.jobs.worker`
(`bootstrap_handlers()` + `run_forever()`), draining a **Postgres jobs table** —
NOT redis. Enqueue and dequeue are SQL against the same `BRIER_DATABASE_URL`
Postgres the web app uses (`postgresql://…@127.0.0.1:5432/brier`). With an empty
table and no scheduler it idles, which is correct for Phase 1.

## Why Postgres-as-a-queue is fine to keep

- **One datastore, one backup.** The queue lives in the DB you already run,
  back up, and monitor. No second stateful service to secure.
- **Transactional enqueue.** A job can be enqueued in the SAME transaction as the
  row it is about (e.g. "ingested analyst X → enqueue score X"), so a job can
  never reference data that rolled back. Redis cannot join that transaction.
- **Low volume.** Brier's job rate is small; Postgres `SELECT … FOR UPDATE SKIP
  LOCKED` handles it comfortably. Redis buys throughput Brier does not need yet.

Keep Postgres unless one of the reasons below actually bites.

## When redis would help

- **Many workers / high dequeue rate** where `FOR UPDATE SKIP LOCKED` contention
  or table bloat from churn shows up in Postgres.
- **Sub-second latency** or fan-out patterns (pub/sub, streams) the SQL table
  models awkwardly.
- **Decoupling** the queue's load from the primary DB so a queue spike cannot
  slow web reads.

## The shared redis on this host

One hardened redis serves every app on the box (cache / rate-limit / queue). Its
owner-run, one-time setup (bind loopback + unix socket only, `requirepass`,
`maxmemory`) is the same as the blueprint `deploy/redis/README.md`. An app opts in
with a single `REDIS_URL`:

- Socket: `REDIS_URL=redis://:PASSWORD@/run/redis/redis.sock?db=0`
  (add the `aytek` user to the `redis` group to open the socket)
- TCP:    `REDIS_URL=redis://:PASSWORD@127.0.0.1:6379/0`

The password stays in `/etc/brier/brier.env` (root-owned, 0600) — never in a
tracked file. Add `BRIER_REDIS_URL` to `.env.production.example` (name only) if
and when this is adopted.

## What an adoption would actually require (NOT done here)

A queue backend is a code change and needs an **ADR** (the stack is locked; see
`.claude/skills/new-adr` and the existing ADR-XXXX series), because it changes a
core seam. Sketch, so the size is honest:

1. **ADR** proposing the switch, with the trigger metric that justifies it.
2. A `RedisJobQueue` implementing the same enqueue/dequeue/ack/retry contract the
   Postgres queue exposes in `brier_pipeline/jobs/` (at-least-once delivery, a
   dead-letter path, and visibility-timeout re-delivery — Postgres gives these
   via row locks + status columns; redis needs them built, e.g. Streams +
   consumer groups + `XCLAIM`, or a `BRPOPLPUSH` reliable-queue pattern).
3. A selection seam (`BRIER_QUEUE_BACKEND=postgres|redis`) defaulting to
   **postgres**, so the change is reversible and testable side-by-side.
4. A **migration** for in-flight jobs: drain the Postgres table to empty under a
   scheduler pause before flipping the backend, or dual-write during a window.
5. Health: extend the deploy health signal to also assert the queue backend
   (e.g. `redis-cli -u "$BRIER_REDIS_URL" ping` → `PONG`).

Until that ADR is approved, the worker stays on Postgres and this migration
leaves `brier-worker.service` exactly as it is.
