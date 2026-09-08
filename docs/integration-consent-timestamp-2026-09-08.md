# Consent timestamp integration, 2026-09-08

Integrated after independent gates at `d72c4f8`: 2152 backend tests passed, 3 skipped;
876 web tests passed; Ruff, four import contracts, typecheck and boundaries passed. Locked pose
and reconstruction extras were installed. All three patches from owner tip `16fec10` were
unchanged when rebased onto reservation commit `b13b487`. The owner's tested source was
`ec63818`; subsequent candidate changes were documentation and evidence only.

The integration envelope is `evaluation/2026-09-08-consent-timestamp-integration.json`. It follows
the final campaign envelope and binds eight independent environment/gate/offline replay logs.
The owner envelope, predecessor and all 38 tracked bindings were independently verified. The
negative control's exact selector has its own FAILED line and the two-clock mismatch reason.

## What changed and what ran

The production edit is limited to record_consent: resolve effective_at once, then pass the same
instant to the receipt builder and SQL insertion. Explicit UTC and offset instants retain their
meaning. Existing receipt validation, sequence allocation, reader checks, expiry, withdrawal and
workspace boundaries were not changed. No migration was added.

The deterministic baseline uses the actual writer and SQL insertion with an advancing clock:
the old receipt encodes midnight while its resolver column is one microsecond later. The control
restores the exact original function from the source-base commit; it does not approximate the
defect or disable the reader. The corrected test compares canonical bytes, JSONB, columns and
digest, then exercises the default-time write through the authenticated World Read route and
clean-process recipient verifier. The advancing clock is local to person_review, not a global
datetime replacement.

Four independent saved-bundle replays ran outside the repository without database or Python-path
environment settings: before naming expiry, exactly at expiry, after recorded withdrawal, and
legacy-chain refusal. All matched their retained outcomes. Generated photographs and scripted
point/pose publication establish the handoff, not real-person consent or reconstruction quality.

The first owner's campaign passed backend checks but failed Ruff on the generated control plugin.
The generator was corrected and all gates rerun. The original executed plugin is preserved as
.py.txt with an archive filename note, alongside the actual failure log; no accepted envelope was
rewritten. Bound logs retain tool-produced whitespace rather than being edited after verification.

## Limits and next decisions

This fixes future writes. Historical receipt/column disagreements remain unavailable to the
recipient reader, including when a later valid grant exists in the chain. The legacy exercise is
a labelled wire fixture; it neither repairs a database nor establishes a backfill. Any correction
or supersession policy must preserve original bytes, identify the authoritative interpretation
and be separately scoped. No such policy, schema change or historical normalization was applied.

The post-gate retained-public snapshot remains migration 0038, 284 captures, 880 artifacts,
5 scenes and 0 person regions. Deployment through 0039-0041 is still a separate action. Release
remains internal_only; actor receipts do not authenticate subject authority or redistribution
rights, and offline bundles cannot discover later withdrawals.

No public migration or activation, personal-media run, hosted model, GPU spend or push occurred.
Main remains unpushed. Backup/recovery and explicit deployment readiness remain operational work;
this integration does not automatically dispatch a legacy-repair or activation task.
