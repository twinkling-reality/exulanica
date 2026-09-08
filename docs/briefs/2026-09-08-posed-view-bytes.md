# Deliver exact posed image bytes through World Read

Status: dispatched by the operator to task 01a0820f-2d29-7722-af7d-f7415e504b1a.
This task exclusively owns the Exulanica isolated database/full-suite slot until explicit
handoff or release. The preceding consent-timestamp task released its slot; recovery readiness
is documentation-only. This reservation permits only owned isolated schemas and the gates below,
not retained-public mutation. Original implementation scope is unchanged.
Repository: /Users/glendonchin/dev/Technology/orimera.
Baseline: pushed main 46e106b. Create worktree
/Users/glendonchin/dev/Technology/exulanica-posed-view-bytes on codex/posed-view-bytes from current
main. Migration: NONE. Existing 0039-0041 remain unchanged. No migration number is reserved.

## Contract and context

Complete the remaining photo-byte item in Tier 3, using generated fixtures. World Read already
has recipient consent evidence, persisted geometry lineage and the prospective timestamp fix.
Do not rebuild them. _view() still returns capture ID, ordinal, registration, camera, exclusion
and consent without a posed-photo byte reference. The existing authenticated
/evidence/{span_id}/masked route selects currently permitted bytes and rechecks permission after
reading the hash-verified store. Reuse this policy rather than creating a weaker parallel one.

Read applicable AGENTS.md, docs/phase-10-tickets.md P10-1, docs/world-read-recipient-evidence.md,
docs/asset-read-currency.md, docs/integration-world-read-recipient-2026-09-08.md,
docs/integration-consent-timestamp-2026-09-08.md, exulanica/graph/world_read.py,
world_read_evidence.py, world_read_verification.py, asset_read_policy.py, reconstruction scene
member projection, exulanica/api/routes/world_read.py, exulanica/api/routes/evidence.py,
exulanica/store/resolve.py and their actual callers/tests. Also trace the producer's orientation,
resize and calibration conventions before declaring a photograph compatible with a camera.

## Writable file set

- exulanica/graph/world_read.py.
- New exulanica/graph/world_read_views.py.
- exulanica/graph/world_read_evidence.py and world_read_verification.py, only for view-byte bindings.
- exulanica/api/routes/world_read.py and evidence.py, only for posed-view delivery and exact-byte
  checks on the existing authenticated routes; preserve existing callers and original-route meaning.
- tests/test_world_read_bundle.py, tests/test_world_read_route.py.
- New tests/test_world_read_views.py.
- New docs/world-read-posed-views.md.
- New scripts/record_world_read_view_evidence.py and scripts/verify_world_read_view_evidence.py.
- New docs/evaluation/*-world-read-views.json and uniquely named generated-fixture artifact folders
  under docs/evaluation/artifacts/ ending in world-read-views.

Everything else is read-only. In particular: shared asset_read_policy.py, SQL policies, migrations,
consent writers, geometry producers, shared test setup, existing evidence, training WMP, README.md,
frontend/main.ts, registries and package manifests. Reuse existing functions where possible.
If a required source binding or authorization seam cannot be supported in this scope, report the
exact file/function, observed mismatch and smallest extension before implementing outside it.
Do not work around a scope boundary by duplicating SQL policy or weakening refusal.

## Required behavior

Write the design/compatibility contract first, then implement within this scope. Expose exact
image digest, media type, decoded dimensions, provenance and an authenticated fetch reference
for each deliverable posed view, or a specific unavailable reason. A URL alone is insufficient.
The bytes must match the declared camera pixel space: orientation, dimensions, crop and intrinsic
calibration. If a transformation cannot be established from persisted evidence, refuse rather
than invent calibration. Preserve members without cameras and their exclusion reasons.

A currently selected viewer image and the image used to recover a pose are separate facts.
Name both when necessary and prove the spatial relationship. Do not substitute a current-looking
mask for historical geometry lineage. Use current presentation consent to select deliverable
bytes, require masks where needed and refuse missing/stale masks. No fallback to original bytes
when masking is required. Preserve exact original citation semantics and workspace non-disclosure.

Bind downloads to the digest advertised by the bundle. If consent, mask selection or lineage
changes between bundle creation and fetching, return a controlled refusal or require refreshing
the bundle; never silently serve different bytes under the old binding. Reuse fresh final policy
checks and verify full and range responses. Avoid holding database locks during network delivery.
Keep signed URLs, public storage and external hosting outside this package.

Preserve recorded-digest v2 semantics unless evidence proves a change necessary. Live delivery
projections must not make recorded identity depend on elapsed time. Full bundle digest covers
the delivered descriptor; document how exact view digests identify conditioning bytes and how
the recipient verifies downloaded bytes. Additive compatibility must be demonstrated, not assumed.
Keep internal_only. Presentation receipts do not authorize training or redistribution, and an
offline verifier cannot discover later withdrawals. This is not real generative-model execution,
entity-addressed reads, masked Gaussian training, or a personal-data run.

## Executed acceptance

Use actual SQL/store/authenticated routes on generated media: obtain a scene bundle and a place
bundle, fetch their advertised bytes, and verify digests, dimensions, calibration and lineage in
a fresh process without database access. Exercise an unmasked image and an actual generated
masked derivative. Include non-square oriented media so dimension/calibration errors cannot hide.
Label scripted pose outputs explicitly; they do not establish reconstruction quality.

Cover missing/corrupt store objects, stale and missing masks, expiry exactly at the boundary,
withdrawal, selection changes between bundle/fetch and during fetch, cross-workspace IDs, range
requests, malformed view descriptors, tampered downloaded bytes, absent legacy bindings and
unregistered views. Keep control of initial state and demonstrate refusals through actual routes.
Kill negative controls for wrong bytes under a declared digest, missing final permission check
and mismatched camera pixel space. Require the exact selector's own FAILED line for each kill.

Coordinate the exclusive database/full-suite slot with the orchestrator before database mutation
or gates. Use only owned isolated schemas on postgresql://localhost:5433/exulanica_spine_test;
do not alter retained public. Run locked pose/reconstruction extras and the full backend suite,
Ruff, import contracts, web typecheck, boundaries and tests. Recovery assessment is read-only;
if a recovery drill is later dispatched, it must wait for this slot to be released.

Generate new canonical three-key digest-bound evidence with no floats, normalized retained argv
and no personal checkout paths. Predecessor: the consent-timestamp integration record. Preserve
failed attempts and all accepted historical records. Run retained-record checks after generating
the final envelope. Report source/final tips, actual route-to-byte-to-verifier results, control
selectors, digest compatibility and unproved limits. No retained-data activation, personal media,
hosted model calls, paid GPU, merge or push. One-line imperative commits, no trailers, authorship
notices or em dash characters. Stage explicit paths.
