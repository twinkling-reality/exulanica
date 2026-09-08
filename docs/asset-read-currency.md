# Asset-read currency

Final acceptance at source head `03501cea376cf530c185e3b12a5fb0d8d8d7acdf` passed 2118 backend
tests (3 skipped), Ruff, all 4 import contracts, web typecheck and boundaries, and 876 web tests.
The locked pose/reconstruction environment was installed. Six negative controls failed at their
own exact selectors. The [executed record](evaluation/2026-09-08-executed-asset-read-currency.json)
binds the route-to-byte evidence; the [verification record](evaluation/2026-09-08-verification-asset-read-currency.json)
records digest checks and the second unsuccessful recorder attempt without changing accepted records.
Runtime source remains identical to that tested head. The recorder was subsequently corrected
at `b845bad6cfc8962b1550fb03c6f73d7aabb3f88f` under the `520a192` evidence-repair approval.
Independent integration caught personal checkout prefixes in retained command arguments because
the original full gate ran before envelope generation. The two unpublished candidate envelopes
were regenerated through the recorder with normalized command provenance, replaced hashes and
the independent failure retained. Accepted historical records were preserved. Post-generation
retained-record checks now run after writing the candidate, including after dependent bindings.
Migration 0041 was exercised only in disposable test schemas; retained database activation, merge
and push remain unperformed.

Migration 0041 implements the scope approved at `6270115`, with the single existing viewer-URL
assertion update approved at `6d12621`. Original/crop/by-URI image delivery now refuses current
mask requirements, withdrawal and missing capture identity. Permitted originals retain exact
bytes; no route substitutes a mask under an original digest. Image track identity is checked even
when MIME metadata is missing. Ordinary non-image citations do not acquire geometry prerequisites.
All new viewer image references use `/masked`, including no-person captures.

## Current read contract and lineage

`/masked` selects an exact current persisted derivative using 0040's input-digest matcher through
0041's explicit-time read policy. Missing, obsolete or purged required masks refuse. World source
metadata checks the same selection and verifies the selected stored bytes; unavailable sources
retain live capture IDs for manual review but no asset reference. Deleted sources lose review
identity. The current schema's unique live-capture index rejects duplicate live mappings. The read
predicate nevertheless refuses disagreeing mappings rather than choosing a permissive one by order.
A missing capture mapping is not an empty, reviewed person inventory.

Point-map metadata omits policy-refused artifacts. Direct-ID delivery verifies the artifact's own
source, read-source digest, screening and exact buffered row; a current mask for the capture is
insufficient. Missing legacy screening lineage refuses. A null read-source means the original,
as defined in 0037; it is accepted only when that artifact's persisted screening and actual source
support current permission. A rebuilt mask does not rebind historical geometry.

Scene geometry checks the persisted pose manifest and exact per-capture frame digests against the
job's recorded point maps and their read-source digests. The current pose, gate, placement, job
and active assertion bindings must remain the buffered bindings. Trained delivery additionally
checks the training manifest's pose digest/source list and the gate-named publication receipt.
Missing, purged or withdrawn lineage refuses. `/graph` retains review metadata for refused scenes
but removes placements, recovered cameras and trained assets. World Read scene/place and sparse
observation responses with embedded geometry refuse when those recorded inputs are unavailable.
No new wire state or schema was added.

The generated scene tests execute real publication/controller/store paths with scripted COLMAP
and training outputs. They establish delivery/lineage behavior, not measured reconstruction quality.
The real mask stage rebuilds a changed source in that test; its old trained asset remains refused.
Masked splat production still refuses at the existing producer's missing held-out-remap seam and
is not implemented or represented as a successful masked training run here.

## Authorization instant and transaction-wide ordering

Snapshot metadata remains REPEATABLE READ READ ONLY. 0041's explicit-time predicates do not invoke
the admission lock or replace snapshot consistency with fresh per-query reads. A metadata result
is true of its snapshot and is not a capability for later bytes.

