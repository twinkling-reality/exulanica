# Serving photographs and geometry under current permission

A world built from photographs serves original photographs, masked derivatives, point maps,
trained scenes and World Read bundles. This contract owns the rule for every such read: the bytes a
response carries must still be permitted, with current mask and geometry lineage, at one
authorization instant ordered against every writer that could change the answer (migration 0041).
It also owns what the World Read bundle says about people, its recipient evidence and its posed
image bytes. Whether a screening permits geometry is
[person-presentation-consent.md](person-presentation-consent.md); which model may receive a
photograph is [personal-admission.md](personal-admission.md).

## Contents

- [What delivery refuses](#what-delivery-refuses)
- [Read contract and lineage](#read-contract-and-lineage)
- [Authorization instant and ordering](#authorization-instant-and-ordering)
- [Writers under the barrier](#writers-under-the-barrier)
- [Society inputs under the barrier](#society-inputs-under-the-barrier)
- [Dependency writer inventory](#dependency-writer-inventory)
- [World Read: people](#world-read-people)
- [World Read: recipient evidence](#world-read-recipient-evidence)
- [World Read: posed image bytes](#world-read-posed-image-bytes)
- [Limits](#limits)
- [Evidence](#evidence)

## What delivery refuses

Original, crop and by-URI image delivery refuse current mask requirements, withdrawal and missing
capture identity. A permitted original keeps its exact bytes, and no route substitutes a mask under
an original digest. Image track identity is checked even when MIME metadata is missing. Ordinary
non-image citations do not acquire geometry prerequisites. Viewer image references use `/masked`,
including for captures with nobody in them.

## Read contract and lineage

`/masked` selects an exact current persisted derivative through the explicit-time read policy,
using the screening mask matcher. Missing, obsolete or purged required masks refuse. World source
metadata checks the same selection and verifies the selected stored bytes; an unavailable source
keeps its live capture id for manual review but no asset reference, and a deleted source loses its
review identity. The unique live-capture index rejects duplicate live mappings, and the read
predicate still refuses disagreeing mappings rather than choosing one by order. A missing capture
mapping is not an empty, reviewed person inventory.

Point-map metadata omits policy-refused artifacts. Direct-id delivery verifies the artifact's own
source, read-source digest, screening and exact buffered row; a current mask for the capture is
insufficient. Missing screening lineage from before migration 0040 refuses. A null read-source
means the original, as defined in migration 0037, and is accepted only when that artifact's
persisted screening and actual source support current permission. A rebuilt mask does not rebind
historical geometry.

Scene geometry checks the persisted pose manifest and exact per-capture frame digests against the
job's recorded point maps and their read-source digests. The pose, gate, placement, job and active
assertion bindings must still be the buffered ones. Trained delivery also checks the training
manifest's pose digest and source list and the gate-named publication receipt. Missing, purged or
withdrawn lineage refuses. `/graph` keeps review metadata for a refused scene but removes its
placements, recovered cameras and trained assets. World Read scene, place and sparse-observation
responses with embedded geometry refuse when their recorded inputs are unavailable. Tests that
publish scenes through the real publication, controller and store paths with scripted COLMAP and
training outputs establish this delivery and lineage behaviour, not reconstruction quality; in them
the real mask stage rebuilds a changed source and the trained asset built from the prior source
stays refused.

A saved world's v4 arrival can retain one successful scene job after a later job becomes the
scene's current graph build. The job-bound build claim is separate from the scene's functional
current-rung claim. The entry-scoped reader requires the stored world, version, source snapshot,
scene, job and exact pose, placement and gate digests; it checks every immutable job member and
current source right before serving metadata or trained bytes. A withdrawn member retracts that
build claim, including a member the reconstruction did not register. Ordinary graph and geometry
reads continue to select the current build. A retained claim does not preserve permission after
withdrawal or purge.

## Authorization instant and ordering

Snapshot metadata is read in a REPEATABLE READ, READ ONLY transaction. The explicit-time predicates
do not invoke the admission lock or replace snapshot consistency with fresh per-query reads, and a
metadata result is true of its snapshot, not a capability for later bytes.

Each byte-serving operation first buffers and hash-verifies local bytes. It then opens a separate
READ COMMITTED, READ ONLY transaction, acquires the asset barrier in its own statement, and obtains
one database timestamp in a subsequent statement. That timestamp is the authorization instant, and
every final input and permission comparison uses it. Graph and World Read also reauthorize their
buffered embedded geometry after closing the metadata snapshot. Successful graph and World Read
responses and evidence and geometry bytes carry a no-store cache policy. Each evidence range request
reauthorizes; point-map and trained routes keep whole-body delivery without byte ranges.

The final check, [`final_read_check`](../exulanica/db/read_check.py), takes only the global asset
barrier, never a training, privacy or object-purge lock, and performs no store read, streaming or
network operation while holding it. Writers that committed before it acquired the barrier are
visible. A writer or an expiry ordered afterwards affects later requests and cannot retract the
already-authorized response; network completion is not the linearization point. Buffers are local
to the request, not transferable permission tokens.

## Writers under the barrier

A writer's own last question takes the same exclusive barrier inside its write transaction,
through [`lock_asset_reads_until_commit`](../exulanica/db/read_check.py), and holds it until that
transaction commits. The rule for a writer is the reader's: no store read, stat or stream while it
holds the barrier. It reads and checks the stored bytes it depends on before taking the barrier,
asks only rows under it, and answers with what it wrote, without availability, which its caller
reads after the commit. The rule gives up one refusal: bytes lost from the store with no row
recording why, between that read and the last question, no longer refuse the write; it commits,
and what it placed reads `unavailable_bytes`, as it would had the bytes been lost just after the
commit. The product erases stored bytes only for a committed deletion (`mark_purged` in
[`deletion/queue.py`](../exulanica/deletion/queue.py)), and a depth estimate's last question reads
that deletion's rows. Authored edits, branches, the carry that adds photographs to a made world and
a society's inputs follow the rule
([`tests/test_store_reads_under_the_asset_lock.py`](../tests/test_store_reads_under_the_asset_lock.py),
[`tests/test_society_store_reads_under_the_asset_lock.py`](../tests/test_society_store_reads_under_the_asset_lock.py)).

Dependency mutations take the shared side of the global barrier with **try-lock** and keep it
through commit. If a reader already owns the exclusive barrier, the mutation raises retryable 40001
rather than waiting while holding another lock, which prevents a cycle even when a caller acquired
training, privacy, row or purge locks before its first relevant mutation. The reader can wait for an
existing writer but holds none of those other locks, and a writer already owning its shared barrier
can finish cascades while a reader waits. The barrier is deliberately global, so it covers moves
between workspaces and global stage mutations without scanning workspaces through row-level
security; its cost is brief cross-workspace contention, sometimes a retry for an unrelated mutation.
Applications must retry the whole failed transaction, not its final statement.

A writer that reads assets as it writes takes its workspace's lock
([`lock_workspace`](../exulanica/world/workspace_lock.py)) before the barrier's exclusive side: an
authored edit, a branch, a society's minute and a playback round. A tombstone takes the barrier's
shared side first, from its first trigger, and migration 0020's structural invalidation takes the
workspace's lock after it, so a tombstone never waits for that lock (migration 0137). Its first
AFTER trigger takes the lock with try-lock; held by another transaction, it refuses the tombstone
with retryable 40001, which the API answers `409 busy`, and the transaction that wrote it, a
stopped search right's included, writes nothing. A transaction that already holds its workspace's
lock takes it again. A tombstone that waited would hold what a reader between its two locks waits
for while waiting for what that reader holds, a cycle PostgreSQL ends by aborting one of them
([`tests/test_tombstone_workspace_lock_postgres.py`](../tests/test_tombstone_workspace_lock_postgres.py)).

`privacy_currency_lock` takes the training-source lock shared before the privacy lock, the order
export uses when it holds training-source exclusively, and covers an earlier admission or read in a
writer's transaction as well as the insert trigger; this removes a deadlock between training export
and consent recording. Training's package lock stays separate, and its consent writer does not wait
for privacy. Delivery never acquires an object purge lock, and a purger's later metadata mutation
try-locks the barrier.

## Society inputs under the barrier

A society's input depends on stored bytes: each placed object's reviewed asset and licence, and a
district's admitted sources and artifacts. Every authorization takes the barrier, and one
transaction often authorizes several inputs, so the transaction reads the bytes of all of them
before its first authorization, once, and answers every later one from that read.

The repository announces the inputs ahead (`inputs_ahead` in
[`world/society.py`](../exulanica/world/society.py)): a minute's inputs, the state read after it
and a change of presence name; a replayed history; a decision's context where it is prepared, read
or finished; a history of directed requests; every society a question's answer reads, of those
whose stored inputs check; a society experiment's baseline and treatment; every input queued for
the minutes a playback round runs after checking its society is ready; and the reviewed assets a
small square places, whose inputs after each addition name them. The read belongs to its
transaction, known by its connection and the time the transaction began
([`society_runtime.py`](../exulanica/api/society_runtime.py)), so a playback round's minutes share
one, and a district society and a saved world's follow the same rule. A transaction that authorizes
one input alone, as a read made outside a caller's transaction does, reads only that input's bytes.
Bringing inhabitants into a saved world reads its first input and takes the barrier before it writes
the world's place, because that write takes the barrier's shared side. An input nobody announced is
still authorized: its bytes are read under the barrier and the log names the defect
(`society_input_not_announced`).

A reviewed asset row, or a district's admitted source, that names other bytes under the barrier
than when they were read changed in between, which only a direct change to the registry or a right
taking effect in that moment does (the importer refuses to rebind or republish a key). That is the
race: a request that meets it is refused as `409 busy`, to be asked again; a question's answer
leaves that society out; a playback round fails without pausing, and the society is claimed again
once that claim's lease runs out. Recording a model's decision is asked again
`RETRIES_AFTER_A_RACE` times, and on its last try the race records the decision as
`decision_sources_unavailable`, with no proposal and with the call that was made and what it cost,
so the race leaves no request in progress.

## Dependency writer inventory

Every INSERT, UPDATE and DELETE on these tables fires the same barrier trigger:

| Dependency | Tables and relevant writer paths |
| --- | --- |
| Source identity and physical availability | `capture`, `blob`, `evidence_span`, `media_track`: intake, direct SQL, deletion, purge metadata, moves between workspaces where the role permits them |
| Current presentation state | `person_region`, `person_presentation_consent`, `person_subject`: review and consent commands and direct SQL, with the append-only and sequence protections of migration 0040 |
| Withdrawal reachability | `tombstone`, `occurrence`, `entity_link`, `entity`, `person_derivative_dependency`: identity and occurrence writers, person dependency triggers, tombstone cascades and later dependencies |
| Persisted geometry and authority | `artifact`, `assertion`, `capture_reconstruction_authorization`, `reconstruction_privacy_screening`: producers and publication, admission, invalidation, direct SQL and purge |
| Scene and job identity | `reconstruction_scene`, `reconstruction_scene_member`, `reconstruction_scene_job`, `reconstruction_scene_job_member`: scene admission, leased publication and cascades |
| Place dependency identity | `place`, `place_version`, `place_alignment`: place admission and alignment and immutable rows |
| Global producer definition | `stage_registry`, `stage_definition`: registry writers affect current mask matching; global rows use the same barrier without a workspace lookup |

These triggers grant no write and relax no append-only, row-level security or role rule. Direct
partition writes inherit the row triggers. TRUNCATE and DDL are not runtime privileges or part of
the concurrent delivery contract; an administrative migration needs separate deployment control.
Training-use package consent is an export permission and is not repurposed as viewer permission.
The runtime evidence tests connect as the actual `exulanica_ro` role and assert SELECT-only access
by a role that owns nothing and is neither superuser nor BYPASSRLS.

## World Read: people

The World Read bundle reports, per photograph, whether anybody has looked at it for people
(`unscreened` or `recorded`) and how many live regions it carries. It reports neither any person's
resolved state nor their outline (`exulanica/graph/read_consent.py`). A resolved state can change
when a `temporary_hide` or a term expires with no write in between, and `release` is inside the
bundle's recorded keys, so a resolved state would make the recorded digest move on a timer, and a
digest that moves when nobody wrote anything is one nobody can quote. `release.state` is therefore
`internal_only` for every scene, with a per-scene reason. Binding a release answer to an explicit
as-of time carried in the bundle is the unbuilt way to report per-person state.

For screening, the bundle publishes the newest receipt's own `eligibility_state` unchanged,
because a read path does not edit what a named reviewer wrote, and beside it
`under_current_policy`: whether that receipt was written under the privacy policy in force. Only the
policy term of `privacy_screening_allows_capture` is reported, because its other terms compare
against the clock. A migration that bumps `current_privacy_policy()` therefore moves the recorded
digest of every bundle; that is a write, not a tick.

## World Read: recipient evidence

An additive `recipient_evidence` block (`exulanica.world-read-recipient-evidence/v1`, with its own
`evidence_sha256`) records, for owning-workspace reads, the capture source identities, the recorded
region inventory, complete applicable presentation receipt chains (subject-wide withdrawal
included) and the persisted geometry input bindings (`exulanica/graph/world_read_evidence.py`).
Opaque subject and actor ids are kept where needed to check receipt digests; names, entity labels,
free-text authority evidence and photo bytes are excluded. A receipt authenticates neither the actor
nor their authority, and training permission and licensor authority are unavailable here and cannot
be inferred from likeness. This is recorded provenance, not redistribution authorization.

Recorded inputs never call a time-dependent consent resolver. A separate offline evaluation needs an
explicit zoned time, applies `effective_at <= time < valid_until`, region-specific precedence and
sequence order, and treats any recorded subject withdrawal as terminal; presence, naming, likeness
and temporary hide stay separate. An offline recipient cannot learn withdrawals recorded after the
bytes were issued. Hashes detect changes against a trusted expected bundle digest, but an unsigned
issuer can omit or replace history and rehash it, so this is not a completeness proof against a
dishonest issuer.

Geometry binds an output artifact id and digest to its persisted `read_source_sha256`, frozen scene
build inputs and publication receipts where available. A newly current mask is never substituted
for the derivative actually read, and absent legacy lineage is reported unavailable, never inferred
from present masking state. Mask manifests must bind the exact derivative and original; trained
geometry also requires its publication's output and source manifest. Generated geometry stays
outside the record and the recorded digest.

The recorded digest recipe is `exulanica.world-read-recorded/v2`, named in
`recorded_digest_profile`. It excludes the delivery keys `scene`, `views`, `geometry`, `rungs` and
`generated`, whose integrity `bundle_sha256` covers; the remaining keys are listed in
`recorded_keys`. Cameras are recorded in the exact pose receipt and output identities in
`recipient_evidence`. Consumers comparing historical recorded digests must distinguish this recipe
from v1. Existing scene and place addresses and v1 fields are unchanged; v1 readers may ignore the
block, and strict clients must accept the key.

The verifier (`exulanica/graph/world_read_verification.py`) keeps source lineage and permission
separate: `point_lineage` available means the retained output, original or read digest and pose
frame agree, and approves nothing about screening, training, quality or redistribution. Mask
coverage is checked with the point's own build-time screening snapshot, the mask named by that
snapshot, its persisted input digest and the retained intake digests; the verifier reproduces the
region-set and consent-state hashes and compares the historical outlines with the recorded region
inventory, never substituting a newer screening or mask. Named unavailable reasons include
`legacy_mask_build_snapshot_missing`, `exact_mask_manifest_missing_or_ambiguous`,
`frozen_point_binding_missing`, `receipt_bytes_missing_or_corrupt` and
`consent_columns_disagree_with_receipt`. Existing persisted snapshots suffice for artifacts that
have them; for legacy artifacts without them, the exact inputs would have had to be retained at
mask publication, and no backfill exists.

Receipt bytes must decode to an object with the expected supported profile, field types and
top-level fields before projection. Unsupported content is withheld as `receipt_unsupported_shape`,
`receipt_unsupported_profile` or `receipt_unsupported_fields`, and its raw payload is never copied
into recipient evidence; this covers mask, pose and trained-publication receipts. A malformed
irrelevant mask candidate does not invalidate a unique supported matching manifest, and when no
supported manifest remains, `exact_mask_manifest_unavailable` carries sorted `candidate_reasons`.
Offline verification applies the same structural checks; malformed input produces an
`EvidenceError` with a named reason, and the command exits 1 with a small JSON error and no private
payload.

## World Read: posed image bytes

Each view in a scene bundle keeps its capture, ordinal, registration, camera, exclusion and consent,
and carries an additive `photo_bytes` object (`exulanica.world-read-view/v1`,
`exulanica/graph/world_read_views.py`) with either an explicit unavailable reason or an available
descriptor. An available descriptor binds the exact SHA-256, byte length, decoded MIME type and
dimensions, original source digest, pose input digest, pose receipt digest, camera and an
authenticated fetch reference; its binding is the canonical digest of those fields. The descriptor
also commits the recipient evidence digest and the capture's recorded region and consent digest
inventory, so any consent write requires a bundle refresh even when it selects the same image.
`GET /evidence/{span_id}/masked` accepts the scene, capture and expected binding; an unbound caller
keeps the route's ordinary behaviour, and original citation routes keep their exact meaning.

The supported relationship between viewer bytes and pose is identity: the selected bytes must equal
the pose frame's persisted input digest and match the recorded camera pixel dimensions, with no
crop, resize or EXIF transform at delivery and unchanged intrinsics. A non-identity EXIF original
refuses, because the pose receipt does not persist the decoder's orientation convention and
dimensions alone cannot prove orientation. A mask is produced from the upright image and encoded as
a full-size JPEG without EXIF, so a mask of an oriented original qualifies when its exact digest is
the persisted pose frame. A later current mask is never substituted for historical pose lineage;
differing current and pose digests are named and refused. Missing legacy bindings and members
without cameras are unavailable.

A download reproduces the descriptor under the requesting workspace in a read-only repeatable-read
snapshot, buffers and hash-verifies the complete object, and rechecks the exact scene bindings and
current image selection under the final check, with no store read or network delivery while the
barrier is held. A changed binding refuses with 409 and requires a bundle refresh. Full and range
responses are checked against the full object digest before slicing, so recipients reassemble
ranges before checking SHA-256. `photo_bytes` lives only in `views`, outside the recorded keys, so
removing it leaves the recorded digest unchanged and changes only `bundle_sha256`.

The offline verifier takes a trusted expected bundle digest and the downloaded files and checks the
canonical envelope, recipient evidence, descriptor structure and binding, exact file digest and
size, decoded orientation and dimensions, and camera agreement with the retained pose receipt,
without SQL, a store or a network connection.

## Limits

- Already delivered bytes cannot be revoked by this guard, and an offline recipient cannot discover
  later withdrawals.
- Unresolved surfaces: generated-model asset delivery and conditioning metadata, exported packages
  and their recipients, direct administrative object-store access, and external copies and caches.
- Non-image evidence keeps its own semantics; the person-image policy is not a global media
  disclosure guarantee.
- `release.state` stays `internal_only`: recipient evidence and posed views are recorded read
  behaviour, not real-person consent, reconstruction quality, training permission or permission to
  redistribute.
- Cropped, resized or transformed viewer-to-pose mappings and non-identity EXIF originals are not
  delivered as posed views.
- Legacy artifacts without retained build snapshots stay unavailable; no legacy backfill exists.

## Evidence

- [Executed record](evaluation/2026-09-08-executed-asset-read-currency.json) and
  [verification](evaluation/2026-09-08-verification-asset-read-currency.json): route-to-byte
  delivery, lineage and lock-order controls over generated media.
- [Recipient evidence campaign](evaluation/2026-09-08-run-02-world-read-recipient-evidence.json),
  [verification](evaluation/2026-09-08-verification-world-read-recipient-evidence.json),
  [repair campaign](evaluation/2026-09-08-repair-01-world-read-recipient-evidence.json) and
  [repair verification](evaluation/2026-09-08-repair-verification-world-read-recipient-evidence.json).
- [Posed view campaign](evaluation/2026-09-08-run-02-world-read-views.json),
  [verification](evaluation/2026-09-08-verification-world-read-views.json),
  [route and digest observations](evaluation/artifacts/2026-09-08-run-02-world-read-views/acceptance-observations.json)
  and [fresh-process negative results](evaluation/artifacts/2026-09-08-run-02-world-read-views/fresh-negative-results.json).
- `tests/test_world_read_evidence.py` and `tests/test_world_read_views.py`.

All of these use generated fixtures and scripted pose outputs in disposable schemas. They establish
delivery and recorded read behaviour, not retained-database activation or reconstruction quality.
