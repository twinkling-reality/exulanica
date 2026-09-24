# Personal admission and re-screening

A personal photograph is admitted under account authority, screened for people, and read by a
model only under a personal model right. This page is the contract for all three.

## Personal model rights

A screening receipt answers whether a photograph may be looked at (`person_detection_only`) or
become geometry (an eligible human review). Neither names a model or a destination, so a receipt
recorded for one model used to let every other model, local or hosted, receive the same bytes.
Migration 0073 adds a separate object, the personal model right, and no byte of a personal
photograph reaches a model unless one is current for that model and that destination. A right is
not a screening and a screening is not a right: every model read requires both.

A right (`personal_model_right`, workspace isolated under row-level security) binds:

- the exact capture and its source SHA-256;
- the operation, `model_processing`;
- the model as the manifest states it: provider, role, identifier and full revision. Hosted
  providers expose no per-model revision, so a hosted right carries none and never matches a right
  that names one. A local checkpoint is always pinned to a full commit;
- the destination: `local-process`, or the exact origin the egress allowlist would have to declare,
  spelled as `exulanica.models.egress.Origin` spells it;
- the personal authority it was granted under, the account holder that authority names as
  `granted_by`, the grant time, a required expiry and a purpose;
- a withdrawal (`withdrawn_at`, `withdrawn_by`), which is final. Rights are never deleted and
  nothing else about them changes; a different model, destination or term is a new right.

The receipt is canonical JSON bound by SHA-256, and the database refuses a receipt that disagrees
with its columns, a grantor who is not the authority's account holder, an authority that was not
current at the grant, a future grant, a deletion and any update other than one withdrawal. A right
lapses with the authority it was granted under.

**Deny by default.** A capture needs no right only when the presented screening was issued under a
synthetic or benchmark authority and no other kind of authority in the workspace covers the same
bytes. Bytes anybody has authorized as personal stay personal whichever receipt a caller presents,
including under a capture that re-imported them after the first was deleted, and a session whose
workspace is unknown is never treated as exempt.

**The one check.** Every model read of personal bytes goes through
`exulanica.ingest.model_rights.require_model_right`:

```python
def require_model_right(
    repository: IngestRepository,
    capture_id: uuid.UUID,
    screening_id: uuid.UUID,
    handoff: ModelHandoff | None,
) -> ModelRightDecision
```

`ModelHandoff` names every model one call can reach and the one destination the bytes travel to.
`ModelHandoff.hosted(manifest, role)` names a manifest role's whole chain at the manifest's
endpoint, because the client falls back on a withdrawn identifier and either model can receive the
request; a right for the primary does not cover the fallback. `ModelHandoff.local(...)` names
checkpoints loaded in this process. `None` means the caller cannot state the model or destination,
which is refused whenever a right is required.

The function resolves a candidate right for each identity, then decides everything in one
evaluation inside the same final read check the environment and graph read paths use,
[`final_read_check`](../exulanica/db/read_check.py): the global asset read lock, a read-only
transaction and one evaluation instant. The screening must still permit these bytes to be looked at
(`asset_observation_allows`, a lock-free statement of `privacy_screening_allows_observation`), and
each identity must be named by a current right (`personal_model_right_allows`). A grant or
withdrawal cannot commit while that check holds the lock, so a withdrawal is either seen or refused
until the check finishes. The lock is released before the model is called. Call the function
immediately before handing the bytes over, after they are read and verified; geometry callers still
ask `require_privacy_screening` first.

It raises `PrivacyAdmissionError` when the screening no longer holds, and `ModelRightRefused` (a
subclass) otherwise, with `reason` one of `undeclared`, `missing`, `expired`, `withdrawn`,
`lapsed`, `other_model` (another identifier or another revision), `other_destination` and
`changed`. It returns a `ModelRightDecision` naming the rights that permitted the hand-over.
`grant_model_right`, `withdraw_model_right` and `model_rights_for_capture` are the writers and the
reader. `POST /personal-admission/model-rights/{right_id}/withdraw` (permission `admission.write`)
withdraws one right for the caller's workspace and answers with the right's reference and
`"state": "ended"`; a second withdrawal changes nothing, and another workspace's right gets the same
404 as an id nobody granted.