Each byte-serving operation first buffers and hash-verifies local bytes. It then opens a separate
READ COMMITTED READ ONLY transaction, acquires the asset barrier in its own statement, and obtains
one database timestamp in a subsequent fresh statement. That is the successful authorization
instant. All final input/permission comparisons use it. Graph and World Read also reauthorize their
buffered embedded geometry after closing the metadata snapshot. Successful graph/World Read responses
and evidence/geometry bytes carry no-store cache policy. Each evidence range request reauthorizes;
point-map and trained routes keep their existing whole-body/Accept-Ranges-none behavior.

The final check takes only the global asset barrier, never a training, privacy or object-purge lock.
It performs no store read, streaming or network operation while holding that barrier. Writers that
committed before it acquired the barrier are visible. A writer or expiry ordered afterward affects
later requests and cannot retract the already-authorized response. Network completion is not the
linearization point. Buffers are local to the request, not transferable permission tokens.

Dependency mutations take the shared side of the global barrier with **try-lock**, retaining it
through commit. If a reader already owns the exclusive barrier, mutation raises retryable 40001
rather than waiting while holding another lock. This prevents a cycle even when a caller acquired
training, privacy, row or purge locks before its first relevant mutation. The reader can wait for
an existing writer but holds none of those other locks. A writer already owning its shared barrier
can finish cascades while a reader waits. The deliberately global barrier covers old/new workspace
moves and global stage mutations without scanning workspaces through RLS. Its cost is brief
cross-workspace contention, potentially a retry for an unrelated mutation; it is not a per-capture
throughput claim. Applications must retry the whole failed transaction, not its final statement.

The audit also reproduced a pre-existing training/source inversion through the actual
`export_training_dataset` and `record_consent` callers: export held training-source and awaited
privacy, while consent held privacy and awaited training-source, producing 40P01. 0041 replaces
only `privacy_currency_lock` to acquire training-source shared **before** privacy. The same helper
covers an earlier admission/read within a writer's transaction, not merely the INSERT trigger.
The source-before-privacy order matches export's exclusive source lock. Training's package lock
remains separate and unchanged; its consent writer does not wait for privacy. Object purge locks
are never acquired by delivery, and a purger's subsequent metadata mutation try-locks the barrier.
The executed interleavings cover the actual export/consent callers, expiry during a wait, a committed
region edit before the final check, tombstone cascade completion and an already-held purge lock.

## Dependency writer inventory

All INSERT, UPDATE and DELETE events on these existing tables have the same barrier trigger:

| Dependency | Tables and relevant writer paths |
| --- | --- |
| Source identity and physical availability | `capture`, `blob`, `evidence_span`, `media_track`: intake, direct SQL, deletion, purge metadata, old/new workspace moves where the existing role permits them |
| Current presentation state | `person_region`, `person_presentation_consent`, `person_subject`: review/consent commands and direct SQL; 0040's append-only and sequence protections remain |
| Withdrawal reachability | `tombstone`, `occurrence`, `entity_link`, `entity`, `person_derivative_dependency`: identity/occurrence writers, person dependency triggers, tombstone cascades and future dependencies |
| Persisted geometry and authority | `artifact`, `assertion`, `capture_reconstruction_authorization`, `reconstruction_privacy_screening`: producers/publication, admission, invalidation, direct SQL and purge |
| Scene/job identity | `reconstruction_scene`, `reconstruction_scene_member`, `reconstruction_scene_job`, `reconstruction_scene_job_member`: scene admission, leased publication and cascades |
| Place dependency identity | `place`, `place_version`, `place_alignment`: place admission/alignment and existing immutable rows |
| Global producer definition | `stage_registry`, `stage_definition`: registry writers affect current mask matching; global rows use the same barrier without a workspace lookup |

These triggers do not grant writes or relax any existing append-only, RLS or role rule. Direct
partition writes inherit the row triggers. TRUNCATE/DDL is not a runtime privilege or part of the
concurrent delivery contract; administrative migration requires separate deployment control.
Training-use package consent is a separate export permission, not silently repurposed as viewer
permission. Runtime evidence tests configure actual `exulanica_ro` connections and assert SELECT-only,
non-owner/non-superuser/non-BYPASSRLS access; they do not use the service's writer fallback.

## Retained evidence and activation limits

The recorder's acceptance run retains labelled generated original media, request/response
status and SHA-256/size observations, response bodies, persisted artifact lineage and stored
objects. Its killed controls require their own exact pytest selector's FAILED line. Mask lineage,
point lineage, original authorization, final buffering check, delivery locking and training lock
order have separate executed controls; the two original-route controls remove the same shared
original guard and establish only their named local claims.

