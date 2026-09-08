# Use one effective instant for each presentation receipt

Queued for dispatch after World Read recipient evidence integration; no task started.
Repository: `/Users/glendonchin/dev/Technology/orimera`; product/package: Exulanica.
Read applicable AGENTS.md, `docs/integration-world-read-recipient-2026-09-08.md`,
`docs/world-read-recipient-evidence.md`, person_review.record_consent, its actual receipt and SQL
insertion callees, and world_read_evidence._consent_columns_match.

Proposed worktree: `/Users/glendonchin/dev/Technology/exulanica-consent-timestamp-consistency`.
Proposed branch: `codex/consent-timestamp-consistency`, from main containing `3352627` and this brief.
Migration: NONE. Do not change old migrations or allocate a new one.

Observed code defect: record_consent independently evaluates effective_at or datetime.now for the
immutable receipt and the resolver column. With no supplied effective_at these can differ. The new
recipient reader refuses the disagreement. Existing campaign grants supplied an explicit instant;
they did not execute this default-time handoff. Goal: one validated effective instant per new
receipt, persisted identically in the canonical record and resolver column, preserving caller-
supplied times and existing sequence, withdrawal, expiry and workspace semantics.

Writable files:
- `exulanica/ingest/person_review.py`, record_consent's effective-time resolution only.
- New `tests/test_consent_timestamp_consistency.py` for the deterministic baseline and actual
  writer-to-recipient path. Import existing fixtures without changing their shared setup.
- New `docs/consent-timestamp-consistency.md`,
  `scripts/record_consent_timestamp_consistency_evidence.py`, generated
  `docs/evaluation/*-consent-timestamp-consistency.json` and uniquely named artifacts.

All other files are read-only, especially recipient verification, consent receipt/schema code,
SQL insertion, migrations, routes, main.ts, stage/route registries and existing evidence records.
If another caller or producing seam needs a change, give the exact file and executed mismatch
before extending scope. Do not relax the reader's column/receipt consistency check to pass a test.

Use a deterministic advancing clock to show the existing double-read mismatch, then execute the
real default-time writer into an isolated database and compare parsed canonical receipt fields,
stored columns and digest. Execute an authenticated World Read route and clean-process recipient
verification containing that receipt on generated media. Retain explicit-time, expiry, withdrawal
and foreign-workspace refusal coverage. A mocked insert alone does not establish production wiring.
Include an exact-selector negative control that restores the two-clock defect and fails.

Inspect the legacy disagreement semantics read-only. Do not rewrite immutable historical receipts,
normalize resolver columns in place or invent a backfill. The reader currently rejects any mismatched
receipt in the supplied chain; do not claim a new appended grant repairs old rows without evidence.
Describe the smallest separate policy/migration checkpoint if legacy repair is needed. No real
personal rows need to be inspected for the generated-fixture acceptance path.

Reserve the serialized full-suite slot with the orchestrator before database mutation or gates.
Use isolated schemas on `postgresql://localhost:5433/exulanica_spine_test`; no retained-public
migration or activation, personal media, hosted models, GPU spend, merge or push. Run the full
backend suite with EXULANICA_TEST_DATABASE_URL set to that URL and locked pose/reconstruction
extras, Ruff, import-linter and web typecheck/boundaries/tests. Preserve failed attempts.

Generate a three-key canonical digest-bound envelope with no floats or personal checkout paths,
and predecessor_record pointing to the World Read recipient integration record. Normalize retained
argv as well as logs. Run retained-record checks after writing the last envelope, not only before
generation. Preserve accepted records. Stage explicit paths; use one-line imperative commits
without trailers, authorship notices or em dash characters. Report exact source/final tips,
executed default-time handoff, evidence digests and unresolved legacy/deployment limits.
