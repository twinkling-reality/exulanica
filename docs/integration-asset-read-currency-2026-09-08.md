# Asset-read currency integration, 2026-09-08

The asset-read branch is integrated on main after independent gates at `188e20c`:
2118 backend tests passed, 3 skipped; 876 web tests passed; Ruff, four import contracts,
typecheck and frontend boundaries passed. Locked pose and reconstruction extras were installed.
All nine patches from owner tip `d434fea` were unchanged when rebased onto main `6d12621`.
The initial runtime campaign used `03501ce`; recorder repair was tested at `b845bad`. Runtime and
test sources remained identical to `d4cffba`; the final integration candidate includes the repaired
recorder and generated records.

The independent verification envelope is `evaluation/2026-09-08-asset-read-currency-integration.json`.
It binds seven environment/gate logs and follows the owner's verification record. The orchestrator
verified three owner envelopes, 419 file bindings across 408 distinct tracked paths, 70 retained
response bodies and 40 stored-object hashes. Historical source bindings were checked at their
recorded heads. All six controls contain their exact selector's own FAILED line.

## Executed behavior and integration findings

Original, crop and by-URI image routes retain exact-byte semantics and refuse when current
presentation policy requires a mask. Existing original URLs do not establish reviewer privilege.
New viewer image references always use /masked. Required absent, stale or corrupt viewer bytes
are withheld. Source metadata verifies selected viewer bytes and retains live capture identity
for manual review without granting an asset reference when those bytes are unavailable.

Point maps and trained scene delivery check actual persisted source lineage. A newly rebuilt mask
does not make geometry built from old inputs current. Graph/World Read retain their consistent
metadata snapshots; embedded geometry receives a final fresh check. Policy-refused point-map
descriptors are omitted using the existing schema, rather than mislabelled bytes_missing.

Final delivery checks run after local byte buffering and hash verification, as the real SELECT-only,
non-owner/non-BYPASSRLS runtime role. The final database instant follows acquisition of a global
asset barrier. Dependencies committed before that instant are visible; later permission changes
apply to later requests. Locks are released before network delivery. No retraction of delivered
bytes or continuing authorization from a metadata response is promised.

The barrier's dependency writers use a shared try-lock and must retry the whole transaction after
40001. This avoids waiting for delivery while holding other locks. It deliberately introduces
cross-workspace contention; throughput and retry load have not been benchmarked. Runtime row
mutations are covered; administrative DDL/TRUNCATE requires separate deployment control.

The owner reproduced an actual export_training_dataset versus record_consent deadlock (40P01),
retained its baseline, and changed the privacy helper in 0041 to acquire training-source before
privacy. Its regression and lock-order mutant exercise those actual callers. Prior migrations
0037 through 0040 were not edited. The existing world-style test changed only its approved URL
expectation; other assertions and fixtures remain intact.

The orchestrator briefly proposed that source metadata only checked file existence. That finding
was wrong: it relied on an earlier implementation diff. The final tested _source_from_row also
calls store.get(), which verifies the selected content digest. Reading the current full function
and its callee disproved the finding. No code or accepted record was changed for it.

## Independent rejection and evidence repair

The first independent suite at `d4cffba` returned 2117 passed, 3 skipped and one failed retained-
record check. The generated acceptance envelope contained fourteen personal checkout paths in
commands.argv: logs were normalized, but command metadata was not. The owner's earlier full gates
ran before this envelope existed, and digest verification alone did not catch its disclosure-rule
violation. The candidate was rejected before merge.

Under the explicit 520a192 exception, the recorder normalized stored command provenance while
executing actual paths, regenerated only the two unpublished dependent candidates with their old
hashes and replacement reason recorded, and added post-generation retained-record checks. Accepted
main records and the valid checkpoint were preserved. The independent failed log is retained in
artifacts/2026-09-08-asset-read-currency-repair-01/independent-backend-failure.log. The corrected final
candidate then passed the independent gates above. The repair changed no runtime or test source.

## Limits and next work

Generated-media tests use the real mask path and authenticated routes. Scripted point/scene
publication tests establish lineage and delivery behavior, not reconstruction quality. Masked
splat production remains unsupported at the existing held-out remapping seam. Purge interleavings
exercise the real object lock and metadata mutation, not destructive operating-system unlink.
Intermediate development and recorder failures remain retained, rather than hidden by the final run.

The post-gate retained-public snapshot remains at migration 0038, with 284 captures, 880 artifacts,
5 scenes and 0 person regions. No retained-public migration or activation was performed. This
runtime now requires migration 0041; the 0039-0041 deployment remains a separate authorized action.
Two empty test schemas reported by the owner could not be attributed and were deliberately left
untouched. Neither handoff nor integration claims global database cleanup.

The next feature brief is `briefs/2026-09-08-world-read-evidence.md`, now unblocked for scoping and
dispatch after this integration. It adds recipient-checkable evidence, retains internal_only
release, and does not imply successful masked training or personal-world validation. A parallel
read-only backup/recovery assessment is separate. No new feature task was started here.

No personal-media run, hosted model, GPU spend, public migration or push was performed. Main's
off-device backup and a verified database/artifact restore remain operational work.
