# Rehearse and approve retained-data activation

Status: proposed, not dispatched. No retained operation is authorized by this document.
Read the [recovery assessment](../recovery-readiness-2026-09-08.md) and require reviewed
[generated recovery drill](2026-09-08-isolated-recovery-drill.md) evidence first.
The outcome is a recoverable, reviewed activation decision, not a requirement to force deployment.

## Ownership and resource scope

Repository: `/Users/glendonchin/dev/Technology/orimera`. Proposed worktree:
`/Users/glendonchin/dev/Technology/exulanica-retained-activation`, branch
`codex/retained-activation`, from operator-selected current local main with the reviewed briefs
available. Record exact base and selected release image/source digest. Do not integrate README or
posed-view changes yourself. Revalidate relevant changes since the assessed
`8e88b59aadb41088dc5fab185c088e1f36c570b5`; a newer main is not automatically the approved release.

Migration: **NONE allocated or modified**. Existing committed 0039-0041 are the only proposed
pending migrations if fresh retained inspection still establishes a checksum-valid 0038 baseline.
Their execution on retained data is a separate approval, never implied by this brief or branch.

Proposed repository writable set, to be approved at dispatch:

- New `docs/retained-activation-2026-09-08.md`
- New `docs/evaluation/2026-09-08-retained-activation.json`

Everything else is read-only. Public output contains only sanitized phase decisions, checks,
aggregate outcomes and non-sensitive evidence bindings. Private backup, media, checkpoints,
object/hash manifests, tokens, credentials, database logs and private scene identifiers stay in
operator-approved private locations outside this repository. Do not reuse generated evidence's
public directory for retained evidence. Any script/config/runtime change needs a scoped amendment.

No full suite required for this operational task. One exclusive isolated DB slot is needed for
recovery/rehearsal after the posed-view owner releases it and the operator assigns it. Retained
migration additionally needs an exclusive deployment maintenance window and writer freeze.
Neither is assigned now. No cloud provisioning, model calls, GPUs, upload to an unspecified
location, merge or push. Backup transfer is permitted only after approval names its destination.

## Phase A: operator-approved retained backup

First deliver a concrete private execution manifest for review: exact retained endpoint/database/
schema and source code, all object mounts and required workspace binding, all writer/purge
processes and schedules, freeze/exit verification, administrator and runtime identities, compatible
PostgreSQL binaries/extensions, free-space needs, backup destinations, encryption, custodian and
key retrieval procedure. Name the independent reviewer and person permitted to reopen traffic.
Use a fresh run ID and owned private directories; no ambient URL or data-dir fallback.

Choose off-device backup destination, independent authoritative-checkpoint custody, secret recovery,
retention and deletion policy, measurable RPO/RTO and failure notifications. The assessment's
7 daily/8 weekly, 24-hour ingest RPO and 4-hour RTO are proposals, not installed policy or evidence.
Deletion/permission coverage cannot be traded for ingest RPO. If ongoing host-loss recovery is a
release requirement, resolve the missing durable history before approval; do not certify it from
an old checkpoint. Private storage availability and key custody are operator inputs, not facts to
invent or infrastructure to provision opportunistically.

**Approval A authorizes only** the named retained read/dump/object-copy/approved transfer and
maintenance freeze. It does not authorize source checkpoint sealing, purge, migration or reopening.
After approval, block traffic/admission, stop API plus internal worker, dedicated derivative/scene
workers, purge processes, ingest/export/reconstruction scripts and administrative writers. Prevent
restarts. Verify processes exited and active transactions and store writes ended. Keep that freeze
through phases B-D; if the operator cannot support the downtime, pause for a separately reviewed
alternative instead of quietly resuming writes.

Read-only inspection now establishes actual schema/checksums and counts. Historical 0038 / 284
captures / 880 artifacts / 5 scenes / 0 person regions is only a dated reference. If actual state
or checksum differs, stop and amend the rehearsal plan. Record source image/code and runtime roles
without credentials. Use matched PostgreSQL 18 tools; assessment found 18.6 Homebrew clients,
not a fresh server measurement. Verify exact server and pgvector version (target 18.6 / 0.8.6 as
in the generated drill) before adopting its results.

Take a logical dump with the approved complete-view administrator and a matching frozen object
snapshot. Preserve extensions, embedding partitions, sequences, policy dependencies and required
workspace binding. A schema-only dump requires explicit extension/dependency setup; prefer the
full isolated-database restoration exercised by the drill when the retained DB boundary permits
it. Never dump unrelated schemas simply to satisfy that preference. Record boundary UTC, checksum
manifest and dump digest, object keys/sizes/hashes and intentional cache/scratch exclusions in
private evidence. Verify off-device retrieval and decryption using separately held keys. Copying
live PGDATA, copying only blobs, or hashing only filenames does not meet acceptance.

## Phase B: separately approved checkpoint and isolated recovery

