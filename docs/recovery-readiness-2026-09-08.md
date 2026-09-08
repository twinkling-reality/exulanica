# Recovery readiness assessment, 2026-09-08

Status: source-grounded assessment; retained recovery and activation are unexecuted.
Exulanica has working offline deletion-replay machinery exercised by generated-fixture tests.
It does not yet have demonstrated deployment recovery or a demonstrated durable history that
can preserve all later deletions and permission changes after loss of the original host.

## Scope and evidence boundary

Assessment base: `8e88b59aadb41088dc5fab185c088e1f36c570b5`, current local main when this task
created `/Users/glendonchin/dev/Technology/exulanica-recovery-readiness` on
`codex/recovery-readiness`. The brief's older `46e106b` baseline was not used as the branch base.
The subsequent dispatch at `40fe6492513599cb401b503bd8ef6b87bba2428b` reserves the DB/full-suite
slot for the posed-view owner; this assessment does not need that slot or a rebase.
Migration: **NONE**. No migrations allocated, edited or executed.

Exact writable set, all new:

- `docs/recovery-readiness-2026-09-08.md`
- `docs/briefs/2026-09-08-isolated-recovery-drill.md`
- `docs/briefs/2026-09-08-retained-activation.md`

The README and posed-view work remain separately owned. Main being pushed protects committed
Git history, not databases, objects, credentials or other branches. The last independently
reported retained public state was schema 0038, 284 captures, 880 artifacts, 5 scenes and zero
person regions. This is a dated observation from the
[consent integration](integration-consent-timestamp-2026-09-08.md) and
[asset integration](integration-asset-read-currency-2026-09-08.md), not a measurement made here.
Their historical “main unpushed” wording does not describe the later dispatch state.

## Recovery inventory

| Boundary | Configured/implemented | Evidence and limits |
| --- | --- | --- |
| Database | [Compose](../compose.yaml) selects `pgvector/pgvector:0.8.6-pg18`, database default `exulanica`, named `pgdata` at `/var/lib/postgresql`. [Database.from_env/session/unscoped](../exulanica/db/session.py) reads `EXULANICA_DATABASE_URL`, uses UTC, scopes workspace sessions and has no fallback or pool. | Configuration, not inspection of a running retained server. Compose named volumes are local persistence, not off-device backups. Runtime app/reader URLs differ from bootstrap owner. |
| Objects | [build_services](../exulanica/api/services.py) and worker builders use `LocalContentAddressedStore(resolve_data_dir()/"blobs")`. [resolve_data_dir](../exulanica/env.py) defaults to `.exulanica/local`; Compose mounts `media` at `/var/lib/exulanica`. | Actual implementation is local filesystem. No configured remote destination, transfer job or object backup schedule found in the inspected configuration/scripts. |
| Object integrity | [LocalContentAddressedStore](../exulanica/store/local.py): `put_bytes`/`put_stream` use content keys `sha-256/aa/bb/<digest>` and atomic replacement; `get` hashes bytes, `exists` only tests a file, `open` does not hash. `_LocalPurger.purge` unlinks. | Read-only file mode is a policy speed bump, not immutable storage. A directory copy alone proves neither DB/object consistency nor completeness. |
| Additional local state | [ingest CLI](../exulanica/ingest/cli.py) uses `workspace.txt` and a model-response cache; scene worker uses `reconstruction-scratch`; Compose places HF model cache on the media volume. | Snapshot scope must distinguish authoritative objects/workspace binding from replaceable model downloads and potentially sensitive scratch/cache files. No private contents inspected. Training/model checkpoints are not deletion checkpoints. |
| Deletion checkpoint | [checkpoint](../exulanica/deletion/restore.py) exports all visible tombstones and archived purge target refs under an administrative complete view; commits a source seal and writes an immutable-path digest envelope. | No configured location, off-device custody, schedule or retained execution established. Hash binds bytes, not authenticity or freshness. It is a database write and a source seal. |
| Restore control | `prepare_restore` writes pending marker; `replay` completes DB receipt and external marker; `verify_restore` compares them. [0036](../exulanica/migrations/0036_restore_tombstone_replay.sql) defines gates. | Marker must survive replacement of BOTH database and object backup domains. CLI accepts arbitrary paths and does not establish that separation physically. |
| Secrets and deployment reconstruction | [Compose](../compose.yaml), [role provisioning](../exulanica/db/roles.py), [deployment sections 5/9](deployment.md) require runtime credentials, token directory and deployment decisions. | No key recovery, off-device secret escrow or complete one-command redeploy established. Never put secret values, private dumps, media or sensitive manifests in public Git. |
| Tests | [test_restore_replay](../tests/test_restore_replay.py) `_backup` invokes real `pg_dump`; `_restore` invokes `psql` and copies generated object bytes. [test_deployment](../tests/test_deployment.py) checks configuration/import contracts. | Existing generated-fixture evidence, not a nightly retained dump restored on replacement infrastructure. No tests rerun by this assessment. |