Run `scripts/record_asset_read_currency_evidence.py --output docs/evaluation/NEW-asset-read-currency.json
--artifacts docs/evaluation/artifacts/NEW-asset-read-currency --full-gates` for a fresh envelope.
The envelope has exactly `profile`, `record`, `record_sha256`, no floats, digest/size file bindings,
and `predecessor_record` pointing to the screening-currency integration record. It also binds the
unchanged accepted checkpoint and intermediate logs. It is written only after the required
commands and exact-selector controls pass. The first full backend run (2112 passed, 3 skipped,
one old-URL assertion failure), fixture mistakes, scene-envelope comparison correction and actual
training deadlock baseline remain retained; none is described as final acceptance.

The task owns the orchestrator-assigned isolated/full-suite slot until handoff. The only test URL
is `postgresql://localhost:5433/exulanica_spine_test`; test schemas are disposable. Full gates include
locked pose/reconstruction extras, all backend tests, Ruff, four import contracts and web typecheck,
boundaries and tests. Source binding in the executed record identifies the exact tested code head;
subsequent evidence commits are not a claim to have tested different feature code.

No retained-public migration, activation, personal-media run, hosted model, GPU spend, merge or
push occurred. Retained public still needs explicit authorization and verification before deploying
code requiring 0039/0040/0041. This is not recipient-checkable World Read release evidence or an
external cache/offline revocation system. Already delivered bytes cannot be revoked by this guard.
Unresolved surfaces outside this implementation are generated-model asset delivery/conditioning
metadata, offline/exported packages and their recipients, direct administrative object-store access,
and external copies/caches. Non-image evidence retains its existing semantics; the new person-image
policy is not a global media disclosure guarantee. Masked trained-geometry production remains an
explicit producer activation dependency. Manual review has no new unmasked bypass.

## Historical pre-implementation checkpoint

The following investigation was committed before implementation. Its pending approvals and test
status describe that earlier checkpoint, superseded only by the approved implementation above.


Status: investigation only, at base `59edce3` (main contains `53039d4` and the brief).
No delivery implementation or activation claim. The branch is `codex/asset-read-currency`.
This document precedes implementation as required by the brief. No applicable on-disk
AGENTS.md was found in the checkout or its ancestors; the supplied instruction to ground
reasoning applies. Migrations 0037–0040 and the callees below were inspected.

## Read contract

| Surface | Existing call graph | Required contract |
| --- | --- | --- |
| Owning-workspace original citation | `evidence.original` → `_address` → `tombstone_blocks_span` / `address_from_span_row` → `resolve_original_bytes` → store | Resolve exactly the original digest. Never return a mask under that digest. Current person-presentation authorization is a separate policy decision. |
| Original crop | `evidence.region` → `_address` → `resolve_region_image` | Explicit original-derived crop; changing its authorization needs the scope checkpoint. |
| Original permalink | `evidence.by_uri` → workspace/span-digest lookup and `tombstone_blocks_span` → `resolve_original_bytes` | Same exact-byte rule; span ownership is not a viewer-presentation permission. |
| Viewer image | `evidence.masked` → `_address` → capture/mask query → store → `_ranged` | Resolve all relevant capture identity and current inputs at a stated instant. Require an exact matching persisted mask when needed. Refuse absent, stale, purged, corrupt or missing required bytes. No original fallback in that case. |
| World source metadata | `WorldRepository.source_media` → `_source_rows` → `_source_from_row` | Use the same availability decision as viewer delivery. Preserve live capture identity for review while required mask bytes are unavailable; publish no asset reference. |
| Point maps | `/geometry` → `point_map_descriptors`; `/geometry/{id}` → `read_point_map` → store | Check the artifact's own screening, source and `read_source_sha256`, not whichever new mask exists. Missing lineage refuses. Metadata and bytes must agree at their respective authorization instants. |
| Trained geometry | `/graph` / World Read → `reconstruction_scene_rows` → `trained_geometry_row`; `/scene-geometry/{id}` → `read_scene_geometry` → gate/pose/publication receipt → store | Validate the exact recorded member/frame inputs and training manifest, plus current permission for every input. A new mask cannot validate a historical original frame. |

