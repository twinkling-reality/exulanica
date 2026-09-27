# Derivative worker operations

This guide owns running `exulanica-derivative-worker`, the process that turns an uploaded
photograph into its derivatives: its delivery contract, progress, observability, shutdown and
recovery. Photographs are one way to build a world; this worker is what makes an upload usable.
Scene pose recovery and publication, purges and material bakes are separate processes
([deployment](deployment.md#2-processes)), and every setting the worker reads is in
[deployment, section 5.2.2](deployment.md#522-the-derivative-worker).

## Process shape

`POST /intake` validates and content-addresses source bytes, commits capture evidence, and enqueues a
PostgreSQL job containing capture UUIDs. It never places source bytes in the queue. A production
composition runs the API with `EXULANICA_DERIVATIVE_WORKER=off` and starts a separately restartable
process:

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@postgres:5432/${POSTGRES_DB:-exulanica}
export EXULANICA_DATA_DIR=/var/lib/exulanica
export EXULANICA_WORKSPACE_IDS=<uuid>[,<uuid>...]
export EXULANICA_DEPTH_MODEL=moge
uv run --extra reconstruction exulanica-derivative-worker
```

Repeat `--workspace <uuid>` instead of the environment variable when that is easier to manage, or
set `EXULANICA_ACCOUNT_DATABASE_URL` to drain every active account-owned workspace as well.
`--name` provides a stable operator-chosen worker identifier; otherwise the command combines host,
PID, and a random suffix. `--once` drains the work that is eligible at that moment, with the same
durable start and stop events, and exits. An empty or malformed workspace set with no account
source is a startup failure.

The worker must connect as a role that owns no RLS table and has neither SUPERUSER nor BYPASSRLS.
It inspects the active database role at startup and refuses an unsafe one, as the API does. The
bootstrap owner URL belongs only to `exulanica-db`; `compose.yaml` enforces that split.

The depth model is the checkpoint `exulanica/models/models.manifest.json` pins as
`local_roles.depth`, at a full Git commit that is part of the model identity stored with each point
map; `EXULANICA_DEPTH_MODEL=moge` turns it on. Compose keeps `HF_HOME` on the media volume, so a
restart does not download the checkpoint again.

Object segmentation (`EXULANICA_SEGMENTATION_MODEL=local`) loads the segmenter the manifest's
`local_roles` pin (SAM 2.1, with Grounding DINO and OWLv2 for boxes) and re-reads each pinned
licence before any weights load. There is no checkpoint override, because swapping one re-keys every
mask. It needs the `segmentation` extra (`uv run --extra reconstruction --extra segmentation
exulanica-derivative-worker`), and a worker without it refuses to start rather than segmenting
nothing. The Compose derivative image is built with `--extra reconstruction` alone, so turning it on
there means adding the extra to that build and the variable to that service. Only this worker
builds a segmenter: it already holds torch, and pycolmap and torch cannot share a process on macOS,
so nothing that runs in the scene worker may load one. See [scene-segments.md](scene-segments.md)
section 4.

Person regions (`EXULANICA_PERSON_DETECTOR=recorded-observation`) are proposed from the people the
vision observation located. The default, `unavailable`, proposes none, and the region stage says
that nothing looked; [person presentation consent](person-presentation-consent.md) owns what a
region then hides.

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
for a registered `(stage key, version, parameter digest)`. The per-capture stages run in this order
(`exulanica/ingest/pipeline.py`), and every stage event records its actual start, end and monotonic
duration:

| Stage | Meaning | Also recorded |
| --- | --- | --- |
| `intake` | Hash, probe, upright normalization, evidence and source artifact | |
| `decoded_source` | For a HEIF photograph only: the lossless decoded image later stages read | Decoder and library versions |
| `rendition` | Bounded display JPEG, the only pixels a model receives | |
| `vision` | Structured observation when a vision model is configured | Model identity, attempts, tokens and returned cost |
| `person_regions` | Person regions from the vision observation when a person detector is configured | |
| `masked_source` | The derivative in which every region whose person has not consented is filled; depth and segmentation read it | |
| `depth` | Point-map production when a depth model is configured | Model identity |
| `segmentation` | Object masks when the segmenter is configured | Model identity and device |

The rendition encodes without Pillow's optional JPEG entropy-table optimization and records
`optimize: false` in its parameters. With that optimization the libjpeg encoder failed on
reproducible, valid high-entropy frames with `broken data stream when writing image file` before any
model call, so the robust choice is deterministic and part of the artifact identity, and the stage
never retries the same input with a hidden alternative setting.

Rendition stage version 3 writes an empty JPEG comment, so a comment (COM marker) in the source
photograph does not reach the rendition a model receives; the rendition already carries no EXIF
([derivatives.py](../exulanica/ingest/derivatives.py)). For a source without a comment the encoded
bytes equal version 2's, so the content hash, and every downstream key built from it, stays the
same; only the rendition artifact is re-keyed. For a source with a comment the bytes differ, and
the vision stage computes a new key from them.

There are no indexing, publication, or reconstruction events. New stage names require a reviewed
stage definition before the database accepts their events.

`stage_succeeded`, `stage_failed` and `stage_reused` mean what they say.
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

The PostgreSQL acceptance test (`tests/test_derivative_reclaim.py`) kills a real process at each of
the intake, rendition, vision and depth stage boundaries. It expires the abandoned lease and starts two competing clean
processes. Every case produces one canonical artifact per stage and capture, one job terminal event,
no running pipeline ledger row, and one returned paid vision result per capture. Separate tests cover
two-connection contention, independent lease renewal, mid-job lease loss, deletion during work,
retry exhaustion, and graceful shutdown.

This is not a claim that an arbitrary kill between a remote provider accepting a request and the
local artifact commit can make the external charge exactly once. No local database can prove that
without provider-side idempotency. The contract is exactly-once local effects and no duplicate paid
result after a committed stage boundary; any provider response whose usage was never returned is
not fabricated in cost provenance.