[Deployment](deployment.md) sections 2-4 describe a proposed remote origin and nightly dumps;
section 5.2 explicitly says those object-store settings are not read by runtime code. Sections
9.4 and 11 leave deployment restore open. These statements coexist with real fixture restore
machinery: “no restore implementation” would be false. Section 4's public permanent asset caching
is not the present private recovery/read path: [evidence routes](../exulanica/api/routes/evidence.py)
use authenticated policy checks and `private, no-store`. Do not expose recovered private assets
through the proposed anonymous origin. [Runtime verification](runtime-verification.md) records
platform calls and generated rehearsal evidence, not a host-loss recovery exercise. External
platform availability/pricing was not reassessed here.

## Actual restore and startup path

[restore.main](../exulanica/deletion/restore.py) exposes the Python module actions `checkpoint`,
`prepare`, `replay`; no `exulanica-restore` console entry exists in
[pyproject.toml](../pyproject.toml). Replay reads **`EXULANICA_PURGE_DATABASE_URL`**, despite its
parser error saying `PURGE_DATABASE_URL`; [env_get](../exulanica/env.py) prefixes the name.

`checkpoint()` takes ACCESS EXCLUSIVE on tombstone, writes prepared file, commits sealed control,
then marks the file sealed. A crash can leave an unusable prepared file or sealed source; do not
edit either into an apparent success. Its 0036 trigger refuses new tombstone INSERTs while
sealed, not every table mutation. Keeping all writers stopped is an operator obligation.

`prepare_restore()` creates a fresh attempt UUID and pending file before any restore. `replay()`
requires superuser/BYPASSRLS complete view for administrative work; it re-inserts originals and
stable per-attempt replay tombstones, requeues both identities' purge jobs, retains archived
object refs, and invalidates every derived aggregate in affected workspaces. Transactions can
commit before completion, making interrupted replay resumable but unsuitable for concurrent use.
[PurgeWorker.drain/_destroy](../exulanica/deletion/worker.py) validates the separately provisioned
purge role's cross-workspace holder visibility, locks content objects, checks release permission,
unlinks, verifies absence, then records completion. Shared live holders, failed/skipped/exhausted
jobs or missing capture bindings refuse completion. A backup older than a blocklisted/interval
capture cannot reconstruct its required binding merely from the tombstone checkpoint.

Replay checks purge completion and absence of targeted bytes before issuing its receipt. It
**does not verify every surviving object** or recover later non-tombstone permission receipts.
Presentation consent goes through [record_consent](../exulanica/ingest/person_review.py),
[IngestRepository.insert_person_consent](../exulanica/ingest/repository.py), and
[spine.insert_consent](../exulanica/ingest/spine/person_consent.py), which inserts the consent
receipt, not a tombstone. Migrations 0037/0039 add separate presentation/training consent history.
An older dump plus a fresh tombstone checkpoint therefore cannot certify current consent after
such history changed. Test this gap explicitly; do not silently translate a receipt into a
new tombstone or present old grants as current.