**Stopping a search right deletes the search entries made from the photograph.** Withdrawing a
right for the `embedding` role, "Search index" in the photo drawer, writes a `caption_search`
tombstone over the photograph in the same transaction
(`exulanica/migrations/0104_a_stopped_search_right_deletes_its_search_entries.sql`). Its cascade
records every search entry made from the photograph's descriptions and queues their purge, and the
purge worker deletes them as it deletes a deleted photograph's (`exulanica/deletion/worker.py`). An
entry made by a model that another current search right still covers for the same photograph is
kept until that right stops too; the drawer's stop ends every current right of the role at once,
so stopping "Search index" there deletes every entry. A model call that was allowed when it left
and returns after the stop is refused by the database, and its result is not stored. The
photograph, its descriptions and its other rights stay, so the photograph can still be found by the
words of its own description, a match made in the database without any model; only the entries the
search model made are deleted. The deletion is as prompt as the purge worker, and until it runs the
entries still exist while the search already leaves them out (`exulanica/selection/embeddings.py`),
as it does a deleted photograph's. An expiry deletes nothing.
`tests/test_search_entries_on_stop.py` holds this through the runtime and purge roles. A restore
writes the stop again from its checkpoint before it replays the stop's tombstone, so a backup taken
before the stop comes back with the right stopped and its entries deleted
([ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md)).

**Where it is enforced.** The vision stage (hosted), the depth stage and the segmentation stage
(local) call it immediately before their model; a refusal records `stage_unavailable` with the
reason and sends nothing. The person-region stage does the same for any person detector that
reads pixels, asking first for a receipt that lets the bytes be looked at, so a pipeline built
directly is gated as the derivative worker is; the recorded-observation detector and the test
doubles that discard the image are exempt by exact type, and a subclass of one is not. Every model
states its hand-over with a `model_handoff` attribute or is refused: `NebiusVisionModel` states its
role's whole chain and the endpoint of the manifest its client was built with; depth states MoGe's
`repo@revision`; segmentation states the segmenter's pinned identity and adds the detector and its
fallback only when the local detector will run. The value types, `ModelIdentity` and
`ModelHandoff`, live in `exulanica.models.handoff` so a model in any layer can state them.

**Text derived from a personal photograph counts.** The caption the vision model writes goes to
the hosted embedding model only under a current right naming the embedding role's whole chain and
its endpoint. `embed_capture` takes a required `before_send`: it holds a session lock on the
capture, reads the text in a short transaction, calls `before_send` with the hand-over on the idle
connection, sends with no transaction open, and writes the vector in a transaction that re-reads
the text and stores nothing if it changed or went. The derivative worker's `before_send` asks
`require_model_right` with the capture's screening, and refuses outright when the capture has no
screening. A pass that states no `model_handoff` runs only for a capture that needs no right. A
refusal leaves the capture succeeded, sends nothing, and is recorded as the `message` of its
`capture_succeeded` event, readable at `GET /operations/derivative-jobs/{job_id}/events`. Name the
`embedding` role in `model_rights`, beside `vision`, to grant both in one admission.

**Not covered yet.**

- Scene pose (COLMAP, classic feature matching with no learned weights) runs under the scene
  privacy admission only. Gaussian-splat training runs a learned perceptual metric (LPIPS) in its
  container on whichever host runs the scene worker, and asks for no model right. Until both
  require a right naming the model and the host, neither is to be run over personal captures, on a
  GPU or on a remote machine.
- Place alignment's joint reconstruction stages original photographs for pose under a deletion
  check only. No API or worker path calls it; a verification script and tests do.
