# World Read recipient evidence integration, 2026-09-08

Follow-up: `integration-consent-timestamp-2026-09-08.md` records the future-write timestamp fix.
Historical mismatched chains remain unavailable; this report retains the earlier verified state.

The branch is integrated after independent gates at `3352627`: 2146 backend tests passed,
3 skipped; 876 web tests passed; Ruff, all four import contracts, typecheck and boundaries passed.
Locked pose and reconstruction extras were installed. The candidate already descended from main
`8d47fb1`, so no rebase was needed. Executable source was unchanged after the owner's corrected `0120faf` run.
The orchestrator implemented no feature code.

The integration envelope is `evaluation/2026-09-08-world-read-recipient-integration.json`, following
the owner's verification envelope. It binds the independent environment, six gates and offline
replay log. All four owner envelopes and all 148 tracked artifact bindings were verified. All six
controls have their exact selector's FAILED line. The orchestrator independently replayed the ten original and eighteen successor
saved fixtures in fresh processes outside the repository, without database environment variables;
results matched the retained evaluations, including stale-mask refusal and legacy unavailability.

## Contract and evidence

The authenticated World Read assembly now includes recorded presentation receipts and persisted
geometry source lineage. Receipt chains are evaluated offline at an explicit zoned time. Presence,
naming, likeness and temporary hide remain separate. Opaque identifiers needed for receipt hashes
do not authenticate the subject or the account holder's authority. Release remains internal_only;
training and redistribution permission are not inferred from presentation receipts.

Historical masks are checked against the point map's own screening snapshot, persisted mask input
commitment and exact manifest. Existing snapshots supported the exercised fixtures without a new
producer or migration. A current-looking mask is not substituted for the source actually used.
Legacy missing lineage remains unavailable; the legacy replay is a labelled wire fixture, not a
demonstrated legacy database migration or backfill. Masked Gaussian training is still unsupported.

Recorded digest compatibility changes deliberately. The v2 recipe excludes scene, views, geometry,
rungs and generated projections from recorded_sha256 because delivery fields can vary at expiry
without a write. Recorded evidence retains the source and receipt bindings; bundle_sha256 still
covers the complete response. Consumers must distinguish v1 and v2 conditioning identities.
Scene/place addressing and release scope remain unchanged. This does not prove a dishonest issuer
supplied complete history: trusted expected digests are required, and unsigned history can be
omitted and rehashed by its issuer. Offline recipients cannot discover later withdrawals.

The elapsed-time test obtains its first bundle through the authenticated route, observes that
the route later refuses after expiry, and uses the internal bundle assembler to compare the
recorded digest. It does not claim the expired bundle remains publicly deliverable. Generated
photographs use real masks; point, pose and training publication outputs are scripted. These
checks establish wiring and recipient verification, not geometry quality or real-person consent.

## Independent review correction

The original candidate `1328935` passed the independent 2124-test backend suite and remaining
full gates, but code review exposed an uncovered receipt-shape failure. The receipt loader labelled
any digest-valid JSON available, then called object methods on mask candidates. A stored array/null
could crash the authenticated route even beside a valid exact manifest. The owner reproduced it
through real database/store/route fixtures; the baseline remains bound in successor evidence.

Under authorization `8d47fb1`, projection now validates expected profiles, required field types and
supported top-level fields before using receipt payloads. Unsupported content is withheld with
named reasons. Valid exact candidates remain usable. The offline CLI uses controlled JSON errors.
Twenty-two added regression cases cover persisted mask and trained-receipt scenarios plus fresh-
process offline checks; an added control restores the original route failure. Both original
envelopes remain byte-identical. Corrected evidence is a successor, not a rewrite of passing
observations that happened to omit the failing case. The independent final gates above include
that corrected runtime and its generated records.

## Remaining producer defect and next brief

The reported timestamp mismatch is confirmed in `exulanica/ingest/person_review.py::record_consent`:
when effective_at is omitted, one clock call constructs the immutable receipt and a second
populates the resolver column. The reader checks agreement and returns
consent_columns_disagree_with_receipt; it does not silently choose one meaning. The campaign's
explicit-time fixture grants do not prove the ordinary default-time writer path works end to end.

The next scoped brief is `briefs/2026-09-08-consent-timestamp-consistency.md`. It fixes future writes
using one instant and requires an executed writer-to-recipient path. Historical disagreeing rows
need a separate decision: simply appending a new receipt cannot be assumed to cure a chain whose
older receipt still fails validation. No historical receipt rewrite or migration is authorized.

After the independent gates, retained public still has migration 0038, 284 captures, 880 artifacts,
5 scenes and 0 person regions. This task adds no migration; runtime deployment through 0041 remains
separate. No personal-media run, hosted inference, GPU spend, public migration, merge by the owner
or push was performed. Main remains unpushed. No next implementation task was dispatched here.
