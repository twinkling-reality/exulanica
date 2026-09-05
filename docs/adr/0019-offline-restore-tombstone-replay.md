# ADR-0019: A declared offline restore replays a sealed deletion checkpoint before serving

- Status: Accepted for the local offline mechanism; production rehearsal remains OPEN
- Date: 2026-09-05
- Deciders: Exulanica build, under the unblocked backend program

## Invariant

A declared restore cannot serve or start a derivative worker until every tombstone in its
current, complete, independently retained checkpoint has been reapplied and its purge verified.
An external pending attempt marker survives restoration of both the database and object store.
A database receipt restored from a previous backup cannot satisfy a new attempt UUID.

The source checkpoint includes **every committed tombstone**, across workspaces, with original
identity, author, scope, times, reason, interval and blocklist intent, plus every purge target,
including completed targets. Checkpoint creation takes an exclusive tombstone-table lock and
seals new tombstone inserts at the database boundary, including direct SQL. Only an administrative
complete view may create the checkpoint. Application and purger credentials cannot certify a
checkpoint or completion receipt. The purge role's privileges are unchanged; runtime has no
DELETE, and destruction still uses the existing cross-workspace authorization predicate.

## Rationale and scope

A restored database cannot be its own authoritative deletion history: a backup preceding a
deletion contains no record of that deletion. An external checkpoint is authoritative through
operator custody and its complete, sealed source, rather than through its hash alone. The hash
binds content and detects accidental changes; it does not authenticate an untrusted operator.

This is an **offline restore protocol**, not an automatic disaster detector or an always-on
journal. Stop the API, derivative workers, purge workers, CLI writers and every direct SQL writer
before checkpoint creation. Keep them stopped until replay completes. The source seal rejects
new tombstones; it does not stop an already-running API or every other kind of write. No promise
is made about an undeclared restore, an omitted marker configuration, an independently rolled-back
control directory, or a stale checkpoint after the source resumed. Resuming the source requires
a fresh complete checkpoint before a later restore. This mechanism cannot recover tombstones
lost before any current independent checkpoint was retained.

Physical deletion may be correctly deferred when a live capture in this or another workspace
holds the same content. This version **refuses restore completion** in that case. It never widens
the purger's authority to make a restore pass. Supporting completion with verified shared-content
holdbacks is deferred; the refusal and the preserved foreign bytes are tested.

The existing interval-withdrawal limits remain: replay reproduces its tombstone and serving
refusals, and does not invent video repair or broader erasure semantics. Source and evidence stub
rows remain as the existing audit design requires; absence means absence from serving, with
410 for withdrawn evidence endpoints under the subsequent ADR-0022, before or after physical
purge. No promise of physical deletion of every PostgreSQL stub
is made. This local exercise does not close production rehearsal, backup retention operations,
A-8, P-1, a cloud deployment, or disaster recovery completeness after an uncheckpointed deletion.

## Canonical representation

The checkpoint is an `exulanica.digest-bound-record/v1` envelope. Its record profile is
`exulanica.restore-tombstone-checkpoint/v1`; `record_sha256` is SHA-256 of `canonical_json(record)`.
Rows use PostgreSQL JSON encodings for UUIDs, timestamps and the half-open `int8multirange` string.
An outer state first says `prepared`, and says `sealed` only after the database seal commits.
Prepared files are unusable. Checkpoint files are created at fresh paths and not overwritten.

The independently retained `exulanica.restore-state/v1` marker binds `restore_id`, `checkpoint_id`
and `checkpoint_sha256`, with state `pending` or `complete`. Writes use an atomic rename and fsync
of both file and directory. The singleton `restore_control` row says `sealed`, `replaying` or
`complete`; `restore_replay_receipt` records one completion per attempt UUID and its tombstone count.
Neither control table contains workspace content beyond global checkpoint metadata and counts.

Missing original tombstones retain their IDs. Each checkpoint tombstone also receives a stable
UUIDv5 replay ID derived from the attempt and original ID, causing the existing deletion triggers
to run even when an old original row was already present. Repeating the same attempt adds no rows.
Archived targets and reset jobs cover a completed database paired with older restored blob bytes.
Every aggregate in affected workspaces becomes stale: a pre-restore closure is not trusted. Other
workspaces are not invalidated. This operation does not recompute a model-produced artifact.