- Benchmark captures keep their recorded license as their model permission; no per-model right
  applies to them.
- The observation half of the final check restates `privacy_screening_allows_observation`, whose
  detection-only branch does not consult withdrawn people or tombstoned entities, so an unmasked
  rendition can reach a detector under a detection receipt and a right.
- Rights are append-only against every row-level write, but the table owner can still `TRUNCATE`
  the table, as for the other receipt tables; the runtime role holds no such privilege.
- Scripts that run MoGe or pycolmap over a folder of files
  (`scripts/reconstruction_moge_scale_vs_colmap.py`, `scripts/reconstruction_pycolmap_run.py`,
  `scripts/measure_extraction_memory.py`) read files rather than the store and check nothing.
- The frontier demonstration and its preflight check screening receipts but not rights; a personal
  capture without a right is reported with vision unavailable rather than refused up front.

**Existing data.** Captures screened before migration 0073 have no right, and the migration writes
none. Their receipts keep their meaning, but no model receives their bytes until the account
holder grants a right. The detection pass of the ordinary batch path, which used to send every
admitted photograph to the hosted vision model, now sends nothing unless the batch names the
vision role. Caption vectors stored before this change stay, and no new caption text about a
personal capture is sent until its account holder grants the embedding role. The migration path is
to admit the same captures again with `model_rights`.

## Ordinary API batch path

`POST /intake` returns exact capture IDs and original digests. Send those captures to
`POST /personal-admission` as one `members` inventory. The route uses the ordinary API connection,
including its public schema, authenticated workspace and actor. It does not provision or migrate
schemas. The CLI below retains its isolated-schema restriction.

The JSON body contains `operation` (`detect` or `review`), `purpose`, `authority` (the same three
fields as the command), `recorded_at`, and `members`. Each member contains `capture_id`, `sha256`,
and `bytes`. Unknown fields and coerced scalar types are refused. The server validates the complete
inventory, stored original bytes, authority interval, and time before writing any receipt; duplicate
captures, future times and expired authority are refused. Receipt writes and queue admission are
atomic across the batch. The request cannot choose an actor or workspace.

For `detect`, each member has `review: "not-reviewed"` and no edits (both are defaults). No human
review is claimed. The response contains a batch ID, queued job ID and one personal authority and
`person_detection_only` receipt per member. The queued worker prefers current eligible screening;
otherwise it checks the SQL observation predicate for an explicit detection-only receipt. It offers
vision and the recorded-observation person detector under that receipt. This path supplies neither
a depth model nor a geometry segmenter. Hosted vision still requires the deployment's configured
model client and spending guard; admission does not create a spending authorization.

The optional `model_rights` list (at most eight entries, default empty) is how the account holder
lets models receive the admitted photographs. Each entry is
`{"role": ..., "valid_until": ..., "notice": ...}` naming a role the manifest states: a hosted role
such as `vision` or `embedding`, or a local role (`object_segmentation`,
`open_vocabulary_detection`, `depth`). `GET /personal-admission` states, in `model_right_offers`,
each role the app offers, with the notice a person reads before allowing it and `offered_with`, the
admission the app offers it with: `review` for `depth`, `detect` for `vision`, `embedding` and
`reasoning_cheap`. An offered role's entry must carry that notice exactly, and any other text, or
none, is refused; any other role is granted only with no notice. The server records one right per
member for every model the role can reach, under that member's new personal authority, granted by
the session actor at `recorded_at`, and the authority's scope records each role's term and notice.
Each role appears once, and each term must end in the future and no later than the authority.
`depth` names the MoGe checkpoint the manifest pins as `local_roles.depth`, the one the derivative
worker loads. The whole list is validated before any receipt is written. Each response receipt
carries `model_right_ids` and `model_rights` (identity, destination, term and receipt digest, never
the purpose). A batch that names no role records no right, and the worker then sends its photographs
to no model. A replay with the same `request_id` reports each granted right as `current` or `ended`,
and `GET /personal-admission` lists the rights the actor granted over each source, each with
`notice_current`, true only when the server states words for the right's role and the right was
granted against exactly those words. Neither answer is a permission. A search right granted
against the role's earlier words, which said the search entries already made would stay, is listed
with `notice_current` false, and the drawer shows it as allowed without the wording shown; stopping
it deletes those entries as well, which removes more than those words said and nothing they
promised to keep for the person.
`POST /personal-admission/model-rights/{right_id}/withdraw` ends one right.

