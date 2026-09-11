# Personal admission and re-screening

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

The API path and worker change do not yet deliver HEIC conversion or a fresh workspace's source
inspector. Those require extensions outside the current writable set, including a distinct decoded
source permission in SQL. No migration has been applied or reserved for this work. No hosted calls
have been authorized in this task.

The final focused run passed 89 PostgreSQL tests on scratch schemas in `exulanica_inspect_test`.
The fresh public-copy rehearsal then refused all three predecessor JPEGs at `/intake`, before the
new admission route: `artifact_pkey` collides when another workspace already holds the same bytes.
`artifact_id_for` derives a global ID from a key without workspace identity, while artifact lookup
is workspace-scoped. The first-place workspace and bytes were preserved. This is an additional
release blocker, not a successful acceptance run. The digest-bound attempt is recorded in
[evaluation/2026-09-11-personal-path.json](evaluation/2026-09-11-personal-path.json).
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
baseline from an executed command-local negative control: removing only the new Python currency
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
