# ADR-0021: Exactness belongs to observed content, and the wider closure remains open

- Status: Accepted
- Date: 2026-09-05

## Invariant and rationale

Deleting a confirmed exemplar must remove it from the contextual proposal index. Rebuilding
from the surviving evidence must reproduce the same canonical payload and dependency set that
existed before that exemplar was introduced. A persisted payload that disagrees with its
content-derived key raises `IntegrityError`; a cache hit cannot turn corruption into authority.
Historical generations stay stale, so a later identical payload has a different generation ID.
No exactness claim applies to `vision` or `depth`. ADR-0017's deterministic stage flag remains
a request to report divergence, not evidence that divergence cannot occur.

## Observed scope

The experiment in `tests/test_recomputation_closure.py` uses the first three courtyard-spring
frames of SYNTH-1, seed 20260905 and three frames per trip. The real photo pipeline ingests them;
a named scripted detector supplies satchel occurrences. The independent baseline uses the first
two sources before the third exists. After confirming and deleting the third exemplar:

- The canonical exemplar payload and dependencies match the two-source baseline exactly.
- Four stored intake/rendition payloads are physically evicted, their absence is checked, and
  the actual deterministic stages regenerate identical bytes. No model is called during this
  recomputation. This is a same-runtime result over these synthetic sources.
- The historical index generation differs, by design. The append-only database and ledger
  therefore are not a bit-identical state.
- The served scene-group projection differs. Existing grouping writes preserve earlier live
  rows, and ordinary capture deletion filters members without recomputing the stored centroid,
  time bounds, radius or positioned-member count. The observed projection grows from two rows
  to three; the last row has two live members but retains metadata computed from three.
  **This is an unresolved aggregate-withdrawal defect and blocks a whole-closure A-24 claim.**
  The experiment retains both projections rather than normalising the difference away.

`scripts/measure_pose_recomputation.py` also runs the real CPU PyCOLMAP executor twice in fresh
directories over the same eight-view synthetic room and pose manifest. Both runs recover all
eight cameras and pass the configured pose quality gate. Both `reused` flags are false. Their
receipt hashes and quality hashes differ. This is observed same-host nondeterminism, not a
failure to find any pose; it is not a metric-scale, corridor or rendering result. The script
refuses to compare runs with fewer than three recovered cameras. Its digest-labelled local
runtime fingerprint is explicitly not a container image. `scene-pose-residual` is now measured
as non-identical for this fixture; exact pose reproduction and cross-machine bounds stay open.

## Canonical representation

The exemplar payload uses `exulanica.identity-match-context/v1` and strict integer-safe
`canonical_json`. The retained observation contains the exact before/after payloads and served
scene projections, byte digests, generation IDs, source digests and exclusions. Pose receipts
retain their existing `exulanica.colmap-pose-receipt/v2` encoding, including its floats. Their
exact bytes are separate retained artifacts referenced by SHA-256 from the integer-safe goal
record. No rounding is performed to obtain equality.

## Compatibility impact and failure behaviour

Only a mismatched stored exemplar payload gains a new refusal. No migration or stage identity
changes. No stale generation is revived. The existing deterministic stage writer still records
`nondeterminism_detected` and `needs_repair` rather than replacing content under an old key.
Scene metadata differences and pose differences are disclosed as limits, not accepted as exact.

## Affected surfaces and tests

The production change is in `exulanica/identity/match_context.py`. The experiment exercises photo
workers, artifact storage, identity decisions, capture tombstones and the graph projection.
There are no API, schema, migration, export or browser changes in this decision.

`tests/test_recomputation_closure.py` has executed negative controls for admitting the deleted
anchor, injecting an index nonce, skipping canonical-key integrity and changing rendition bytes.
`tests/test_unblocked_program_record.py` checks the retained comparisons and model exclusions.
The program record retains the executed controls and references the exact evidence artifacts.
