# Asset-read currency: contract and scope checkpoint

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