Metadata is not a capability: a later byte request must authorize again, including ranges.
Changed outline, permission expiry without writes and withdrawal must be re-evaluated.
Unchanged effective inputs can reuse matching artifacts; timestamps are not lineage.
No-person captures may use original bytes through the viewer path when permitted at that
request's instant. Deleted captures cannot be treated as empty inventories.

## Findings requiring a checkpoint

1. **Viewer references can bypass the masked route.** `_source_from_row` currently emits
   `/evidence/{span_id}` when no mask is needed. A previously obtained reference still reaches
   the original route after permission changes. The writable source-selection seam can emit
   `/masked` for all viewer images going forward, but that does not revoke old original URLs
   or authorize changing original/crop/by-URI semantics. Decide whether originals remain an
   owning-workspace review/citation privilege. If viewer access to them must be narrowed,
   approve only those three route authorization guards and the necessary purpose distinction;
   keep exact-byte semantics. Current bearer sessions alone do not establish that distinction.

2. **0040 cannot simply be called from graph metadata.** `Database.session` is autocommit;
   `readonly_connection` uses `Services.readonly_database`, which falls back to the writer
   database if no read-only URL is configured. `/graph` and the scene/place World Read routes
   explicitly open REPEATABLE READ READ ONLY transactions. `privacy_currency_lock` raises
   SQLSTATE 40001 unless isolation is READ COMMITTED. This propagates through
   `current_privacy_inputs`, `current_privacy_mask` and `privacy_screening_allows_capture`.
   The isolated test database has no installed currency function at inspection time; this
   incompatibility is established by source, not a claimed executed route failure.

3. **Admission locking is insufficient for delivery ordering.** 0040 locks region, presentation
   consent and screening INSERTs. Tombstone and capture mutations do not take that lock.
   0039's `tg_training_source_mutation_lock` covers tombstone, region, presentation consent,
   subject, capture, artifact, scene/member, job/member and screening mutations with the shared
   `training-source:` workspace lock. This is a useful existing mechanism, not proof of full
   delivery coverage: `person_withdrawal_blocks_capture` also reads occurrence/entity links;
   `person_withdrawal_blocks_artifact` reads `person_derivative_dependency`; trained delivery
   reads assertion status. Those tables are outside that trigger list. Stage registry changes
   affect mask matching too. Capture authorization expiry is time-dependent.
   A reader acquiring the training-source lock before the privacy lock can also invert writer
   ordering: the `aa_privacy_currency_lock` INSERT trigger runs before
   `tg_training_source_mutation_lock`. Do not compose these locks without interleaving tests.

4. **Masked splat production is explicitly unavailable.** `scene_selection` returns `None`
   when masked declarations and a splat request coexist because the held-out digest remap is
   missing. `scene_reconstruction._manifest` binds pose frames to actually resolved bytes;
   `SceneSplatRequest.manifest` copies those frame hashes into the training manifest.
   Readers can inspect this persisted lineage, but cannot manufacture a masked historical
   training run or relabel an old receipt. Keep legacy/missing-lineage refusal. Supporting
   successful masked training needs a separately scoped producer change, not this read patch.

5. **Point-map unavailable state has a constrained wire type.** The permitted graph module and
   the read-only API response model currently expose only `available` and `bytes_missing`.
   A policy refusal must not claim that existing bytes are physically missing. Omission can
   withhold a descriptor without changing that schema. If an explicit privacy-unavailable
   descriptor is required, the smallest additional file is `api/routes/geometry.py` for its
   state literal/response mapping; frontend and World Read contracts remain a separate checkpoint.

## Proposed ordering, not yet implemented or demonstrated

Authorize at one database clock instant **after** acquiring the chosen policy lock and a
fresh database snapshot. All predicates for one asset must use that same instant and actual
persisted input lineage. A writer ordered before this check must be visible and can refuse it.
A writer ordered after it may invalidate subsequent requests; the current response can finish.
Permission expiry after this instant is likewise not retroactive.

