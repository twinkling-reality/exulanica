# Screening currency: contract review and scope blocker

Status: design review only. Shared admission remains unfixed and personal-data activation
remains blocked. Base: integrated `38625d2`, following the accepted personal review integration
record. Migration 0040 is reserved, not written or applied. Historical evidence is unchanged.

## Recorded inputs and the missing producer alignment

The current mask producer already records meaningful lineage. In
`ingest/stages/masked_source.py`, its input digest hashes the sorted three hashes of:

1. The exact upright intake artifact content.
2. `person-region-set/v1`: capture ID, original source hash, and sorted live region keys and
   silhouettes.
3. `person-consent-state/v1`: capture ID, source hash, and sorted per-region presentation state,
   masked flag and naming permission.

The artifact also records source hash, stage version, parameters digest, input digest, identity
key and output content hash. Its identity key frames and hashes these stage inputs. The producer
uses the supplied silhouettes and resolved states to paint the image. These hashes can support
an exact comparison; newest timestamp or any masked artifact cannot substitute for it. The
separate mask manifest identifies masked regions, subjects and states but omits silhouettes and
receipt identities. Its bytes are in the content store, not a SQL-readable current-input record.

There is a concrete semantic mismatch before persistence. `pipeline._masked_source` obtains
inputs from `person_state.region_state_for_capture`. That function reads all consent transitions
from `spine/person_consent.py`, then drops `valid_until` and folds them by effective time and
receipt digest. It does not exclude future-effective transitions. SQL's
`person_consent_is_granted` filters effective and expiry times and gives region-scoped receipts
precedence over subject-wide receipts, then orders by sequence. These are different decisions.

A local in-memory probe of the actual state reader, using one generated polygon and a likeness
grant effective January 1, 2000 and expired January 2, 2000, returned
`Expired likeness grant: state=shown, masked=False`. This is a focused diagnostic, not a database
rehearsal, retained acceptance envelope, mutant kill, or demonstration of disclosed bytes.

Consequently a SQL implementation matching the producer would inherit its expiry defect; one
matching time-aware SQL would refuse a mask that the unchanged producer cannot correctly rebuild.
For a photograph whose only region has expired likeness consent, the producer emits no mask at
all. A trigger stamping current inputs onto an artifact at INSERT would additionally mislabel
work performed using earlier inputs. Neither approach meets this brief.

## Smallest requested extension

Add **`exulanica/ingest/person_state.py`** to the writable set. Make this existing producer input
reader consume the shared database-resolved current states at an explicit evaluation instant,
using helpers in the already permitted `ingest/spine/privacy.py`. The pipeline and mask stage
already consume this reader, so no pipeline, stage registry, new spine module or new table is
requested. Preserve the existing mask digest formats and compare their exact recorded inputs.

This extension addresses the demonstrated producer mismatch. Do not implement a second fold in
the admission layer. If implementation shows that an additional producer interface is needed,
report that extension before changing it. No production changes have been made at this checkpoint.

## Proposed shared contract after extension

Resolve workspace, exact capture/source bytes, live region inventory including subject links and
edit receipt identities, and applicable consent receipt identities/scopes/decisions at a single
database evaluation instant. Preserve both the review input binding and the mask input binding:
an unrelated naming change need not force different pixels, but a changed review input must not
silently retain an earlier review's standing permission. Specify the relevant input set explicitly
in 0040 rather than treating every historical receipt as invalid.

Recompute effective consent on every new permission check. Expiry and future effective times
can change the answer without any database write. Check authority and screening expiry too.
Withdrawal remains a terminal refusal through existing tombstone/withdrawal policy. Detection-only
permission stays separate from permission for geometry. A no-person review binds the empty
inventory, so adding a region makes that review obsolete.

Bind new screenings immutably to their observed inputs and any exact required mask. Compare
the bound inputs with the current inputs in `privacy_screening_allows_capture`, and compare the
named mask's persisted digest with the expected producer digest. Reject missing legacy bindings
for new geometry operations without rewriting dated receipts. Rebuild alone must not revive an
old review; re-screening establishes the new binding. Unchanged-input retries may reuse it.

Before implementation, specify and test a database locking contract shared by region/consent
writes, screening insertion, scene admission and geometry insertion. Capture-only locks are
insufficient for subject-wide consent affecting multiple captures. A conservative workspace lock
is a possible tradeoff, with subject/capture lookup repeated after acquiring it. Account for
READ COMMITTED fresh snapshots, reject unsupported stale transaction snapshots, and re-evaluate
time-dependent permission after waiting. Do not hold a transaction lock across model inference:
an artifact can record old inputs, but a new operation must reject that obsolete binding.

## Consumers and separate read activation dependency

Direct SQL policy consumers include frontier `preflight.py` and `demonstration.py`,
`ingest/spine/privacy.py` selection/checking, `world_package/training_inputs.py`, and migration
0029's admission-member, artifact and scene policy paths. `admit_reconstruction_scene` must be
tested through its real entry point. Migration 0037's point-map trigger currently checks only
that the named masked bytes belong to an existing unpurged derivative of the source. The new
write check must validate currency even when a write explicitly names masked bytes and current
state no longer requires masking; cover relevant UPDATE paths as well as INSERT.

`ingest/spine/artifacts.py` applies the SQL screening predicate to point-map selection and exact
resolution. Its masked-source queries do not apply that predicate. `masked_inputs.py` currently
selects available masks and verifies declared IDs/content, without establishing current inputs
for every exact declared mask. Those permitted seams need explicit currency checks.

Serving old assets is a **separate remaining activation dependency**. In particular,
`api/routes/evidence.py` selects masked-source bytes by stage version and creation time without
matching current mask inputs. `graph/geometry.py` reads point-map bytes with live-source, purge
and withdrawal checks; `graph/scene_geometry.py` reads trained scene assets with scene/job/gate,
purge and withdrawal checks. Admission checks do not establish a universal current-consent read
guarantee for these paths. Original evidence access also has its own exact-byte semantics.
Read-time currency and read-versus-withdrawal races require a separately scoped fix and tests.

The predecessor personal-admission records demonstrate a stale SQL admission answer and a killed
command-local guard mutant. They demonstrate neither a stale depth write nor disclosure. This
review preserves that distinction.

## Verification still required

After scope extension, execute generated-media database/mask rehearsals in isolated schemas at
the permitted test database, including direct SQL, actual frontier preflight, scene admission,
point-map writes, expiry, withdrawal, region add/edit/delete, consent precedence, cross-workspace,
legacy, detection-only, no-person and unchanged retry cases. Execute rebuild/re-screen success
and appropriate concurrent interleavings. Require exact selector FAILED lines for mutant kills.
Generate new digest-bound evidence with an explicit predecessor and no personal paths or floats.

Full backend and web gates have not been run for this documentation checkpoint; no suite slot
was taken. Coordinate that slot with the orchestrator when implementation can proceed. The full
acceptance brief remains pending. No public migration, personal media, hosted calls, credentials,
GPU work, merge or push occurred.