Review the completed backup inventory before **Approval B**, which names permission to seal the
retained source, create an independently held checkpoint, restore private bytes into specifically
named isolated destinations, and purge ONLY those restored copies. Explicitly acknowledge that
sealing mutates retained `restore_control` and that the source remains offline/sealed afterwards.
An existing unfinished checkpoint is an incident to inspect, not a row to clear.

Use unique run-owned `exulanica_test_activation_<token>_restore` database/store and separate
`_upgrade` target with no shared retained paths or running workers. Role names are run-specific on
a shared cluster; the approved administrator/restore owner provisions app, SELECT-only reader and
purge roles. Dump policy role names can require precreation before restore. Use the same owner
for restoration, migrations and default grants. Do not overwrite deployment passwords using
`exulanica-db` on a shared cluster as a shortcut for isolated role setup.

Call the reviewed `checkpoint()` on the still-frozen retained source. It writes prepared envelope,
commits a source seal, then writes sealed envelope; it is not a read-only export. Verify the file
and transfer it to the approved independent authority location outside both DB/object backup
failure domains. Preserve full tombstone and archived purge target coverage privately. Complete
custody/freshness proof before using the checkpoint. Source writes remain forbidden.

Create pending marker on a separately preserved control path BEFORE restoring any target bytes.
Restore the phase-A dump and objects using the tool/function forms verified in the generated
brief, then verify the complete manifest and provision isolated roles. At 0038, require the
specific generated 0038 replay compatibility result; do not infer it from a latest-schema test.
Do not start current API against 0038 merely because `verify_schema()` tolerates pending files.
Replay with the administrative target URL, separate target purge URL and exact target object root.
Require matching marker/receipt, no incomplete purge, absent targeted bytes, preserved live bytes
and accounted stale aggregates. A refusal stops progression; never bypass it to fit an RTO.

The frozen backup and checkpoint must cover the same authoritative permission boundary. If any
consent, review, withdrawal or deletion changed after the dump, stop: a fresh tombstone checkpoint
alone does not replay the separate consent history. Retake an authorized coherent snapshot or
obtain a separately implemented and reviewed authority-preservation mechanism. Do not repair
historical grants or synthesize missing permission records.

Retained recovery does not authorize corruption/unlink experiments on the retained source.
Generated negative controls already exercise interruption and corrupt/missing-object refusal.
Any further destructive negative control on a private restored copy must be named in Approval B;
otherwise perform positive manifest/replay checks only. Keep all isolated listeners restricted.

## Phase C: rehearse the actual 0038-to-0041 upgrade

**Approval C** permits only migration and resulting verification on the named recovered isolated
copy, with all other writers stopped. Keep the verified pre-upgrade backup and private evidence
unaltered. Create the independent `_upgrade` copy through the reviewed dump/restore/marker/replay
procedure, not a raw hot directory copy. Freeze all sources while making it. Verify its 0038
version/checksums before running `apply_pending` from the exact candidate package. Provision
roles under the same owner, with the explicit isolated names. A rehearsal that only applies
0001-0041 to an empty database does not satisfy this phase.

Expected existing migrations:

| File | Operational effect to check |
| --- | --- |
| [0039](../../exulanica/migrations/0039_training_is_a_separate_permission.sql) | Separate training consent table/constraints, training export profile and terms, shared source mutation locks. Historical memory exports must retain original profile/bytes. |
| [0040](../../exulanica/migrations/0040_bind_geometry_admission_to_current_privacy_inputs.sql) | Current privacy input bindings, mask lineage checks, READ COMMITTED requirement and consent sequence ambiguity refusals. Old receipts are not automatically made current. |
| [0041](../../exulanica/migrations/0041_guard_asset_reads_with_current_permission.sql) | Global delivery barrier with try-lock writer rejection `40001`, current asset authorization and training-source-before-privacy lock order. |

`apply_pending` applies each SQL file with its own transaction and records checksum afterward
([runner](../../exulanica/db/migrate.py)). The initial advisory transaction does not hold a lock
across the whole multi-file run; each SQL migration takes its own lock. Keep a single migration
owner/process. A SQL commit before a missing checksum insert is possible; do not assume a failed
command rolled back the whole upgrade or blindly rerun it. Inspect actual schema and recorded
checksums and stop for a repair decision. No reverse migration exists.

Require reported applied list exactly `0039,0040,0041`, complete ordered 0001-0041 version list,
and every stored checksum matching candidate files. Verify role grants/RLS and preserved data
with private before/after manifests, accounting separately for authorized deletion replay effects.
Start the upgraded isolated API only with normal schema/role verification, explicit independent
restore marker and app/reader roles. Keep workers off initially. Exercise authenticated graph,
source-media, evidence, geometry and World Read; missing token/foreign workspace refusals, live
byte hashes and expected unavailable legacy assets all need concrete recorded results.

Expected refusals are not permission to loosen guards: historical screening lacking current
`privacy_inputs`, stale masks/geometry lineage, withdrawn/expired consent, and receipt/column
timestamp disagreement remain unavailable. The consent timestamp integration fixes future writes;
it provides no historical normalization. Zero person regions is not evidence that photographs
contain nobody. Masked splat production remains unsupported; do not rebuild or re-screen personal
media under an activation permission. Release remains `internal_only`.

