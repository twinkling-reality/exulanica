# Execute an isolated generated-media recovery drill

Status: proposed, awaiting operator dispatch and exclusive isolated-DB slot assignment.
Read [recovery assessment](../recovery-readiness-2026-09-08.md) first. This brief does not
itself authorize execution, retained-data access, infrastructure provisioning or activation.

## Ownership and boundaries

Repository: `/Users/glendonchin/dev/Technology/orimera`. Proposed new worktree:
`/Users/glendonchin/dev/Technology/exulanica-isolated-recovery-drill`, branch
`codex/isolated-recovery-drill`, from operator-selected current local main after this brief is
available there. Record its exact base; if not integrated, ask the operator to select the reviewed
brief commit as the task input without merging it yourself. Reuse only a scope-matching clean
worktree. Migration: **NONE** (apply existing migrations only to owned disposable databases).

Proposed exact repository writable set, requiring dispatch approval:

- New `scripts/verify_isolated_recovery.py`
- New `docs/recovery-drill-2026-09-08.md`
- New `docs/evaluation/2026-09-08-isolated-recovery-drill.json`
- New `docs/evaluation/artifacts/2026-09-08-isolated-recovery-drill/` containing only sanitized
  generated-fixture logs/manifests and the driver's explicit file inventory

Everything else is read-only, including runtime, tests, migrations, README, configuration,
existing evidence and these briefs. If any path already exists, stop for a scoped amendment;
do not overwrite accepted evidence. No production fixes are implied by permission to write a
verification driver. Report the smallest failing function before requesting runtime scope.

The posed-view task exclusively owns the isolated DB/full-suite slot until handoff or release.
Do not claim it, create a database, provision a role or start a test before explicit reassignment.
After assignment, this drill needs one exclusive DB execution slot for sequential owned databases
and targeted tests, **no full-suite slot**. No suites now or later unless separately assigned.
Do not use retained `public`, shared test databases or deployment role names on a shared cluster.
No cloud, models, GPUs, private media, upload, merge or push.

## Gate 0: approve a concrete execution manifest

Before any DB writes, show the operator the driver and manifest naming source commit, exact
PostgreSQL binaries/server/extension requirements, connection aliases without secrets, owned DBs,
roles, output/control directories, tests, cleanup and failure retention. Execution requires
explicit approval of those resources and release of the slot. Do useful driver/source review
before this approval; do not implement a second recovery engine.

Allocate a UUID run token and require identifiers under 63 bytes. Names:
`exulanica_test_rr_<token>_src`, `_dst`, `_v38`, `_upgrade` and `_checks` for database names with
the same prefix. Use a short collision-resistant token recorded in the manifest. Refuse any
pre-existing database and verify current_database/server endpoint before each mutation. New role
names use `rr_<token>_app`, `_ro`, `_purge`; the administrator is an explicitly approved existing
bootstrap principal. Prefer an operator-provided disposable cluster; do not provision a host.

External generated working root: operator-approved absolute `RR_ROOT`, outside the repository and
all retained media roots, newly created for this run. Exact children: `source-data/blobs`,
`restored-data/blobs`, `backup`, `authority`, `control`, `v38-data`, `upgrade-data`, `checks`,
`private-logs`. Checkpoint under `authority`; marker under `control`; neither belongs to copied
DB/object trees. Local directories simulate rollback independence only, not separate devices.
Record this limitation. Real off-device retained custody belongs to the activation task.

Use explicit credential-free libpq service aliases with owner-only credentials outside Git; do
not inherit ambient database or data-directory settings. Do not print secrets in commands,
tracebacks or evidence. A run must refuse non-test names and any target absent from its manifest.

## Driver and commands to validate

Reuse [checkpoint/prepare/replay/verify_restore](../../exulanica/deletion/restore.py),
[role provisioners](../../exulanica/db/roles.py),
[PhotoIngestPipeline](../../exulanica/ingest/pipeline.py) and generated test fixture patterns in
[test_purge](../../tests/test_purge.py) and [test_restore_replay](../../tests/test_restore_replay.py).
Do not call a development ingest CLI merely to populate data: its `_repository` applies pending
migrations. Generate images within the owned root and use scripted model outputs with zero network.

Tool target: PostgreSQL **18.6** clients/server and pgvector **0.8.6**, with pgcrypto, pg_trgm,
btree_gist and uuidv7 available. Assessment found 18.6 clients at
`/opt/homebrew/opt/postgresql@18/bin`; recheck actual installed tools and approved server before
execution. The repository's helper chooses the first existing binary and does not validate its
version; `tests/pg_harness.require_target` checks server >=18 and extension availability, not an
exact pgvector patch. Explicitly measure both. A mismatch blocks the run; do not install/change
shared infrastructure without an amended approval.

