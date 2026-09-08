# Presentation consent timestamp consistency

`record_consent` resolves one effective instant after allocating the sequence, then passes that
same value to the existing receipt builder and repository insertion. The receipt builder still
validates the UTC offset before insertion. Caller-supplied instants, including non-UTC offsets,
retain their meaning; canonical receipts encode UTC and PostgreSQL stores the same instant.
No receipt format, SQL writer, reader, sequence allocation, expiry, withdrawal or workspace rule
changes. Migration: NONE.

Source base: `802f902c3cacb631ab80bf43f4348ddbe67734a2`, containing `3352627` and the World Read
recipient integration record and `docs/briefs/2026-09-08-consent-timestamp-consistency.md`.
The orchestrator explicitly reserved the isolated database
and full-suite slot before the first database mutation. Only generated fixtures in the existing
scratch-schema harness use `postgresql://localhost:5433/exulanica_spine_test`.

## Executed path

The deterministic baseline invokes the unchanged real writer and SQL insertion with a clock that
advances one microsecond per read. Its immutable receipt is `2020-01-01T00:00:00Z`; its resolver
column is `2020-01-01T00:00:00.000001+00:00`. Two calls occur and the reader's column check is false.
The retained baseline fails `test_default_time_sql_receipt_uses_one_instant` on the parsed-time
comparison. The negative control restores precisely the source-base `record_consent` function in
a child test process and must fail that same selector with `two-clock effective_at mismatch`.
Neither control changes the recipient reader or repository insertion.

The corrected path adds a subject and region to a generated photograph, invokes `record_consent`
with no `effective_at`, records screening and publishes the fixture scene. The actual stored
canonical bytes are parsed and compared with JSONB, resolver columns and SHA-256. The authenticated
owner route returns a bundle containing that exact receipt and digest. Fresh Python processes
outside the checkout verify the saved bundle without database or Python-path environment settings.
The point maps and pose execution are scripted fixtures; this demonstrates production wiring,
not reconstruction quality or real-person consent.

Coverage includes explicit UTC and non-UTC instants, unchanged region-chain sequence allocation,
naive effective/expiry refusal before insertion, naming permission immediately before and exactly
at expiry, subject-wide withdrawal, and a foreign workspace's route refusal. The withdrawal bundle
is separately evaluated and the live route refuses it. The deterministic clock is scoped only to
`person_review` during the default-time write; no shared datetime module is patched.

## Legacy policy checkpoint

Read-only inspection of migration 0037 shows that consent rows are append-only. The database checks
canonical-byte digest and JSONB agreement, but does not compare receipt time fields against resolver
time columns. The live resolver filters the columns; the recipient projector independently parses
the receipt times and rejects disagreement. It loads every applicable receipt, including
subject-wide withdrawals. The offline reader requires each supplied receipt to be available before
folding the chain, so a later valid grant does not override an unavailable earlier receipt.

A labelled wire-only negative fixture adds the historical disagreement marker beside valid receipts
and confirms `consent_receipt_unavailable`. It is not a migrated database or a historical repair.
No personal rows were inspected and no historical receipt or resolver column was rewritten.

The smallest separate checkpoint would decide which recorded meaning is authoritative when the
two times differ and define an explicit, auditable correction/supersession contract. Any approved
schema or reader-policy change would need to preserve original bytes and digests, bind the original
and corrected interpretations, specify chain completeness and withdrawal precedence, and test live
and offline behavior on generated legacy disagreements. Such a policy/migration requires a separate
scope; neither in-place normalization nor an assumed append-only cure is authorized here.

Retained-public deployment through migrations 0039-0041 remains separate. This change allocates no
migration and performs no activation, hosted inference, GPU work, merge or push. Saved bundles cannot
discover later withdrawals; presentation receipts do not authenticate the person's authority or
supply training or redistribution permission.

## Retained attempts

The baseline directory retains the expected one-microsecond SQL disagreement. Attempt 01 passed
all six new cases, the exact-selector negative control and the full backend suite, then failed Ruff
on annotations/import spacing/line lengths in its generated control plugin. No acceptance envelope
was written for that attempt. Its executed plugin bytes are preserved as `mutant_two_clocks.py.txt`
with a filename note; the original failure log is unchanged. The generator was corrected and a
fresh campaign repeated all gates. This is an evidence-tooling correction, not a production-code
change. The production writer and regression tests remain byte-identical to `970c6bc`.

## Final verification

Tested source: `ec638182d95339fe295aa8a1b587c04326574cd8`. The full backend passed
2152 tests with 3 skips using locked pose and reconstruction extras. Ruff, all four import
contracts, web typecheck, web boundaries and all 876 web tests passed. Retained-record tests
passed after the final envelope was written. An additional independent check reproduced its
canonical digest and all 38 artifact bindings, rejected float values and checked path normalization.

[Final campaign](evaluation/2026-09-08-final-consent-timestamp-consistency.json) follows the
World Read recipient integration record and binds the baseline and unsuccessful first attempt.

- Campaign record SHA-256: `30089be19b184cea014bed9492a8891c469a7533866c8294fede4c044be7b248`
- Default-time receipt SHA-256: `68c25425e05667a58da68202745d71338a49fa4dd8d968d752fafbbb85b097de`
- Authenticated bundle SHA-256: `db7d38a4f3b39c66dfe874e3975ebcdbcc606ecc09a0e50c8780069709b4ce3b`
- Recorded-input SHA-256: `170ed0326e06a13d1ea167b4d59a4c54c21a5a1331134f37f5e20fdfd61a3bb8`
