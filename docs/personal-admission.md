# Personal admission and model rights

A person can build part of a world from their own photographs. This contract owns how those
photographs are admitted under account authority, which models may read them (the personal model
right), and which trainer may read them (the scene training right). Person regions, masking and the
screening that permits geometry are [person-presentation-consent.md](person-presentation-consent.md);
serving photographs and geometry under current permission is
[asset-read-currency.md](asset-read-currency.md).

## Contents

- [Personal model rights](#personal-model-rights)
- [Scene training right](#scene-training-right)
- [Not covered](#not-covered)
- [Captures screened before model rights](#captures-screened-before-model-rights)
- [Ordinary API batch path](#ordinary-api-batch-path)
- [Isolated rehearsal command](#isolated-rehearsal-command)
- [Evidence](#evidence)

## Personal model rights

A screening receipt answers whether a photograph may be looked at (`person_detection_only`) or
become geometry (an eligible human review); it names no model and no destination. The personal
model right (migration 0073) does: no byte of a personal photograph reaches a model unless a right
is current for that model and that destination. A right is not a screening and a screening is not
a right: every model read requires both.

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
  nothing else about them changes; a different model, destination or term is another right.

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
as it does a deleted photograph's. An expiry deletes nothing. A search right granted again lets
the photograph be indexed again, and the search ranks the entry made under it: an entry is left out
only while the stop names it and its purge has not destroyed it, and the stop's record stays. An
entry is made again only after the purge, since indexing skips a photograph whose entry is still
stored. `tests/test_search_entries_on_stop.py` holds this through the runtime and purge roles, and
`tests/test_search_entry_granted_again.py` the right granted again. A restore writes the stop again
from its checkpoint before it replays the stop's tombstone, so a backup taken before the stop comes
back with the right stopped and its entries deleted
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

## Scene training right

Training a scene reads photographs on a trainer host and leaves an artifact that outlives any grant,
so it has its own right (migration 0080, table `scene_training_right`,
`exulanica/ingest/training_rights.py`), separate from the personal model right and from the
dataset-export training consent of migration 0039. A right names one photograph and its exact
bytes, the operation `scene_training`, the personal authority it was granted under with that
authority's account holder as grantor, a purpose, a grant time, a required expiry and a
destination: `local-process`, an https origin, or a rented machine spelled
`rented-host:<provider>/<instance>`. Loopback spellings are refused, because a rented machine
reached through a tunnel presents itself as localhost and a right recording that spelling would say
the bytes never left the machine. A right names no model: what outlives the grant is the artifact,
which `scene_training_artifact` binds to the rights that permitted it when it is published.

A training job states its destination in its build inputs (`scene_training_destination`, set by
`enqueue_exact_scene_reconstruction(..., training_destination=...)`). For every personal member of
the job, the database refuses the member insert without a current right for that destination, so
the run cannot be queued, and refuses the artifact insert that would publish anything if the right
lapsed during the run. Withdrawing a right cancels any queued, running or failed training job that
contains the photograph and writes a `scene_training` tombstone (migration 0082) whose cascade
queues the artifacts trained from that photograph for destruction while the photograph itself
survives ([domain-and-evidence-model.md](domain-and-evidence-model.md) section 6.2). A restore
replays the withdrawal ([ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md)). Synthetic and
benchmark captures need no training right.

No API route or application surface grants or withdraws a scene training right:
`grant_training_right` and `withdraw_training_right` in `exulanica.ingest.training_rights` are its
only writers, so an account holder's photograph reaches a trainer only through an operator who calls
them. The read-side check `require_artifact_training_right` refuses a withdrawn artifact under the
final read check, but no route calls it; a published trained scene stays readable until the purge
worker destroys its artifacts.

## Not covered

- Scene pose (COLMAP, classic feature matching with no learned weights) runs under scene admission
  and screening only. Gaussian training runs a learned perceptual metric (LPIPS) inside the trainer
  container; the scene training right names the photographs and the destination host, not that
  metric.
- Place alignment's joint reconstruction stages original photographs for pose under a deletion
  check only. No API or worker path calls it; a verification script and tests do.
- Benchmark captures keep their recorded licence as their model permission; no per-model right
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

## Captures screened before model rights

A capture screened before migration 0073 has no right, and the migration wrote none. Its receipts
keep their meaning, but no model receives its bytes until the account holder grants a right, which
admitting the same capture again with `model_rights` does. The ordinary batch path's detection pass
sends nothing to the hosted vision model unless the batch names the vision role. Caption vectors
stored before model rights stay, and no caption text about a personal capture is sent until its
account holder grants the embedding role.

## Ordinary API batch path

`POST /intake` returns exact capture IDs and original digests. Send those captures to
`POST /personal-admission` as one `members` inventory. The route uses the ordinary API connection,
including its public schema, authenticated workspace and actor. It does not provision or migrate
schemas; the rehearsal command below keeps its isolated-schema restriction.

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
member for every model the role can reach, under that member's personal authority, granted by the
session actor at `recorded_at`, and the authority's scope records each role's term and notice. Each
role appears once, and each term must end in the future and no later than the authority. `depth`
names the MoGe checkpoint the manifest pins as `local_roles.depth`, the one the derivative worker
loads. The whole list is validated before any receipt is written. Each response receipt carries
`model_right_ids` and `model_rights` (identity, destination, term and receipt digest, never the
purpose). A batch that names no role records no right, and the worker then sends its photographs to
no model. A replay with the same `request_id` reports each granted right as `current` or `ended`,
and `GET /personal-admission` lists the rights the actor granted over each source, each with
`notice_current`, true only when the server states words for the right's role and the right was
granted against exactly those words. Neither answer is a permission. A search right granted against
the role's earlier words, which said the search entries already made would stay, is listed with
`notice_current` false, and the drawer shows it as allowed without the wording shown; stopping it
deletes those entries as well, which removes more than those words said and nothing they promised
to keep for the person. `POST /personal-admission/model-rights/{right_id}/withdraw` ends one right.

For `review`, supply `reviewed_by_name`, `attestation`, and either `no-person` or `confirmed-regions`
on every member. The attestation must exactly read:

> I personally inspected every exact photograph in this inventory and reviewed all people and sensitive person regions, including any missed by the detector.

The caller supplies that statement; the server never supplies it for them. A no-person review is
refused when regions remain. A confirmed-regions review requires every proposal to have been
confirmed or explicitly removed. Optional `edits` use the command's format. The named review and
statement are retained in the authorization scope, which is digest-bound into the same
human-screening receipt that the command writes. The response's `eligibility_state` is
authoritative: a recorded review can stay blocked until current masks exist. Account authority and
review do not establish a subject's likeness consent.

`POST /identity/subjects/link` accepts `regions: [{capture_id, region_key}, ...]` and an optional
`subject_id`. Omitting the subject creates one subject for the whole selected set, and supplying the
returned ID links further photographs to the same person. Each region gets an immutable human
confirmation, and the transaction refuses unknown subjects or regions without applying a partial
set. `POST /identity/subjects/unlink` requires the current `subject_id` and selected regions and
appends confirmations with no linked subject; existing consents and previous edits remain
historical. `POST /person-subjects/{subject_id}/consents` records the account holder's consent
statement. Ordinary outline confirmations preserve an existing subject when `subject_id` is
omitted, and an explicit null unlinks it. An edit request names each region at most once;
duplicate keys are refused before any edit is written. Changed links invalidate screenings through
the screening currency rule ([person-presentation-consent.md](person-presentation-consent.md#screening-currency)).

## Isolated rehearsal command

`exulanica.ingest.personal_admission_command` is an operator rehearsal over exact capture bytes. It
composes intake, personal account authority, privacy screenings, person review receipts and mask
stages, writes no benchmark provenance, creates no receipt table and applies no migration. It is
bound to the test database `postgresql://localhost:5433/exulanica_spine_test` and an isolated
`exulanica_personal_*` schema that the operator creates and migrates beforehand; public is not an
allowed target. A missing schema or pending migration produces a JSON refusal before provisioning,
intake or store writes.

```sh
uv run python -m exulanica.ingest.personal_admission_command \
  --schema exulanica_personal_operator_run \
  --manifest /outside-git/admission.json \
  --photo-dir /outside-git/authorized-photos \
  --data-dir /outside-git/personal-store
```

The strict manifest has exactly these fields. Replace identifiers, bytes, times and authority with
the actual operator inputs; the timestamps below describe an example, not standing authority.

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
noncanonical or escaping paths, symbolic-link sources, changed hashes or sizes, expired authority
and blank authority or purpose are refused. Each manifest names one exact source, and unlisted files
are not read. Store and photo roots must be separate and non-nested, and symlinks in the store are
refused. The actor is an explicit local operator attestation, not an authenticated subject
identity. Account authority does not establish consent to presence, naming, likeness, training or
publication, and the command never records a subject's consent.

The operations run in this order: `admit` hashes and intakes the exact bytes and records personal
authority; `detect` records `person_detection_only` and runs the permitted ingest pass (no vision,
detector or depth model is configured, so an empty inventory claims nothing); a `review` records a
human screening (`no-person` only after actually finding nobody, otherwise `confirmed-regions` with
every region added or confirmed); `mask` uses the detection permission to build the masked source;
`rescreen` records a human screening over the current regions and states; `geometry-check` calls the
privacy policy and current-mask check without running geometry; and `retry` runs the permitted
derivative pass with an explicit receipt. After a region edit, rebuild the mask with the detection
receipt, re-screen explicitly, and use the new eligible screening. An edit has exactly `action`
(`add`, `confirm` or `delete`), `region_key` (64 lowercase hexadecimal characters) and `silhouette`
(null to reuse an outline, or a polygon in integer parts per million of the display space). The
command writes workspace partitions, capture and receipt rows, pipeline ledger events and
content-addressed bytes beneath `--data-dir/blobs`, never modifies original photos or the manifest,
and reports JSON with a nonzero status on refusal.

## Evidence

- [Personal admission flow](evaluation/2026-09-08-personal-admission-flow.json) and
  [command evidence](evaluation/2026-09-08-command-personal-admission-flow.json): the rehearsal over
  labelled generated images, manual fixture regions, real PostgreSQL policy and the real ingest and
  mask stages, with no personal photographs, hosted model calls or GPU work.
- `tests/test_search_entries_on_stop.py` and `tests/test_search_entry_granted_again.py` for search
  rights; `tests/test_depth_awaits_admission.py` for a photograph that waits for admission.
