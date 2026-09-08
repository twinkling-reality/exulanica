# World Read recipient evidence

Wire contract, 2026-09-08. Owning-workspace reads only; release.state remains
internal_only. This is recorded provenance, not redistribution authorization or WMP 1.1.

The additive recipient_evidence block has its own v1 profile and evidence_sha256 over its
record. The record contains capture source identities, the current recorded region inventory,
complete applicable presentation receipt chains (including subject-wide withdrawal), and actual
persisted geometry input bindings. Opaque subject and actor IDs are retained where needed to
check receipt digests; names, entity labels, free-text authority evidence and photo bytes are
excluded. A receipt authenticates neither the actor nor their authority. Training permission
and licensor authority are explicitly unavailable here and cannot be inferred from likeness.

Recorded inputs never call a time-dependent consent resolver. A separate offline evaluation
requires an explicit zoned time, applies effective_at <= time < valid_until, region-specific
precedence and sequence ordering, and treats any recorded subject withdrawal as terminal.
Presence, naming, likeness and temporary hide remain separate. An offline recipient cannot
learn withdrawals recorded after these bytes were issued. Hashes detect changes against a trusted
expected bundle digest; an unsigned issuer can omit or replace history and rehash it. This is
not a completeness proof against a dishonest issuer.

Geometry binds output artifact ID/digest to persisted read_source_sha256, frozen scene build
inputs and publication receipts where available. A newly current mask is never substituted for
the derivative actually read. Legacy absent lineage is unavailable with a producing seam, never
inferred from today's masking state. Mask manifests must bind the exact derivative and original;
trained geometry additionally requires its publication's output and source manifest. Generated
geometry stays outside this record and outside the recorded digest. Missing receipt bytes or
unsupported/private payloads must yield specific unavailable reasons.

Compatibility: existing scene and place addresses and v1 fields remain. New evidence changes
recorded and bundle hashes once. Existing v1 readers may ignore the addition; strict clients
must accept the new key. The legacy recorded digest also contains delivery-sensitive fields:
this work must isolate clock-dependent delivery projections before claiming elapsed-time
stability. The evidence digest always covers only immutable recorded inputs; evaluation at a
requested time is a separate output and never a recorded input. No current authorization promise
is made by a saved bundle. Live route and media authorization remain their existing contracts.

Migration: none. No producer, consent writer, graph snapshot or API registration changes.

The implemented digest recipe is named exulanica.world-read-recorded/v2 in
recorded_digest_profile. It excludes scene, views, geometry and rungs as well as generated:
those first four fields contain live delivery projections. Their integrity remains covered by
bundle_sha256. Recorded cameras live in the exact pose receipt and recorded output identities
in recipient_evidence. The remaining keys are enumerated by recorded_keys as before. Consumers
that compare historical recorded digests must distinguish this recipe from v1; new generations
cite the new digest. This deliberately changes conditioning identity, not scene/place addressing.

Source lineage and permission evaluation are separate results. The verifier's point_lineage
available means the retained output, original/read digest and pose frame agree. It does not
approve screening, training, reconstruction quality or redistribution. Masked input identity
is checked against its exact retained v1 manifest. Coverage is checked using the point's own
screening snapshot, the mask artifact named by that snapshot, its persisted input digest, and
retained intake digests. The verifier reproduces the original region-set and consent-state
hashes and their sorted input hash, and compares the historical outlines to the recorded current
region inventory. A newer screening or mask is never substituted. The privacy snapshot is an
immutable build-time record, not a fresh clock-derived resolution. Authorization scope, free-text
review material and account-holder authority evidence are excluded from this projection.

Missing historical snapshots return legacy_mask_build_snapshot_missing. Missing or ambiguous
exact manifests return exact_mask_manifest_missing_or_ambiguous. Old points with no frozen build
binding return frozen_point_binding_missing, and missing receipt bytes return
receipt_bytes_missing_or_corrupt. Existing persisted snapshots suffice without a producer change
for current fixtures. For legacy artifacts lacking them, a separate scoped producing-seam
follow-up would need to retain the exact inputs at masked_source publication; later reconstruction
cannot invent them. No migration is allocated and no general legacy backfill is claimed. The
legacy unavailable wire case is a labelled protocol fixture; it is not a migrated legacy database.
Masked Gaussian training remains separate.

A separate producer concern is checked explicitly: presentation writers can call now twice when
no effective_at is supplied, once for the immutable receipt and once for the resolver column.
This reader returns consent_columns_disagree_with_receipt rather than silently choosing between
those meanings. A separate consent-writer follow-up should use one explicit instant for both.
No writer is changed in this brief.

## Executed verification

Code head 4c5a764 ran against the permitted test database, using generated photographs, the
real masked-source producer, and scripted point-map, pose and trained-geometry publishers.
Authenticated scene/place routes produced canonical bundles. Ten saved fixtures then ran in
fresh child processes outside the repository with database settings removed. The saved stale
mask was rejected; the labelled legacy protocol fixture reported unavailable rather than
inventing a historical snapshot. The legacy fixture is a wire case, not a real legacy database.

Checks cover elapsed time and consent expiry without writes, recorded digest movement on
withdrawal, receipt tampering, omitted lineage, output/source disagreement, changed outlines,
mask input commitments, workspace isolation and resolved/unresolved place compatibility.
Five controls disabled the exact consent, output-lineage, mask-coverage, mask-input and trained
output checks. Each failed its named selector with DID NOT RAISE. The first campaign's backend
was deliberately interrupted after review found the existing historical screening snapshots;
its logs and artifacts are retained, not counted as a passing full run.

The complete final gates passed: 2124 backend tests and 3 skips, Ruff, four import contracts,
web typecheck, boundaries and 876 web tests. Gates were serialized; no competing pytest suite
was observed at dispatch. Post-generation retained-record checks passed. The verification
record checks 65 artifact bindings and follows the campaign record, which follows the verified
asset-read integration record. The code remained unchanged through the final gates.

- [Campaign](evaluation/2026-09-08-run-02-world-read-recipient-evidence.json)
- [Verification](evaluation/2026-09-08-verification-world-read-recipient-evidence.json)

These fixtures establish recorded read behavior, not real-person consent, reconstruction quality,
masked Gaussian training or permission to redistribute. Retained deployment of migrations
0039 through 0041 remains separate from this test-schema work. No public migration, personal
media, hosted inference, GPU spend, merge or push was performed.