Read and digest-verify bytes into a local immutable buffer before a final permission check,
or within a bounded local read section, then release database locks before network delivery.
Never hold a write transaction across arbitrary streaming or promise to retract delivered bytes.
Missing/purged bytes refuse independently of permission. `purge_lock_object` serializes object
purge by object reference; it does not serialize every permission writer. Network completion is
not the authorization instant. Each range is a new request subject to the whole check.

For a serialized contract, the smallest policy extension to review is **one newly assigned
migration** exposing a read-time predicate with one explicit evaluation instant and a documented
lock order, plus trigger coverage for the exact mutable policy dependencies above. Retain 0040
unchanged. Final trigger coverage needs audit of direct SQL, tombstone cascades, identity writes,
purge and publication writers, not just the HTTP consent command. Do not silently allocate 0041.
The migration must work as a non-owner, non-BYPASSRLS SELECT-only runtime role without granting
table writes. Snapshot metadata may use a separately specified historical snapshot contract;
it must not claim a fresh serialized check if a lock wait retained an old snapshot.

If instead reusing the current READ COMMITTED admission predicate, approve the minimum caller
transaction extension in `api/routes/graph.py` and affected `api/routes/world_read.py` only after
reviewing their existing snapshot contracts. Changing isolation globally is not approved.
No implementation outside the original writable set has been made.

## Callee and writer inventory inspected

- 0037: region inventory, consent precedence, original-vs-read-source column, observation
  purpose and point-map trigger; superseded definitions are resolved through 0040.
- 0038: place membership and `tombstone_blocks_place` → `tombstone_blocks_scene`.
- 0039: training-consent package lock and source mutation trigger; separate permission purpose.
- 0040: `privacy_inputs_at` → `privacy_consent_at`, `person_subject_is_withdrawn`,
  `person_region_current`; mask canonicalization → current intake/mask registry and artifact
  inputs; screening → authorization, capture/tombstone and exact receipt binding.
- 0030: person withdrawal guards → confirmed occurrence/entity links and persisted derivative
  dependencies; tombstone cascade reaches artifacts/jobs/assertions. 0035 adds forward
  invalidation when a dependency arrives after withdrawal. 0036 adds restore-checkpoint refusal.
- 0013: object purge lock; queue/worker handle destruction separately from tombstone visibility.
- `ingest/masked_inputs.py`: exact declarations and resolver, not an allowed graph import.
- `db/session.py`, `db/roles.py`, `api/dependencies.py`, `api/services.py`: actual role and
  transaction composition. Existing geometry/world fixtures use a shared writer role, so they
  alone cannot prove SELECT-only delivery. New route tests must configure the separate role.

## Evidence and work remaining

The companion recorder produces a **checkpoint** envelope, not acceptance evidence: exactly
`profile`, `record`, `record_sha256`, integral canonical JSON, source/log bindings and
`predecessor_record` pointing to the screening-currency integration record. Existing records
are preserved. Its read-only database probe inspects runtime role attributes and demonstrates
advisory-lock acquisition in a READ ONLY transaction as `exulanica_ro`; it does not prove
currency policy or writer serialization. No personal-media tables are queried.

No serialized suite slot was assigned in the supplied context and no repository slot protocol
was found. Reserve the slot with the orchestrator before running the database suite or mutations;
the slot is **not claimed as reserved**. No full gates or labelled route tests have run for this
checkpoint. Still required after scope resolution: real authenticated generated-media routes,
real mask production, persisted geometry lineage, exact-selector killed controls with their
own FAILED lines, controlled reader/writer schedules, and all backend/web gates with locked pose
and reconstruction extras and the specified test URL.

The pending matrix is: changed outline; expiry without writes; withdrawal; absent/stale mask;
rebuilt mask that does not revive old geometry; unchanged inputs; no-person; deleted capture;
missing legacy lineage; byte ranges; cross-workspace refusal; metadata/bytes agreement; review
reachability. Geometry quality inference and successful masked splat training are not established
by placeholder point-map bytes or constructed publication fixtures.

Unresolved read surfaces explicitly remain: original citation, original crop, by-URI original,
masked image, World source metadata, point-map metadata/bytes, trained scene metadata/bytes,
and World Read scene/place bundles. There is no global disclosure claim. No retained-public
migration, real personal media, hosted model, credentials, GPU spend, merge or push occurred.