[API _lifespan](../exulanica/api/app.py) verifies schema checksums/role, then restore state, then
starts the in-process worker. [build_services](../exulanica/api/services.py) reads optional
`EXULANICA_RESTORE_STATE_PATH`; Compose does not pass or mount it. If a pre-checkpoint DB has no
control row and the marker is omitted, `verify_restore()` cannot detect the rollback. Marker
configuration is mandatory operationally for a recovered instance, although optional in code.
It must be available at an independently mounted control path before boot.

The dedicated [derivative builder](../exulanica/ingest/worker_command.py) and
[scene builder](../exulanica/ingest/scene_worker_command.py) check schema/role but do NOT call
`verify_restore`; scene startup also cleans scratch. The [purge CLI](../exulanica/deletion/cli.py)
does not provide that gate either. [ingest._repository](../exulanica/ingest/cli.py) even calls
`apply_pending`. Thus stopping only the API, or setting its in-process worker off, is insufficient.

Another distinction: [verify_applied](../exulanica/migrations/__init__.py) accepts pending files;
`verify_schema()` alone is not a latest-schema assertion. [readyz._schema_check](../exulanica/api/routes/health.py)
compares the entire version list. Its `_store_check` only calls `exists` on an all-zero key and
ignores the boolean; this is weaker than deployment section 6.2's “HEAD on a known asset”. A green
readiness result does not prove any recovered object's integrity or external worker progress.

## Coherent snapshot and recovery procedure

This is a proposed authorized procedure, not actions performed here.

1. Operator identifies database/schema, every store mount, current code/image, writer processes,
   scheduled jobs and administrator access. Block traffic and admission; stop API including its
   internal worker, dedicated derivative/scene workers, ingest/reconstruction/export jobs, purge
   commands/threads and administrative writers. Disable automatic restarts. Wait for actual
   process exit and transactions/object operations to finish. A shutdown timeout or lease expiry
   is not proof of quiescence; stop and investigate before copying.
2. While the same freeze remains in force, take an administrative complete-view logical dump
   with schema/partitions/extensions accounted for and copy the matching content store plus
   necessary workspace binding. Do not copy live PGDATA as a substitute. Record UTC boundary,
   migration file/record checksums, selected image/source, object key/size/SHA-256 manifest, dump
   digest and explicit exclusions. Validate referenced non-purged object coverage; surplus and
   deliberately purged objects need explained accounting. Hashes and identifiers may themselves
   be sensitive, so retain full manifests privately.
3. A routine coherent backup does not require calling `checkpoint()`. If the next operation is
   recovery, keep the source frozen and obtain separately authorized checkpoint sealing, then
   retain the authoritative envelope outside both backup domains and off the source device.
   For recovery of an older backup, obtain the current checkpoint after all later deletions, and
   separately establish that later consent/review changes are covered. Otherwise refuse serving.
4. Prepare independent pending marker before restoring into an empty isolated target. Restore
   dump and matching bytes, rebuild roles under the migration/restore owner, verify full object
   manifest, replay with administrative and separate purge credentials, verify receipt/marker,
   then exercise authenticated reads as real non-owner app and SELECT-only reader roles.
5. Leave the original source frozen. Completing replay on a different target does not unseal the
   source. There is no read-only “unseal” operation. If resuming the original is selected, it
   needs its own explicitly authorized prepare/replay cycle and may purge bytes/invalidate
   aggregates; never manually clear control rows. Alternatively keep it sealed and approve a
   verified replacement cutover. Every later recovery after resumed writes needs current proof.

For a pre-deployment window, keeping the source frozen from backup through review avoids an
uncovered permission-change interval. It is operationally costly and must be approved as such.
A fresh coherent backup after permission changes covers them only through its own boundary.

## Original-host loss and decisions still required

