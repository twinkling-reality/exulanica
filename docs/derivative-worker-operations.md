# Derivative worker operations

- Status: **IMPLEMENTED, PostgreSQL-tested, and image-smoke-tested 2026-09-04**.
- Scope: photograph derivative delivery, including production point-map generation. Scene pose,
  publication, indexing, package export, and Atlas layout remain separate processes.

## Process shape

`POST /intake` validates and content-addresses source bytes, commits capture evidence, and enqueues a
PostgreSQL job containing capture UUIDs. It never places source bytes in the queue. Production runs
the API with `EXULANICA_DERIVATIVE_WORKER=off` and starts a separately restartable process:

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@postgres:5432/${POSTGRES_DB:-exulanica}
export EXULANICA_DATA_DIR=/var/lib/exulanica
export EXULANICA_WORKSPACE_IDS=<uuid>[,<uuid>...]
export EXULANICA_DEPTH_MODEL=moge
export EXULANICA_DEPTH_MODEL_ID=Ruicheng/moge-2-vitl
export EXULANICA_DEPTH_MODEL_REVISION=39c4d5e957afe587e04eec59dc2bcc3be5ecd968
uv run --extra reconstruction exulanica-derivative-worker
```

Repeat `--workspace <uuid>` instead of the environment variable when that is easier to manage.
`--name` provides a stable operator-chosen worker identifier; otherwise the command combines host,
PID, and a random suffix. `--once` drains currently eligible work with the same durable start/stop
events and exits. An empty or malformed workspace set is a startup failure.

The API and worker must connect as a role that owns no RLS table and has neither SUPERUSER nor
BYPASSRLS. Both inspect the active database role at startup and refuse an unsafe one. The bootstrap
owner URL belongs only to `exulanica-db`; `compose.yaml` enforces that split.

`EXULANICA_DEPTH_MODEL` accepts only `moge` or `unavailable` and defaults to the latter outside
Compose. `EXULANICA_DEPTH_MODEL_REVISION` is a full Git commit, not a mutable branch or tag, and is
included in the model identity stored with each point map. `EXULANICA_DEPTH_DEVICE` may pin `cuda`,
`mps`, or `cpu`; when absent, the model selects MPS, then CUDA, then CPU according to measured
runtime availability. Compose persists `HF_HOME` under the media volume so a restart does not
download the reviewed checkpoint again.

`EXULANICA_SEGMENTATION_MODEL` accepts only `local` or `unavailable` and defaults to the latter
everywhere, Compose included. `local` loads the object segmenter the manifest's `local_roles` pin
(SAM 2.1, with Grounding DINO and OWLv2 for boxes) and re-reads each pinned licence before any
weights load; there is no checkpoint override, because swapping one re-keys every mask.
`EXULANICA_SEGMENTATION_DEVICE` may pin `mps`, `cuda`, or `cpu`; when absent the segmenter selects
MPS, then the CPU. It needs the `segmentation` extra (`uv run --extra reconstruction --extra
segmentation exulanica-derivative-worker`), and a worker without it refuses to start rather than
segmenting nothing. The Compose derivative image is built with `--extra reconstruction` alone, so
turning it on there means adding the extra to that build and the variable to that service. Only
this worker builds a segmenter: it already holds torch, and pycolmap and torch cannot share a
process on macOS, so nothing that runs in the scene worker may load one. See
[scene-segments.md](scene-segments.md) section 4.

## Delivery contract

PostgreSQL is the queue and the delivery ledger. There is no message broker and no
service-per-capability split. The measured queued-job lookup is an ordered index scan over
`(workspace_id, kind, priority, job_id) where state = 'queued'`; `run_after` remains a filter so it
does not destroy `order by priority, job_id`. On the populated concurrency fixture it touches at
most eight buffers and requires no sort. A broker would add a second acknowledgement state without
evidence that this indexed, transactional queue misses the contract.

Delivery is at least once. Effects are exactly once through four database boundaries:

1. `for update skip locked` gives one claimant a row without blocking a second worker;
2. every claim rotates an opaque token and every progress, retry, and terminal write checks it;
3. derivative identities are computed before work and uniquely content-addressed, so a replay
   resolves a committed artifact instead of recomputing it; and
4. a unique partial index permits one terminal delivery event per job.

A lease-renewal thread uses an independent connection while the delivery thread is inside a slow
stage. The main thread checks the token again at capture and continuity boundaries. If renewal or a
boundary check reports a different token, the old worker records `lease_lost`, withdraws, and does
not close either the job or its batch.

An expired running row is reclaimed before new queued work, so recovery is not starved. Reclaim
closes any pipeline run left open by the previous token as `failed` with
`worker_process_lost`; the new claim then replays from durable inputs. A retryable transport or
structured-response failure is returned to the queue with bounded exponential delay. Three claims
are allowed. A third retryable failure becomes `failed` with `retry_exhausted`; three process deaths
become `retry_exhausted_after_process_death`. Non-retryable failures terminate immediately.

Measured cost accumulates across attempts on the job row. Retry events retain each attempt's cost;
the terminal event and operational metrics carry the cumulative cost. Missing provider usage stays
missing rather than being estimated.

## Real progress and state

The pipeline ledger registers reviewed stage definitions additively and accepts stage events only
for a registered `(stage key, version, parameter digest)`. The implemented per-capture stages are:

| Stage | Meaning | Durable timing |
| --- | --- | --- |
| `intake` | Hash, probe, upright normalization, evidence and source artifact | Actual start/end and monotonic duration |
| `rendition` | Bounded display JPEG used by later stages | Actual start/end and monotonic duration |
| `vision` | Structured observation when a vision implementation is configured | Actual start/end, model identity, attempts, tokens and returned cost |
| `depth` | Point-map production when a depth implementation is configured | Actual start/end and model identity |

**CORRECTED 2026-09-04.** Rendition stage version 2 records `optimize: false` in its parameters.
Version 1 always enabled Pillow's optional JPEG entropy-table optimization. The libjpeg encoder
then failed on reproducible, valid high-entropy frames with `broken data stream when writing image
file` before any model call. Version 2 makes the robust encoding choice deterministic and visible in
the artifact identity. It does not retry the same input with a hidden alternative encoder setting.

There are no indexing, publication, or reconstruction events. New stage names require a reviewed
stage definition before the database accepts their events.

`stage_succeeded`, `stage_failed`, and `stage_reused` keep their existing meanings.
`stage_unavailable` means the real stage had no configured implementation;
`stage_missing` means a required durable input was absent; `stage_skipped` is reserved for a
reviewed stage deliberately disabled by policy. Unavailable optional vision or depth does not turn
capture-supported intake and rendition facts into a failed job: the lower rung can finish while the
ledger says exactly what did not run.

Delivery jobs use these terminal states:

| State | Meaning |
| --- | --- |
| `done` | All remaining work reached its honest available result |
| `cancelled` | Deletion withdrew every relevant capture; this is not a failure |
| `missing` | A required capture or durable source input did not exist |
| `unavailable` | Required processing was unavailable rather than failed |
| `failed` | Non-retryable work failed or the retry/reclaim budget was exhausted |

`queued` and `running` are non-terminal. Job progress counts only real terminal capture outcomes.
Retryable failures remain pending. A deletion committed during a stage may make an already-started
provider call billable, but tombstone guards prevent the returned derivative from becoming an
effect and the job terminates as cancelled.

## Observability

The process emits one JSON object per lifecycle condition to standard output: `startup`,
`startup_failed`, `shutdown_requested`, `shutdown_timed_out`, `pass_failed`, unexpected worker stop,
and `stopped`. The database carries the authoritative replay in `derivative_job_event`, including:

- worker start, shutdown request, and stop;
- claim or reclaim with attempt and token;
- lease renewal, retry scheduling, and lease loss;
- capture start plus succeeded, failed, cancelled, missing, or unavailable completion; and
- exactly one job succeeded, failed, cancelled, missing, or unavailable event.

All events are workspace-scoped under FORCE row-level security. Authenticated operators can read
their workspace through:

- `GET /operations/derivative-jobs` for queued/running depth, oldest queued age, state counts,
  maximum attempts, terminal duration, cumulative model cost, and failure classes;
- `GET /operations/derivative-jobs/{job_id}/events` for the complete ordered delivery replay.

An unknown or foreign-workspace job returns an empty replay, so existence is not disclosed across
the authorization boundary.

## Shutdown and recovery runbook

SIGTERM and SIGINT stop new claims and wait for the held job. The default grace period is 900
seconds and can be changed with `--grace-seconds`. A clean stop records `shutdown_requested` and
`worker_stopped`. If the grace period expires, the command returns status 2; the killed process's
lease then expires and another worker reclaims it. Do not manually set a running job to done.

For a growing queue:

1. Read `/operations/derivative-jobs`; distinguish queued age from a live running claim.
2. Read the job replay. Repeated `lease_renewed` means slow live work; a stale last event with an
   expired lease means reclaim is expected.
3. Check worker JSON output for startup-role refusal, schema refusal, or repeated pass failures.
4. Start another worker with the same workspace authorization and shared content-addressed store.
   Two workers are supported; do not clear claim tokens or duplicate jobs by hand.
5. Treat `missing`, `unavailable`, `cancelled`, `lease_lost`, and retry exhaustion differently.
   Only a retryable queued job is expected to run again automatically.

## Verified acceptance boundary

The PostgreSQL acceptance test kills a real process after each committed existing stage boundary:
intake, rendition, vision, and depth. It expires the abandoned lease and starts two competing clean
processes. Every case produces one canonical artifact per stage and capture, one job terminal event,
no running pipeline ledger row, and one returned paid vision result per capture. Separate tests cover
two-connection contention, independent lease renewal, mid-job lease loss, deletion during work,
retry exhaustion, and graceful shutdown.

This is not a claim that an arbitrary kill between a remote provider accepting a request and the
local artifact commit can make the external charge exactly once. No local database can prove that
without provider-side idempotency. The contract is exactly-once local effects and no duplicate paid
result after a committed stage boundary; any provider response whose usage was never returned is
not fabricated in cost provenance.