For `review`, supply `reviewed_by_name`, `attestation`, and either `no-person` or `confirmed-regions`
on every member. The attestation must exactly read:

> I personally inspected every exact photograph in this inventory and reviewed all people and sensitive person regions, including any missed by the detector.

The caller supplies that statement; the server never supplies it for them. A no-person review is
refused when regions remain. A confirmed-regions review requires every proposal to have been
confirmed or explicitly removed. Optional `edits` use the command's existing format. The named
review and statement are retained in the authorization scope, which is digest-bound into the same
human-screening receipt that the command writes. The response's `eligibility_state` is authoritative:
a recorded review can remain blocked until current masks exist. Account authority and review do
not establish a subject's likeness consent.

`POST /identity/subjects/link` accepts `regions: [{capture_id, region_key}, ...]` and an optional
`subject_id`. Omitting the subject creates one subject for the whole selected set. Supplying the
returned ID links further photographs to the same person. Each region gets an immutable human
confirmation; the transaction refuses unknown subjects or regions without applying a partial set.
`POST /identity/subjects/unlink` requires the current `subject_id` and selected regions and appends
confirmations with no linked subject. Existing consents and previous edits remain historical.
`POST /person-subjects/{subject_id}/consents` continues to record the account holder's consent
statement. Ordinary outline confirmations preserve an existing subject when `subject_id` is omitted;
explicit null unlinks it. An edit request names each region at most once; duplicate keys are
refused before any edit is written. Changed links invalidate screenings through the existing currency policy.

The API path and worker change do not deliver HEIC conversion or a fresh workspace's source
inspector. Those require extensions outside the writable set, including a distinct decoded
source permission in SQL. No migration has been applied or reserved for this work. No hosted calls
have been authorized in this task.

The final focused run passed 89 PostgreSQL tests on scratch schemas in `exulanica_inspect_test`.
The fresh public-copy rehearsal then refused all three predecessor JPEGs at `/intake`, before the
new admission route: `artifact_pkey` collides when another workspace already holds the same bytes.
`artifact_id_for` derives a global ID from a key without workspace identity, while artifact lookup
is workspace-scoped. The first-place workspace and bytes were preserved. This is an additional
release blocker, not a successful acceptance run. The digest-bound attempt is recorded in
`2026-09-11-personal-path`, a local-only evaluation record a clone does not contain.
The integration coordinator owns the deferred single full-backend suite and document index update.

## Historical isolated command and evidence

This is an operator command for exact capture bytes. It composes existing intake, personal
account authority, privacy screenings, person review receipts and mask stages. It writes no
benchmark provenance, creates no new receipt table and applies no migration. Migration 0039
must already be installed in the selected isolated schema. Public is not an allowed target.

**Real personal-data activation remains blocked on a separate shared SQL policy follow-up.**
The existing `privacy_screening_allows_capture` predicate accepts an old eligible receipt after a
region changes, even when a new human screening is blocked. Frontier preflight, demonstration and
`admit_reconstruction_scene` have direct SQL-predicate paths. This change strengthens the Python
`require_privacy_screening` boundary with the existing `capture_mask_is_current` check. It does
not globally invalidate historical receipts, nor prove that stale geometry was produced or served.
After a mask is rebuilt, currency alone does not force callers to choose the new screening.
Operators must explicitly re-screen and use the new receipt. The shared policy follow-up must
close that historical-receipt gap before real-data activation.