Check `/healthz` separately from `/readyz`; compare complete migration checksums independently.
The readiness object probe does not validate actual media, and “worker off” does not prove an
external worker is draining. If worker activation is in the approved plan, name exact workspaces/
jobs, stop/restart control, queue baselines, lease expiry/reclaim behavior and expected refusal
states. Model-disabled delivery smoke must not accidentally launch MoGe, COLMAP or hosted vision.
Do not start all Compose services to run these checks: Compose's migrate service auto-applies
pending files and its workers restart independently.

Exercise contention/retry behavior on generated fixtures, not by creating real consent changes:
0041 can raise `40001` across workspaces; retry the entire transaction with bounded backoff after
rollback, including sequence allocation and authorization reads. Distinguish retry exhaustion,
legacy ambiguous-consent `40001` (not cured by blind retries) and unexpected `40P01`. The actual
`add_consent` route handles `PrivacyAdmissionError` but has no generic serialization retry loop;
do not promise transparent API retry. Review each selected writer's caller behavior and withhold
concurrent writer activation if retry handling is not demonstrated. A required runtime retry fix
must receive its own exact writable scope and validation task.

## Phase D: evidence review and recovery decision

No automatic promotion from rehearsal. The reviewer receives exact base/image, private backup
and checkpoint custody confirmation, manifest verification, measured retrieval/restore/replay/
upgrade/read timing, role proofs, all failures and explained legacy refusals. Record cleanup and
source sealed state. Missing complete deletion/permission authority, bad bytes, role violations,
partial migrations or unresolved replay is a stop, even if health endpoints are green.

**Approval D selects whether to proceed to retained change** and names acceptable limitations,
maintenance duration, smoke scope, recovery target/code, operator and reviewer. It must explicitly
resolve host-loss readiness: either prove a complete independent history for the required mode,
or document that deployment recovery is restricted to a frozen authority boundary and do not
claim unattended active-write disaster recovery. Approval cannot manufacture missing proof.

## Phase E: separately authorized retained migration and smoke

**Approval E** must explicitly name retained migration 0039-0041, any retained-source
prepare/replay/purge needed to complete its seal, its expected aggregate invalidation/destruction,
role provisioning, and the bounded smoke/read operations. Approval of isolated recovery never
authorizes retained purge. If purge/replay of the source is unacceptable, keep it sealed and
review a replacement cutover instead; there is no benign “unseal” command.

Reconfirm source freeze and unchanged snapshot/checkpoint boundary; if changed, return to phase A/B.
Follow the rehearsed order: source prepare/replay at 0038 with separate purge role and independent
source marker, verify completion, then run the approved migration as the same bootstrap owner
and provision roles. All writers remain stopped between replay completion and migration. If the
rehearsal proved a different necessary order, amend Approval E before execution rather than
improvise it on retained data. Use `exulanica-db` with no subcommand only when its default deployment
role provisioning is expressly approved; its parser does not accept `provision` or a target version.

Verify full schema/checksums and expected retained counts, role safety, marker/receipt and live
object integrity. Start only the intended API with independent marker wiring and workers disabled,
then execute approved authenticated read smoke checks. Any write smoke uses an explicitly approved
isolated generated workspace and cleanup plan; “smoke” alone grants no personal-data modification.

**Approval F separately reopens traffic and the named workers**, after results are reviewed. Keep
purger credentials confined to the approved purge path. Record changed queues, actual worker
progress and failures; graceful-stop timeout is not successful quiescence. No model execution,
re-screening, new training permission, legacy repair or public redistribution follows implicitly.

## Failure, rollback and cleanup

Before retained writes, abandon an isolated candidate safely, preserving review evidence; the
source remains frozen/sealed. After any committed retained migration there is no assumed down
migration or safe code-only downgrade. Recovery uses the verified paired snapshot in a fresh
target, independent pending marker and CURRENT complete deletion/permission authority, then a
reviewed compatible code version. A pre-upgrade code image has not been selected by this brief;
it must be proven compatible in rehearsal before being called a rollback option.

After traffic resumes, old phase-A data cannot be restored as current if later deletions or
permission changes are missing. Freeze, preserve current authority if the source survives, and
review a new restore attempt. If the host and unexported authority are lost, keep serving disabled.
Never clear marker/control records, invent missing bindings, normalize receipts, or disable
triggers to make restoration pass. A partial migration needs inspection before retry or recovery.

The activation owner cleans only named isolated databases, roles and private working copies after
review and according to approved retention. Do not delete retained backups/checkpoints or source
volumes as routine scratch cleanup. Record remaining copies and their custodian; expired backup
versions require the approved private-data destruction process. Release the DB slot and maintenance
window explicitly. Return exact branch/tip, executed phase approvals, evidence outcomes and the
next unapproved action. Stage explicit public files, use a one-line imperative commit without
trailers or em dash, and do not merge or push.
