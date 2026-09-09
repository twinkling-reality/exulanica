# Asset-read currency

Final acceptance at source head `03501cea376cf530c185e3b12a5fb0d8d8d7acdf` passed 2118 backend
tests (3 skipped), Ruff, all 4 import contracts, web typecheck and boundaries, and 876 web tests.
The locked pose/reconstruction environment was installed. Six negative controls failed at their
own exact selectors. The [executed record](evaluation/2026-09-08-executed-asset-read-currency.json)
binds the route-to-byte evidence; the [verification record](evaluation/2026-09-08-verification-asset-read-currency.json)
records digest checks and the second unsuccessful recorder attempt without changing accepted records.
Runtime source remains identical to that tested head. The recorder was subsequently corrected
at `b845bad6cfc8962b1550fb03c6f73d7aabb3f88f` under the `520a192` evidence-repair approval.
Independent integration caught personal checkout prefixes in retained command arguments because
the original full gate ran before envelope generation. The two unpublished candidate envelopes
were regenerated through the recorder with normalized command provenance, replaced hashes and
the independent failure retained. Accepted historical records were preserved. Post-generation
retained-record checks now run after writing the candidate, including after dependent bindings.
Migration 0041 was exercised only in disposable test schemas; retained database activation, merge
and push remain unperformed.

Migration 0041 implements the scope approved at `6270115`, with the single existing viewer-URL
assertion update approved at `6d12621`. Original/crop/by-URI image delivery now refuses current
mask requirements, withdrawal and missing capture identity. Permitted originals retain exact
bytes; no route substitutes a mask under an original digest. Image track identity is checked even
when MIME metadata is missing. Ordinary non-image citations do not acquire geometry prerequisites.
All new viewer image references use `/masked`, including no-person captures.

## Current read contract and lineage

`/masked` selects an exact current persisted derivative using 0040's input-digest matcher through
0041's explicit-time read policy. Missing, obsolete or purged required masks refuse. World source
metadata checks the same selection and verifies the selected stored bytes; unavailable sources
retain live capture IDs for manual review but no asset reference. Deleted sources lose review
identity. The current schema's unique live-capture index rejects duplicate live mappings. The read
predicate nevertheless refuses disagreeing mappings rather than choosing a permissive one by order.
A missing capture mapping is not an empty, reviewed person inventory.

Point-map metadata omits policy-refused artifacts. Direct-ID delivery verifies the artifact's own
source, read-source digest, screening and exact buffered row; a current mask for the capture is
insufficient. Missing legacy screening lineage refuses. A null read-source means the original,
as defined in 0037; it is accepted only when that artifact's persisted screening and actual source
support current permission. A rebuilt mask does not rebind historical geometry.

Scene geometry checks the persisted pose manifest and exact per-capture frame digests against the
job's recorded point maps and their read-source digests. The current pose, gate, placement, job
and active assertion bindings must remain the buffered bindings. Trained delivery additionally
checks the training manifest's pose digest/source list and the gate-named publication receipt.
Missing, purged or withdrawn lineage refuses. `/graph` retains review metadata for refused scenes
but removes placements, recovered cameras and trained assets. World Read scene/place and sparse
observation responses with embedded geometry refuse when those recorded inputs are unavailable.
No new wire state or schema was added.

The generated scene tests execute real publication/controller/store paths with scripted COLMAP
and training outputs. They establish delivery/lineage behavior, not measured reconstruction quality.
The real mask stage rebuilds a changed source in that test; its old trained asset remains refused.
Masked splat production still refuses at the existing producer's missing held-out-remap seam and
is not implemented or represented as a successful masked training run here.

## Authorization instant and transaction-wide ordering

Snapshot metadata remains REPEATABLE READ READ ONLY. 0041's explicit-time predicates do not invoke
the admission lock or replace snapshot consistency with fresh per-query reads. A metadata result
is true of its snapshot and is not a capability for later bytes.

Each byte-serving operation first buffers and hash-verifies local bytes. It then opens a separate
READ COMMITTED READ ONLY transaction, acquires the asset barrier in its own statement, and obtains
one database timestamp in a subsequent fresh statement. That is the successful authorization
instant. All final input/permission comparisons use it. Graph and World Read also reauthorize their
buffered embedded geometry after closing the metadata snapshot. Successful graph/World Read responses
and evidence/geometry bytes carry no-store cache policy. Each evidence range request reauthorizes;
point-map and trained routes keep their existing whole-body/Accept-Ranges-none behavior.

The final check takes only the global asset barrier, never a training, privacy or object-purge lock.
It performs no store read, streaming or network operation while holding that barrier. Writers that
committed before it acquired the barrier are visible. A writer or expiry ordered afterward affects
later requests and cannot retract the already-authorized response. Network completion is not the
linearization point. Buffers are local to the request, not transferable permission tokens.

Dependency mutations take the shared side of the global barrier with **try-lock**, retaining it
through commit. If a reader already owns the exclusive barrier, mutation raises retryable 40001
rather than waiting while holding another lock. This prevents a cycle even when a caller acquired
training, privacy, row or purge locks before its first relevant mutation. The reader can wait for
an existing writer but holds none of those other locks. A writer already owning its shared barrier
can finish cascades while a reader waits. The deliberately global barrier covers old/new workspace
moves and global stage mutations without scanning workspaces through RLS. Its cost is brief
cross-workspace contention, potentially a retry for an unrelated mutation; it is not a per-capture
throughput claim. Applications must retry the whole failed transaction, not its final statement.