## Failure behaviour

Every partial replay retains a pending external marker and issues no new completion receipt. It may commit
individual monotonic deletions and destroy bytes before a later failure; retry reapplies them
idempotently. Missing/corrupt checkpoint files, conflicting tombstone contents, missing capture-to-blob
bindings needed by an interval or hash blocklist, narrow
administrative visibility, unavailable marker, wrong attempt receipts, failed or deferred purge,
exhausted jobs, and surviving target bytes refuse completion or startup. If the final external
marker write fails after the database receipt commits, startup still refuses until replay is
resumed. Startup checks this even when the test-only schema-verification bypass is selected.

## Compatibility and affected surfaces

Migration `0036_restore_tombstone_replay.sql` is forward-only. Historical migrations and evidence
addresses do not change. It also binds the recursive JSON-schema validators to their own schema:
an actual pg_dump restore exposed their unqualified self-calls failing during COPY with the
restorer’s empty search path. An ordinary instance with no declared restore keeps its existing startup
behaviour; a sealed or replaying database refuses. `EXULANICA_RESTORE_STATE_PATH` configures the
independent marker for API startup. `Services.restore_state_path` is the injectable equivalent.
`exulanica.deletion.restore` supplies checkpoint, prepare and replay commands. Runtime provisioning
revokes INSERT/UPDATE on the two administrative control tables. Purge grants and DELETE privileges
are unchanged. No HTTP route, browser payload, worker algorithm, export format or model call is
added. The checkpoint is a private operational artifact, not a world-package export.

## Local operational sequence

Keep the checkpoint and marker outside both database and blob backups and retain their current
contents. Configure the API process with `EXULANICA_RESTORE_STATE_PATH` pointing at that marker.
The API must remain stopped until the marker exists and replay completes.

1. Stop traffic and all writers. With the current source's administrative database URL, run
   `uv run python -m exulanica.deletion.restore checkpoint --checkpoint /independent/checkpoint.json`.
2. Before restoring anything, run
   `uv run python -m exulanica.deletion.restore prepare --checkpoint /independent/checkpoint.json --marker /independent/restore.json`.
3. Restore the database and object-store backups while keeping the checkpoint and marker intact.
   Apply forward migrations and reprovision normal runtime/purge roles. Reprovisioning is
   mandatory: existing default grants can otherwise leave the new control tables writable.
4. With the restored administrative URL and the separate `EXULANICA_PURGE_DATABASE_URL`, run
   `uv run python -m exulanica.deletion.restore replay --checkpoint /independent/checkpoint.json --marker /independent/restore.json`.
5. Start the API with the same configured marker path. Failed replay is resumed with the same
   command and pending attempt; a completed attempt may be repeated without extra receipts.

These are operational instructions, not evidence of a deployment. Tests use only
`postgresql://localhost:5433/exulanica_spine_test`, a scratch schema, actual `pg_dump`/`psql`, a
synthetic scripted photograph, and independent temporary checkpoint/control directories.

## Verification and executed negative controls

Seven focused synthetic tests pass, including two actual database dump/restores. A regression run
covering restore, purge, API, migrations, workspace isolation and ingest preconditions passed
389 tests. The final focused restore plus retained-record checks passed 26 tests. These are
executable checks, not a measurement of retrieval, identity or model quality.

Twelve production mutations were executed and reverted. Tests failed when replay was omitted
(two failures, including completed-job/old-byte divergence), startup verification was removed,
the SQL source seal was removed, the checkpoint digest was ignored, shared-content release
protection was removed, receipt identity was ignored, aggregate invalidation was omitted,
checkpoint reads were narrowed to one workspace, runtime control-table writes were granted,
missing capture bindings were accepted, recursive validators lost their bound schema path,
or the external marker was ignored after restoring a database with no restore-control row.
The last control allowed startup with the old graph and failed the refusal assertion, proving
that the independently retained marker is necessary. The validator control reproduced an actual
`psql COPY predicate` failure, rather than a simulated restore.