These command forms were checked against client help/source, not run against a DB. `PG_BIN`,
service aliases and paths below must first resolve to the reviewed manifest. Never fall back to
an unversioned PATH tool or an ambient database.

```sh
"$PG_BIN/createdb" --maintenance-db="service=rr_admin" --template=template0 "$RR_SOURCE_DB"
"$PG_BIN/createdb" --maintenance-db="service=rr_admin" --template=template0 "$RR_RESTORE_DB"
"$PG_BIN/pg_dump" --dbname="service=rr_source_owner" --no-owner --no-privileges --file="$RR_DUMP"
"$PG_BIN/psql" --dbname="service=rr_restore_owner" --no-psqlrc --set=ON_ERROR_STOP=1 --file="$RR_DUMP"
```

A full logical dump into a new database exercises extensions, partitions and dependencies beyond
the existing schema-only test. Keep source/target schema names the same within distinct DBs; do
not edit dump SQL to rename schemas. Empty target may need dump-policy roles to exist BEFORE
restore even with `--no-privileges`: row-security policies still name roles. Create the manifest's
roles first, then after restore grant them with the same restore/migration owner using
`provision_runtime_role(role=..., read_only=False/True)` and `provision_purge_role(role=...)`.
These helpers operate on cluster roles; tests' `_suite` role names need exclusive cluster access
or a disposable cluster. Default `exulanica-db` provisions deployment role names, so do not use
it on a shared cluster. Explicitly check app/reader are non-owner, non-superuser, non-BYPASSRLS,
reader is SELECT-only, purge holder visibility is complete, and workspace isolation holds.

Source-only checkpoint command, then target-only replay (each with isolated explicit environment):

```sh
python -m exulanica.deletion.restore checkpoint --checkpoint "$RR_CHECKPOINT"
python -m exulanica.deletion.restore prepare --checkpoint "$RR_CHECKPOINT" --marker "$RR_MARKER"
python -m exulanica.deletion.restore replay --checkpoint "$RR_CHECKPOINT" --marker "$RR_MARKER"
```

First uses `EXULANICA_DATABASE_URL=service=rr_source_owner`. Last uses
`EXULANICA_DATABASE_URL=service=rr_restore_owner`,
`EXULANICA_PURGE_DATABASE_URL=service=rr_restore_purge`, and
`EXULANICA_DATA_DIR` naming `restored-data`. Use the selected environment's Python pinned to the
reviewed checkout; no unreviewed CLI name or `--database` option exists. The driver may call these
same functions directly with explicit `Database` and store objects. Approval covers generated
source sealing and generated target purge only. Never use a retained URL to “check” these commands.

## Acceptance sequence

1. Apply current committed migrations in source using `apply_pending`, provision the explicit
   roles and record version/checksum rows. Seed generated live and deletion-target captures,
   spans, graph/aggregate data, current mask/screening and person-consent fixtures. Keep a live
   control so successful recovery must return bytes, not merely deny everything. Record object
   key, byte length and SHA-256, schema checksum list and source commit without private identifiers.
2. Quiesce every driver writer and purger before paired DB dump/store copy. Copy only owned
   generated trees; compute dump and sorted object manifests and cross-check DB live references.
   Preserve both hashes and lengths. Restore verification must compare content, not mtime or ETag.
3. After the backup, resume only the source fixture writer to insert a capture tombstone through
   `IngestRepository.insert_tombstone` and drain the real purge worker. Quiesce again, seal the
   current source, independently retain checkpoint and prepare pending marker. Verify raw SQL
   tombstone insertion is refused while sealed. Source remains sealed until owned cleanup.
4. Restore the earlier DB and objects into the distinct target. Before replay, prove the deleted
   bytes were restored and older metadata lacks the deletion, but API startup refuses pending
   marker before an in-process worker starts. Do not start dedicated workers: their builders
   currently lack this gate. Record that gap, not a passing worker-refusal claim.
5. Replay with the real purge role; verify targeted bytes absent, tombstone guards hold, spans
   return 410, affected aggregates stale and graph excludes deleted content. Receipt must match
   checkpoint digest and attempt ID. Repeat replay on the same target/attempt: no duplicate
   receipt or new tombstone identities. Check every surviving referenced object's hash and size.
6. On a fresh owned restore attempt, inject failure at the existing purger seam after replay
   tombstones commit, following `test_partial_replay_refuses_startup_before_any_worker_can_start`.
   Require pending state, no receipt and API startup refusal. Remove the injection and resume
   the same attempt successfully. Label this an injected interruption, not an observed power cut.