The audit also reproduced a pre-existing training/source inversion through the actual
`export_training_dataset` and `record_consent` callers: export held training-source and awaited
privacy, while consent held privacy and awaited training-source, producing 40P01. 0041 replaces
only `privacy_currency_lock` to acquire training-source shared **before** privacy. The same helper
covers an earlier admission/read within a writer's transaction, not merely the INSERT trigger.
The source-before-privacy order matches export's exclusive source lock. Training's package lock
remains separate and unchanged; its consent writer does not wait for privacy. Object purge locks
are never acquired by delivery, and a purger's subsequent metadata mutation try-locks the barrier.
The executed interleavings cover the actual export/consent callers, expiry during a wait, a committed
region edit before the final check, tombstone cascade completion and an already-held purge lock.

## Dependency writer inventory

All INSERT, UPDATE and DELETE events on these existing tables have the same barrier trigger:

| Dependency | Tables and relevant writer paths |
| --- | --- |
| Source identity and physical availability | `capture`, `blob`, `evidence_span`, `media_track`: intake, direct SQL, deletion, purge metadata, old/new workspace moves where the existing role permits them |
| Current presentation state | `person_region`, `person_presentation_consent`, `person_subject`: review/consent commands and direct SQL; 0040's append-only and sequence protections remain |
| Withdrawal reachability | `tombstone`, `occurrence`, `entity_link`, `entity`, `person_derivative_dependency`: identity/occurrence writers, person dependency triggers, tombstone cascades and future dependencies |
| Persisted geometry and authority | `artifact`, `assertion`, `capture_reconstruction_authorization`, `reconstruction_privacy_screening`: producers/publication, admission, invalidation, direct SQL and purge |
| Scene/job identity | `reconstruction_scene`, `reconstruction_scene_member`, `reconstruction_scene_job`, `reconstruction_scene_job_member`: scene admission, leased publication and cascades |
| Place dependency identity | `place`, `place_version`, `place_alignment`: place admission/alignment and existing immutable rows |
| Global producer definition | `stage_registry`, `stage_definition`: registry writers affect current mask matching; global rows use the same barrier without a workspace lookup |

These triggers do not grant writes or relax any existing append-only, RLS or role rule. Direct
partition writes inherit the row triggers. TRUNCATE/DDL is not a runtime privilege or part of the
concurrent delivery contract; administrative migration requires separate deployment control.
Training-use package consent is a separate export permission, not silently repurposed as viewer
permission. Runtime evidence tests configure actual `exulanica_ro` connections and assert SELECT-only,
non-owner/non-superuser/non-BYPASSRLS access; they do not use the service's writer fallback.

## Retained evidence and activation limits

The recorder's acceptance run retains labelled generated original media, request/response
status and SHA-256/size observations, response bodies, persisted artifact lineage and stored
objects. Its killed controls require their own exact pytest selector's FAILED line. Mask lineage,
point lineage, original authorization, final buffering check, delivery locking and training lock
order have separate executed controls; the two original-route controls remove the same shared
original guard and establish only their named local claims.

Run `scripts/record_asset_read_currency_evidence.py --output docs/evaluation/NEW-asset-read-currency.json
--artifacts docs/evaluation/artifacts/NEW-asset-read-currency --full-gates` for a fresh envelope.
The envelope has exactly `profile`, `record`, `record_sha256`, no floats, digest/size file bindings,
and `predecessor_record` pointing to the screening-currency integration record. It also binds the
unchanged accepted checkpoint and intermediate logs. It is written only after the required
commands and exact-selector controls pass. The first full backend run (2112 passed, 3 skipped,
one old-URL assertion failure), fixture mistakes, scene-envelope comparison correction and actual
training deadlock baseline remain retained; none is described as final acceptance.

The task owns the orchestrator-assigned isolated/full-suite slot until handoff. The only test URL
is `postgresql://localhost:5433/exulanica_spine_test`; test schemas are disposable. Full gates include
locked pose/reconstruction extras, all backend tests, Ruff, four import contracts and web typecheck,
boundaries and tests. Source binding in the executed record identifies the exact tested code head;
subsequent evidence commits are not a claim to have tested different feature code.

No retained-public migration, activation, personal-media run, hosted model, GPU spend, merge or
push occurred. Retained public still needs explicit authorization and verification before deploying
code requiring 0039/0040/0041. This is not recipient-checkable World Read release evidence or an
external cache/offline revocation system. Already delivered bytes cannot be revoked by this guard.
Unresolved surfaces outside this implementation are generated-model asset delivery/conditioning
metadata, offline/exported packages and their recipients, direct administrative object-store access,
and external copies/caches. Non-image evidence retains its existing semantics; the new person-image
policy is not a global media disclosure guarantee. Masked trained-geometry production remains an
explicit producer activation dependency. Manual review has no new unmasked bypass.

## The investigation that preceded this contract

The 152 lines above are the live read contract. The investigation that preceded it, committed before
implementation and superseded by it, was lifted on 2026-09-09 to
[records/2026-09-08-asset-read-currency-investigation.md](records/2026-09-08-asset-read-currency-investigation.md).

It was moved rather than deleted, because a superseded proposal that was acted on is a checkpoint
rather than a draft: it records what was believed before the work and is the only place the
reasoning survives. It was moved rather than left in place because a live contract with 145 lines of
superseded proposal beneath it is a document people read wrongly, and the read contract is the half
that governs what the system does today.

This file keeps its path. Two evaluation records name it, and one binds a sha256 of its bytes as of
an earlier revision; the path is what those records depend on.