## Command and manifest

```sh
uv run python -m exulanica.ingest.personal_admission_command \
  --schema exulanica_personal_operator_run \
  --manifest /outside-git/admission.json \
  --photo-dir /outside-git/authorized-photos \
  --data-dir /outside-git/personal-store
```

The database is fixed to `postgresql://localhost:5433/exulanica_spine_test`. The operator must
explicitly create and migrate the isolated `exulanica_personal_*` schema beforehand. A missing
schema or pending migration produces an actionable JSON refusal before provisioning, intake or
store writes. The command never invokes a migration operation. The recorder alone creates and
migrates its own disposable schema, then removes it in a `finally` block.

The strict manifest has exactly these fields. Replace identifiers, bytes, times and authority
with the actual operator inputs; the timestamps below describe an example, not standing authority.

```json
{
  "profile": "exulanica.personal-admission/v1",
  "actor_id": "00000000-0000-4000-8000-000000000001",
  "workspace_id": "00000000-0000-4000-8000-000000000002",
  "purpose": "Inspect my exact capture and hide people before reconstruction",
  "source": {
    "path": "a.png",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "bytes": 123,
    "capture_id": null
  },
  "authority": {
    "account_authority_basis": "State the actual account authority for these bytes",
    "authorized_at": "2026-09-08T12:00:00Z",
    "valid_until": "2026-09-08T14:00:00Z"
  },
  "operation": "admit",
  "authorization_id": null,
  "screening_id": null,
  "recorded_at": "2026-09-08T12:01:00Z",
  "review": "not-reviewed",
  "edits": []
}
```

Unknown or missing fields, duplicate keys, floats, non-finite numbers, malformed UUIDs,
noncanonical or escaping paths, symbolic-link sources, changed hashes/sizes, expired authority
and blank authority/purpose are refused. Each manifest names one exact source, not an assertion
about every image in its directory. Unlisted files are not read. Store and photo roots must be
separate and non-nested; symlinks in the store are refused.

The actor is an explicit local operator attestation, not an authenticated subject identity. The
CLI uses the local database role's authority. Account authority does not establish consent to
presence, naming, likeness, training or publication. This command never records a subject's
consent. Human additions without linked consent remain `unknown` and are masked by existing policy.

## Operator sequence

1. `admit` hashes and intakes the exact bytes and records personal authority. Save the returned
   `capture_id` into `source.capture_id` and `authorization_id` into subsequent manifests. Keep
   the authority fields unchanged. Repeating the same manifest reuses the capture and authority.
2. `detect` records `person_detection_only` with the explicit purpose and runs the permitted
   ingest pass. Save its `screening_id` for later mask/retry passes. This bounded command configures
   no vision, detector or depth model. Their unavailable stages are reported explicitly. An empty
   inventory therefore makes no claim that no people exist. The receipt permits observation and
   remains blocked for geometry. No hosted-call flag or environment variable enables a model here.
3. Inspect the exact source outside this command. Use `review: "no-person"` only after actually
   reviewing it and finding no person. A nonempty current inventory refuses this attestation.
   Otherwise use `review: "confirmed-regions"` and explicitly add or confirm every region.
4. A `review` operation calls the existing person-edit and human-screening seams. A named hidden
   person without a current mask yields a durable blocked screening, not a false no-person claim.
   Exit 0 means the requested review was recorded; inspect `eligibility_state` for permission.
5. `mask` uses the original detection permission as `screening_id` and runs the ordinary ingest
   derivative pass to build the real masked source. A blocked human screening cannot authorize
   this observation pass; retain the separate detection permission.
6. `rescreen`, with a fresh `recorded_at` and explicit review attestation, records the new human
   screening over the current regions and resolved states. Use its new ID for `geometry-check`.