If the host dies before a fresh checkpoint, the latest independently held checkpoint covers only
its sealed history. No inspected caller exports an ongoing authoritative tombstone/consent journal,
and no WAL archiving/PITR or remote deletion replication is configured in Compose or the searched
scripts. A backup can resurrect later deleted data; a locally held checkpoint can disappear with
it. A valid old digest/receipt cannot prove no later requests existed. Refuse public serving
unless independent complete current authority can be established. A simulated frozen-source loss
can be drilled now; recovery after arbitrary resumed activity cannot be certified by this machinery.

| Operator decision before retained work | Proposed starting point, not an existing fact |
| --- | --- |
| Backup destination | Private encrypted off-device storage, with exact provider/device, account, region, endpoint, access and failure domain approved. A second independent copy if loss of the first destination must be tolerated. No provisioning authorized here. |
| Checkpoint/control custody | Independently retained checkpoint outside DB/object rollback domains, plus attempt marker on a separately preserved control path. Record custodian and how a replacement host retrieves and authenticates them. |
| Retention/deletion policy | Candidate 7 daily and 8 weekly backups for the 46-day window, subject to explicit privacy/retention approval. Keep required authority for every restorable backup; retire all affected backup versions under an approved deletion policy. These counts are not configured schedules. |
| Keys and credentials | Separate encrypted secret custody with a named primary/backup operator; test decryption and credential recovery without the original host. Keep decryption keys outside the backup and public Git. Rotate compromised credentials; don't blindly restore old tokens. |
| RPO | Candidate 24 hours for ordinary ingest, reflecting deployment section 9's proposal. No tolerated resurrection of deletions or permissions: proof coverage must reach the recovery authority boundary. Current implementation cannot promise that after active-host loss. |
| RTO | Candidate 4 hours end to end, including key retrieval, download, hash verification, restore, replay, role setup and authenticated validation; measure before accepting. “Hours” in deployment docs is not a timing result. |
| Cadence and accountability | Name backup operator, restore operator, independent reviewer, failure alert recipient and review cadence. Schedule/freshness monitoring remains unknown until configured and exercised. |

Smallest follow-up gaps, not authorized implementation: worker builders above lack the existing
restore gate; Compose lacks marker wiring. These can remain procedural isolation controls for
an offline drill. Full survivor validation belongs in a bounded drill driver using `store.get`,
not a claim about `replay`. Crash-safe deletion/permission durability needs a separate design at
`checkpoint`'s tombstone-only export and the actual consent writers, including commit/export crash
windows and missing bindings. It is indispensable only for the stronger active-host-loss claim;
no broad backup framework is proposed by default.

## Assessment acceptance and handoff

Executed: read the complete brief and applicable supplied AGENTS instructions; checked ancestor
AGENTS paths and repository inventory (no additional AGENTS.md found); created the specified
worktree from local main; read the required deployment/runtime/integration files, Compose,
migrations 0036-0041, DB/session/restore/store/worker files and tests; followed CLI, startup,
role, health, consent and test-harness callers. Inspected PostgreSQL client binary metadata and
side-effect-free help: `/opt/homebrew/opt/postgresql@18/bin/{pg_dump,psql,createdb}` all report
18.6 (Homebrew). Validated proposed dump/restore flags against this help and Python actions
against parser source without importing/starting services. Checked documentation paths, writable
set and diff whitespace before committing.

Not executed: DB connections, retained measurements, dumps, copies of private data, checkpoint
seals, restores, migrations, worker starts, object enumeration, model calls, infrastructure work,
suites, merge or push. No DB or full-suite slot consumed. Installed client version is not a live
server/version/extension measurement. Existing test source and historical results remain distinct
from new execution evidence.

Reviewable successors:
[isolated generated recovery drill](briefs/2026-09-08-isolated-recovery-drill.md) and
[retained activation](briefs/2026-09-08-retained-activation.md). Neither is dispatched by this report.
The former needs explicit isolated-DB slot release/assignment and generated-data execution approval;
the latter has additional private-data and retained-write gates. Commit tip is returned in the
handoff rather than embedded recursively in its own content.
