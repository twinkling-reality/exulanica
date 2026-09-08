# Close shared stale-screening admission before personal-data activation

This is the next serialized brief after manual review and personal admission have both landed.
It takes priority over the queued World Read evidence brief because an executed admission
rehearsal exposed a shared policy gap. Do not start from either unintegrated implementation tip.

Repository: `/Users/glendonchin/dev/Technology/orimera`. Product/package: Exulanica.
Read applicable AGENTS.md, the latest integration report, `docs/personal-admission.md`, migration
0037, and the two personal-admission evidence records. Their failed SQL baseline is an observed
defect; their killed command-guard mutant proves only the new Python caller's local guard.

Proposed worktree: `/Users/glendonchin/dev/Technology/exulanica-screening-currency`.
Proposed branch: `codex/screening-currency`. Migration number reserved for this brief: 0040.
Create these only when the orchestrator dispatches this brief after the preceding integrations.
Do not edit old migrations or apply 0040 to retained public. Use isolated schemas on
`postgresql://localhost:5433/exulanica_spine_test` for executed checks.

Observed sequence: authorize exact generated source bytes, add a person region, build a real
masked derivative, write an eligible human screening, change the region outline, and record a
blocked screening. The old receipt still passes `privacy_screening_allows_capture`. The new
command's `require_privacy_screening` checks `capture_mask_is_current` and refuses; frontier
preflight/demonstration and scene admission have direct SQL-policy callers that do not inherit
that guard. Migration 0037's point-map trigger proves that a named masked artifact exists for
the source, not that it corresponds to the current masking inputs. No stale depth write or
disclosure was demonstrated by the original reproducer. Preserve that distinction.

Goal: make current geometry admission and geometry writes that name masked sources obey a shared,
checkable contract, so direct consumers cannot reuse an obsolete screening/mask combination after relevant
region or consent changes. Preserve detection-only permission as a separate purpose; do not turn
it into geometry permission. Do not rewrite dated receipts or invalidate every historical fact.

Writable file set:
- New `exulanica/migrations/0040_bind_geometry_admission_to_current_privacy_inputs.sql`.
- `exulanica/ingest/privacy.py`, `exulanica/ingest/masked_inputs.py`, and
  `exulanica/ingest/spine/privacy.py` for this shared contract only.
- `exulanica/orchestration/preflight.py` and `demonstration.py`, only existing screening
  selection/checking seams if necessary to consume the corrected shared policy.
- New `tests/test_screening_currency.py`; relevant cases in
  `tests/test_personal_admission_flow.py`, `tests/test_person_detection_screening.py`,
  `tests/test_frontier_preflight.py`, `tests/test_frontier_demonstration.py`, and
  `tests/test_masked_scene_inputs.py`.
- New `docs/screening-currency.md`, `scripts/record_screening_currency_evidence.py`, generated
  `docs/evaluation/*-screening-currency.json`, and their uniquely named artifact directories.

No frontend, main.ts, stage registry, new spine module, new workspace-isolated table, route
registration, dependency or RLS-count changes. New columns/functions on existing tables may be
used through 0040 if justified. If actual persisted lineage cannot support a sound check inside
this scope, report the smallest producer/file extension before implementing a second policy or
claiming success. Do not equate the latest timestamp or the existence of any mask with currency.

First document which exact recorded inputs establish currency, how a mask proves it used those
inputs, how relevant consent expiry is evaluated without a write, and what is an immutable
historical receipt versus permission to perform a new operation. Trace direct SQL callers and
existing artifact-read paths. If serving old assets needs a distinct fix, name that remaining
activation dependency explicitly; this brief must not claim a global disclosure guarantee from
admission-only tests. Do not silently expand into all media delivery or World Read release policy.

Execute the baseline sequence against the new shared predicate, the actual frontier preflight,
scene admission and a point-map write attempt. Require obsolete inputs to be refused, then show
rebuild/re-screen/retry succeeds. Exercise region add/edit/delete, consent change and expiry,
withdrawal, cross-workspace requests, unchanged-input retry, no-person review, detection-only
permission and legacy receipts. Prove the relevant policy cannot be bypassed by calling SQL
directly. Include concurrency checks appropriate to the chosen locking/snapshot contract.

Use clearly labelled generated media and the real database/mask path. No personal data, hosted
models, credentials, public migration or GPU spend. Produce one end-to-end evidence record and
executed negative controls; require the exact selector's FAILED line for any killed-mutant claim.
Run the full backend suite with EXULANICA_TEST_DATABASE_URL set to the permitted URL, Ruff,
import-linter, and web typecheck/boundaries/tests. Coordinate the suite slot with the orchestrator.

Evidence has exactly three top-level keys, canonical record_sha256, no floats, and an explicit
predecessor_record. Generate records; preserve accepted historical records. Keep personal paths
and credentials out of retained envelopes. Make one-line imperative commits without trailers,
authorship notices or em dash characters, staging explicit files. Report tip, scope, migrations,
executed criteria, tradeoffs and remaining read/disclosure limits. Do not merge or push.