7. `geometry-check` calls the real privacy policy and current-mask check. It performs no geometry
   inference. `retry` runs the permitted derivative pass with the explicit receipt, reusing
   unchanged stages. After a region edit, use the detection receipt to rebuild the changed mask,
   explicitly re-screen, and then use the new eligible screening.

An edit has exactly `action`, `region_key` and `silhouette`. Actions are `add`, `confirm` and
`delete`; keys are 64 lowercase hexadecimal characters. `silhouette` is null to reuse an existing
outline, or `{"kind":"polygon","points":[[0,0],[500000,0],[500000,500000],[0,500000]]}`.
Coordinates use the existing integer parts-per-million display convention, not raw sensor pixels.
The existing silhouette validator rejects degenerate or out-of-range outlines. Repeating an edit
with the same actor, capture, key and timestamp reuses the existing receipt; conflicting contents
at that same timestamp are refused. New decisions require a new timestamp.

The command writes workspace partitions, capture and receipt rows, pipeline ledger events and
content-addressed bytes beneath `--data-dir/blobs`. It never modifies original photos or the input
manifest. Stage failures can leave successfully committed intake or prior receipts available for
retry; command output is JSON with a nonzero status on refusal. There is no extra sidecar receipt
store. JSON output reports identifiers already persisted through the existing repository.

## Executed evidence and limits

The recorder uses labelled generated images, manual fixture regions, real PostgreSQL policy and
the real ingest/mask stages. No personal photographs, credentials, hosted model calls, actual
person detector, depth inference or GPU work are used. The generated polygon is a simulated
sensitive region; its masking is not a measured real-person detector or segmentation result.

The original [record](evaluation/2026-09-08-personal-admission-flow.json) is preserved. Its SQL
control is a known failing baseline, not a killed mutant. The follow-up record distinguishes that
baseline from an executed command-local negative control: removing only the Python currency
guard in subprocess memory makes
`tests/test_personal_admission_flow.py::test_changed_region_requires_current_mask_before_geometry`
fail with `DID NOT RAISE`. The recorder requires that selector's exact `FAILED` line.

The evidence retains exact successful and refusal commands, manifests and JSON logs for admission,
authority expiry/absence, byte mismatch, cross-workspace access, detection-only geometry refusal,
manual no-person review, a person needing a mask, stale mask refusal, rebuild, re-screening and
idempotent retry. It also executes the existing frontier preflight CLI against the persisted
receipts: its exact-source database/screening check passes; the overall preflight refuses the
intentionally absent signing key. No signing key is created or supplied.

Every evidence envelope has exactly `profile`, `record`, and `record_sha256`; the digest is SHA-256
of `canonical_json(record)`. There are no floats. Every record names its predecessor and binds its
retained artifacts by size and digest. Generate a new record with new output/artifact paths:

```sh
uv run python scripts/record_personal_admission_evidence.py \
  --output docs/evaluation/NEW-personal-admission-flow.json \
  --artifacts docs/evaluation/artifacts/NEW-personal-admission-flow \
  --predecessor docs/evaluation/2026-09-08-personal-admission-flow.json
```

Historical manifests contain expiring authority and a schema that the recorder removed. Their
exact commands are audit evidence, not perpetual permissions; rerun the recorder to obtain a fresh
isolated rehearsal. A successful command-local check is not production activation or a global
privacy-policy guarantee.

## Final verification and exact executed commands

The [final command evidence](evaluation/2026-09-08-command-personal-admission-flow.json) binds the
corrected recorder and remaining gates at `ff67b771c6993fcd8d16ae99c79950d69275a4fd`.
The full backend run at the preceding candidate head returned **2070 passed, 3 skipped, 1 failed**:
the failure was the retained-record test rejecting absolute workstation paths in command strings.
The orchestrator authorized replacement of these two unpublished candidate records by real recorder
reruns and removal of their defective unpublished history. Established main records were unchanged.
The replacement digests and tested heads are retained in `gates/candidate-replacements.json`.