7. Separate negative attempts: corrupt checkpoint digest; missing marker; forged complete marker
   with a mismatched receipt; completed DB jobs paired with older object bytes; shared live holder;
   backup predating a required blocklist/interval capture. Match the specific refusal, never just
   a nonzero process exit. Keep shared holder bytes intact and withhold completion when purge skips.
8. For surviving current assets, remove one generated object and substitute same-length corrupt
   bytes in another copy. Manifest verification must refuse acceptance; `store.get` must raise
   `BlobNotFoundError`/`IntegrityError`. Authenticated reads must not return those bytes (ordinary
   evidence missing=404, integrity=500; mask/geometry paths can have their own 409/424 refusal).
   Record exact route response and reason. Replay/readiness may still succeed: explicitly prove
   that neither certifies all surviving objects. Repair only from verified generated backup and
   rerun the failed check.
9. Start target API with normal `verify=True`, explicit independent
   `EXULANICA_RESTORE_STATE_PATH`, in-process derivative worker off, no model credentials,
   non-owner app and distinct SELECT-only reader roles. Verify live authorized evidence hash,
   masked delivery, deleted refusal, foreign workspace and missing-token refusals, graph/World
   Read behavior, `/healthz`, and every `/readyz` component. No public listener needed: use the
   actual app lifespan with TestClient. Existing `_app` in restore tests uses `verify=False` and
   owner-backed services; that fixture is not production-role proof. Use authenticated readers
   and current asset-policy fixture patterns from [asset tests](../../tests/test_asset_read_currency.py).
10. Add a bounded permission-history control: record a consent revocation/withdrawal AFTER an older
    dump without a tombstone, then checkpoint. Establish the restored dump lacks that receipt and
    checkpoint carries no copy of it. Mark recovery authority incomplete and never serve this
    target as current. This control demonstrates the limit, not a new receipt replay mechanism.
    A frozen-source-loss scenario may pass; active-host-loss after unexported changes must remain
    unproved/refused by the operating procedure.
11. Prepare a separate generated 0038 database by enumerating exact committed migrations through
    0038 with `_apply_one` (its files/record behavior), not deleting or renumbering migrations.
    Exercise dump/restore/replay at 0038 with no API serving claim, then run current `apply_pending`
    on its separate upgrade copy. Require applied list exactly 0039,0040,0041 and final complete
    checksum/version list. This is generated upgrade-path evidence, not a retained upgrade.

After slot approval, the targeted existing module command is
`python -m pytest -q tests/test_restore_replay.py tests/test_deployment.py`, with
`EXULANICA_TEST_DATABASE_URL` explicitly bound to `_checks`,
`EXULANICA_REQUIRE_POSTGRES=1`, and `EXULANICA_POSTGRES_BIN` set. Bind Python to this checkout and
use locked dependencies in an external environment. Review conftest/harness again before launch;
no skipped DB tests count as passing. No full suites. The driver must add the separate-database,
production-role, complete-manifest and 0038 checks beyond the existing tests.

## Evidence, cleanup and approval checkpoints

Gate 1: after driver review, slot assignment and manifest approval, run generated steps above.
No further approval is needed for the precise generated mutations/destruction already approved.
Gate 2: independent reviewer assesses exact responses, hashes, timings, role checks, partial
failures and limitations. A green generated run permits only discussion of retained work.
Gate 3: retained backup/recovery requires the separate activation brief's explicit approvals.

Time dump, copy, retrieval simulation, restore, replay and authenticated verification separately
and end to end. Record local simulation versus actual off-device retrieval. Save driver hash,
commit, versions, command templates, assertions and each negative outcome in the report/envelope.
Sanitize before public evidence is written; no secrets, local private paths or private media.

The drill owner owns cleanup. On success, close connections/processes, delete only manifest-owned
DBs and generated working directories, then remove only roles created by this run after verifying
no dependencies remain. Never use broad DROP OWNED or a filesystem wildcard outside the run root.
Existing tests can leave `_suite` roles: on a disposable cluster remove that owned cluster only
with its approved cleanup; on a shared cluster do not drop pre-existing roles. On failure, retain
only owned targets/logs for review, record their inventory and cleanup owner, and keep all serving
off; do not silently erase the evidence. Explicitly release the slot on handoff.

Return exact base/branch/tip, writable-set diff, executed versus unexecuted criteria, measured
recovery times, refusals, cleanup state, open runtime gaps, and next approval needed. Stage explicit
files; use a one-line imperative commit without trailers or em dash. Do not merge or push.
