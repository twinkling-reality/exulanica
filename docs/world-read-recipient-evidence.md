# World Read recipient evidence

Proposed wire contract, 2026-09-08. Owning-workspace reads only; release.state remains
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
can be checked against a retained v1 mask manifest. Complete mask coverage returns
mask_outline_binding_not_supplied: that manifest lists region IDs but not outlines. A missing
or ambiguous exact manifest returns exact_mask_manifest_missing_or_ambiguous. Old points with
no frozen build binding return frozen_point_binding_missing, and missing pose bytes remain
receipt_bytes_missing_or_corrupt. These failures are not repaired by selecting a newer mask.

Separate scoped follow-up requested: extend the masked-source producing seam
(exulanica/ingest/stages/masked_source.py and exulanica/ingest/person_receipts.py) to export an
exact, privacy-minimized historical input commitment and the material needed to verify it,
including the intake digest, region outlines and resolved input states, together with the
persisted mask input digest. Assess reuse of existing JSON receipts and screening snapshots
before proposing any storage change; no migration is allocated here. Existing v1 manifests
must retain their historical limitations. Masked Gaussian training remains separate.

A second producer concern is checked explicitly: presentation writers can call now twice when
no effective_at is supplied, once for the immutable receipt and once for the resolver column.
This reader returns consent_columns_disagree_with_receipt rather than silently choosing between
those meanings. A separate consent-writer follow-up should use one explicit instant for both.
No writer is changed in this brief.