After correction, all retained-record tests and 38 focused command/privacy/masking tests passed.
Ruff, all import contracts, web typecheck, boundaries, and all 867 web tests passed. An intermediate
Ruff failure in the generated mutant program was corrected in the recorder and re-executed; its log
is retained too. Production and test source did not change after the full backend run. Per the
orchestrator's explicit direction, the full backend suite was not repeated; independent full gates
on the rebased integration tree remain pending. The known slow-stage lease test did not fail.

The following commands were actually executed from the repository root. Their exact schema was
removed after the rehearsal and their authority expires; they document the run, not a live schema.
The pending-migrations refusal was executed before that isolated schema was migrated by the recorder.

### pending-migrations (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/pending-migrations.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### missing-authority (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/missing-authority.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### expired-authority (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/expired-authority.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### wrong-source-bytes (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/wrong-source-bytes.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### admit (exit 0)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/admit.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### detection-only-geometry-refusal (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/detection-only-geometry-refusal.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### cross-workspace-refusal (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/cross-workspace-refusal.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### unmasked-person-geometry-refusal (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/unmasked-person-geometry-refusal.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### stale-mask-geometry-refusal (exit 1)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/stale-mask-geometry-refusal.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### final-geometry-permission (exit 0)

```sh
uv run python -m exulanica.ingest.personal_admission_command --schema exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063 --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/final-geometry-permission.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data
```

### frontier-preflight (exit 1)

```sh
EXULANICA_DATABASE_URL='dbname=exulanica_spine_test host=localhost port=5433 hostaddr=127.0.0.1 options=-csearch_path=exulanica_personal_evidence_5f20ec58ae9948bfafc6e102fa88b063,public' uv run python -m exulanica.orchestration.cli preflight --manifest docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/frontier-manifest.json --photo-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/photos --data-dir docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/data --output docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/frontier-output --private-key docs/evaluation/artifacts/2026-09-08-command-personal-admission-flow/not-supplied.pem
```


## HEIC source lineage

HEIC/HEIF intake retains the exact uploaded bytes and evidence address. It also records an
immutable `decoded_source` PNG artifact, binding the original SHA-256, output SHA-256, actual
decoder inventory, conversion options, and display pixel grid. The pinned decoder and its
LGPL components are documented in [the license matrix](license-matrix.md#11-heic-decoder-inspection-and-pin-2026-09-12).
Only single-frame images within the common pixel limit are accepted. Conversion normalizes
to RGB8, removes metadata, discards alpha, and does not perform ICC color management.

The source inventory and viewer route select that PNG with `image/png` and explicit decoded
provenance. The evidence route continues to return the camera original when current permissions
allow it. A conversion receipt grants no detection, likeness, or geometry permission. Human
screening and current consent still govern geometry; a capture needing privacy masking uses a
separate JPEG mask whose receipt binds the normalized predecessor and its decoder receipt.
Depth and segmentation load those exact persisted bytes, as pose and training do.

Decoder inventory or conversion-option changes invalidate normalized inputs and dependent masks,
even when a new decoder produces the same PNG bytes. Queued work must be rebuilt and admitted
again when these bindings move. Depth and segmentation version 2 also invalidate earlier cache
entries that named a mask JPEG but consumed pixels before its JPEG encoding. No existing artifact
is relabelled. Splat manifests carry decoded lineage separately from privacy masks and preserve
the original identity of held-out photographs. Offline readers verify the receipt and selected
image grid before accepting training inputs or downloaded views.

Migration 0045 is exercised only in owned scratch schemas in this repair. Advancing the running
API database is an integration operation; the retained first-place database remains untouched.
Synthetic HEIC tests use local model doubles. They do not establish real model quality or hosted
vision acceptance, and no paid model call is authorized by this document.
