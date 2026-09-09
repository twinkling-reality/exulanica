# Authored world versions and created objects

Status: **DECISION** and **IMPLEMENTED** for alternate world versions, authored object add/move/
remove/undo, the reviewed asset registry, and the bounded object-behaviour registry. The renderer
integration, the conversational authoring service, and the package extension do not exist.

This is the fourth world plane under [ADR-0007](adr/0007-world-composition-and-customization.md).
The three that exist are appearance ([world-style-backend.md](world-style-backend.md), migrations
0017 and 0023), structural authority ([spatial-world-authority.md](spatial-world-authority.md),
migration 0020) and interaction policy (migration 0021). All three share one shape: immutable
versions, one mutable current pointer, a preview lifecycle and compare-and-swap. This plane shares
the discipline and not the lifecycle, for the reasons in section 1. It implements the World state
contract in [product-direction.md](product-direction.md) and steps 2, 3 and 4 of the first
milestone. The implementation is migration `0042_authored_world_objects.sql`,
`exulanica/world/objects.py`, `exulanica/world/object_repository.py`,
`exulanica/world/assets.py`, and the `/world/versions` and `/world/assets` routes.

## 1. The decision: a new plane, bound to the snapshot the way appearance is

The question this document had to answer first was whether an alternate world version and an
authored object are a new element kind plus a version lineage on the existing structural snapshot
plane, or a plane of their own. They are a plane of their own, referencing the structural snapshot
as its source. Five properties of the existing plane decide it, and each is a property of the code
rather than a preference.

**The structural element schema is closed, deliberately.** `_topology_elements` in
`exulanica/world/structure.py` calls `_exact_keys` with exactly `element_id`, `owner`, `module`,
`lineage`, `collision`, `evidence`, `attachment` and `streaming_key`. An authored object has no
reviewed module, no `recipe_key`/`slot_key` lineage, and no evidence binding. Widening that key set
would widen the schema whose closedness is what lets an independent verifier re-derive every
historical snapshot digest.

**Element identity is composer-derived and permanent.** `world_structure_element_identity` keys
`(workspace_id, world_id, element_id)` with the snapshot that first introduced it, and
`_assert_owner` refuses to reuse an id for another owner. An object added and then undone would
burn a permanent identity row, and undo is not a composition.

**Snapshot history is append-only and revision is linear.** `tg_world_structure_append_only`
rejects UPDATE and DELETE on eight tables, and `world_structure_snapshot` is
`unique (workspace_id, world_id, revision)` behind a single `world_structure_state` pointer. One
add, one move and one remove would be three full recompositions with four recomputed section
digests each. Two alternate versions of one place could not coexist at all, which is what
product-direction means by "existing component snapshots do not establish complete world
branching".

**There is deliberately no public topology mutation route.** ADR-0007 and world-style-backend.md
both state it, and `WorldStyleRepository.register_topology` is named as the internal composer
handoff. Routing a person's edits into the composer plane would revoke that guarantee rather than
extend it.

**The structural plane has no undo.** Appearance has rollback-by-append; structure has preview,
apply and discard. An authored edit that a person can take back is neither.

So the authored plane stores a delta against one immutable source snapshot. The source is
preserved exactly, which is the first sentence of the World state contract.

### What is reused rather than rebuilt

Reuse is not a slogan here; these are the things migration 0042 does not contain because
something already does them.

| Concern | Reused mechanism |
| --- | --- |
| Source identity | Composite foreign key to `world_structure_snapshot(workspace_id, world_id, snapshot_id)`, so a version cannot name another workspace's or another world's snapshot |
| Deletion | No new invalidation path. A version is invalid exactly when its source snapshot carries a `world_structure_invalidation` row, which the existing `tg_world_structure_invalidate_on_tombstone` trigger writes when a tombstone covers a snapshot dependency |
| Coordinates | The same fixed-point integers as `placement`: `x_mm`, `y_mm`, `z_mm`, `yaw_microradians`, `scale_milli`. No IEEE-754 value reaches a digest |
| Digests | `exulanica.canonical.sha256_of_canonical`, the strict JCS subset already used for every snapshot section |
| Asset bytes | `ContentAddressedStore`. A reviewed asset is `BlobId` bytes, addressed by SHA-256, with no delete on the interface |
| Asset availability | The three-state honesty of `GET /world/source-media`: an asset is `available` or `unavailable_asset`, and an unavailable asset carries no substitute geometry |
| Workspace isolation | FORCE row-level security with the same `ws_isolation` policy on `workspace_id = current_workspace()` |
| Immutability | The same append-only trigger shape, with the current-state row as the one intentionally mutable exception |
| Concurrency | Compare-and-swap against a stored base token under a per-workspace advisory lock, as both existing world planes do |
| Registry shape | The `interaction_capability_registry` pattern: reviewed rows seeded by the migration, readable by the runtime roles and not writable by them |

Six tables are new. Each stores something no existing table can hold: an alternate version and its
lineage, an authored object, an override of a source element, an append-only edit log, a reviewed
asset catalog, and a bounded object-behaviour catalog.

### Why the interaction registry is not the behaviour registry

`interaction_capability_registry` is a per-world viewer policy. Its `category` check admits only
`comfort`, `navigation`, `disclosure` and `initiative`, and `world_interaction_policy_version`
stores one value per capability for the whole world. An object behaviour is per object, and two
lanterns in one version may hold different bounded parameters. The new registry copies its shape,
its bounds discipline and its read-only grants, and does not copy its rows or its table.

## 2. An alternate version

An alternate version has a stable id, names the source it was created from, and stores the delta.
It is one row in `world_alternate_version`:

```text
version_id            uuid, stable for the life of the version
world_id              the world this version belongs to
source_snapshot_id    the immutable structural snapshot it preserves
parent_version_id     the alternate version it was branched from, or null
title                 what the person called it
origin                authored
style_version_id      the appearance reference, or null for the source appearance
state_sha256          canonical digest of the current delta: the concurrency token
edit_seq              monotonic count of applied edits
created_by, created_at
```

`source_snapshot_id` is a real foreign key, so a version can only ever name a snapshot in its own
workspace and world. `parent_version_id` is the lineage the structural plane cannot express: many
alternates may branch from one source, and an alternate may branch from another alternate. Both
sit on the same source snapshot, and neither moves the structural current pointer.

`state_sha256` is the digest of the canonical delta document, computed with the same JCS subset as
every snapshot section. It is the optimistic concurrency token, chosen to be content-derived rather
than a counter so that two edits producing identical state are identical bases, exactly as
`base_topology_digest` behaves for appearance.

The delta has four parts, and the version stores all four:

| Part | Storage | Public mutation route |
| --- | --- | --- |
| Additions | `world_alternate_object` rows with `removed = false` | Yes |
| Removals | authored objects with `removed = true`; source elements in `world_alternate_element_override` with `suppressed = true` | Authored objects yes; source elements no |
| Transforms | the fixed-point transform on an authored object; a replacement transform on a source element override | Authored objects yes; source elements no |
| Appearance references | `style_version_id` on the version | At creation only |

Source-element suppression and source-element transform are stored, digested, read back and
tested, because the World state contract requires an alternate version to store removals and
transforms of its source and because the package extension cannot be specified against a data
contract that is missing half of the delta. Their public mutation route is deliberately not opened
in this slice: suppressing a structural element changes what a person can reach, and that is a
protected-value review, not an object edit. Until that review exists, only the reviewed composer
writes them.

## 3. A created object

```text
object_id             stable within the version, lowercase, chosen by the caller
asset_sha256          reviewed asset reference, by content digest
region_id             the source snapshot region the transform is local to
transform             x_mm, y_mm, z_mm, yaw_microradians, scale_milli
origin.kind           authored, always
origin.role           fictional | personal, chosen by the person
behaviour             optional behaviour_key + behaviour_version + bounded parameters
removed               whether a removal is currently in force
created_edit_id       the edit that added it
last_edit_id          the edit that last changed it
```

That is the stored row. The last two are not on the wire: an edit id means little without the log
that explains it, and `edits[]` in section 7 is that log. The base version an edit was made against
is a property of the edit rather than of the object, and it lives on the edit row; section 5 has it.

The asset reference is a content digest, never a name and never a URL. `region_id` must be a region
of the source snapshot's topology, and the transform is **region-local**.

That frame is a deliberate difference from the structural plane, and it is the one place this
contract does not simply copy it. `world/placement.json` poses every element in a single shared
world frame; an authored object is posed against its region. The units are identical, so nothing
about the digest discipline changes, but the renderer must compose an object's transform with its
region's placement rather than using it directly. The reason is that a placement migration is an
expected operation on the structural plane: a reviewed recomposition may move a whole region, with
a recorded migration id, reason and approver. If authored objects were posed in the world frame,
that approved move would leave every object a person had put in the region floating where the
region used to be, and no record on this plane would show why. Region-local means the move carries
them, which is what a person who placed a lantern inside a room means by placing it there.

`origin.role` is chosen by the person and is never inferred. Product direction is explicit that an
uploaded image establishes no personal association by itself and that the first slice asks rather
than classifies. There is no automatic reality classifier here and none is planned for this route.
`origin.kind` is always `authored`: this plane cannot express a claim about the source world, and
nothing it stores may be read as evidence.

A removal is stored, not executed. The row survives with `removed = true`, so the object id stays
stable and undo restores it rather than resurrecting a new identity.

### Behaviours

A behaviour is `behaviour_key` plus `behaviour_version` plus parameters, all validated against
`world_object_behaviour_registry` before any write. The registry is reviewed migration data. A
parameter is `integer` with an inclusive minimum and maximum, `choice` over at least two values, or
`toggle`. An unknown key, an unknown version, an unknown parameter, a missing parameter, a wrong
kind, and an out-of-range value all fail closed with `invalid_object_data`.

The one seeded behaviour is the one the first milestone names.

| Key | Version | Parameters |
| --- | --- | --- |
| `motion.bounded-path` | 1 | `travel_mm` 100 to 10000, `period_milliseconds` 500 to 60000, `axis` one of `x`, `y`, `z`, `easing` one of `linear`, `smooth` |

Bounded motion with trigger, stop and reset is the runtime's contract, not a stored parameter: the
registry bounds the path, and the renderer owns the controls. A behaviour cannot carry code, a
shader, a URL, or a selector, for the same reason a style recipe cannot.

## 4. The reviewed asset registry

`world_reviewed_asset` is a global reviewed catalog, not tenant data. It is seeded by migration
0042 and is read-only to the runtime roles by grant, like every other registry in this schema.

```text
asset_key        stable reviewed name
content_sha256   SHA-256 of the GLB bytes
media_type       model/gltf-binary
byte_size        exact byte length
licence_id       CC0-1.0
licence_sha256   SHA-256 of the licence text bytes
title, summary   what the asset is
```

Three small CC0 assets are seeded. Their bytes are **generated deterministically** by
`exulanica.world.assets`, not committed, which is the rule `tests/conftest.py` states for the
Python suite's images: it carries no binary fixture, and a generated asset has an exact
reproducible digest that the migration can pin. `web/` does commit binary fixtures; this plane
follows the backend rule, not that one. They are original geometry authored for this repository and
dedicated to the public domain under CC0 1.0, so the licence claim is one this project can actually
make. The licence text is stored as its own blob and referenced by digest. Two precedents already do
this: `license_document_sha256` in `exulanica/ingest/reference_admission.py` for benchmark
admission, and `dataset/materials.json` in the training package profile, which binds a licence
declaration to a signed inventory of asset digests. This registry is neither of those. It is not
`world_topology_source`, which is workspace-scoped and either names an evidence span or records
why none exists; a reviewed CC0 mesh is global, carries no evidence and makes no claim about the
source world.

| Key | Geometry |
| --- | --- |
| `cc0.marker-cube` | A half-metre cube |
| `cc0.marker-pillar` | A square pillar |
| `cc0.marker-plate` | A flat square plate |

`seed_reviewed_assets(store)` writes the GLB and licence bytes into the content-addressed store.
The registry row is the reviewed decision; the store holds the bytes; the two are separate because
a migration cannot write to an object store and should not pretend to.

**That call is not yet on a deployment path**, and until it is, a deployment that has run migration
0042 holds three registry rows whose bytes nothing wrote, so every asset read honestly answers
`unavailable_asset`. It belongs beside the store's construction in `exulanica/api/services.py`
(`build_services`) or in the `exulanica-db` command that already runs migrations and role grants,
and it is idempotent, so running it on every start costs three hashes of about 800 bytes each.
Neither of those files is writable by the task that wrote this document, which is why the wiring is
named here rather than done.

The HTTP routes report two states and never invent a third:

- `available`: the registry row exists and the bytes are present in the store;
- `unavailable_asset`: the registry row exists and the bytes are not.

`WorldObjectRepository.reviewed_assets` also answers `unknown`, and only when it was called
without a store. That is not a third product state; it is the repository refusing to say
"present" about bytes nobody looked for. Every route passes the store, so no response carries it.

An unavailable asset yields no geometry, no placeholder mesh and no substitute imagery. This is the
same rule the source-media contract states, for the same reason: a fallback that looks like the
thing it replaces is a lie the renderer cannot take back.

## 5. Concurrency, undo, and reopening

Every mutation names the base it was made against: the version id and that version's
`state_sha256` at the moment the caller read it. The repository takes the same per-workspace
advisory lock the structural plane uses, `pg_advisory_xact_lock(hashtextextended(workspace_id::text,
880024))`, re-reads the version row `for update`, and compares. Sharing that seed rather than
minting a new one is what makes an object edit serialize against a structural commit and against
`tg_world_structure_invalidate_on_tombstone`, closing the same check-then-commit race deletion
already closes for snapshots. A mismatch changes nothing and raises
`stale_object_base`. That is the named error the World state contract asks for, and it is the same
compare-and-swap both existing world planes use.

Every applied edit appends one immutable row to `world_alternate_version_edit`:

```text
edit_id, edit_seq, kind, object_id, element_id, undone_edit_id,
base_state_sha256, result_state_sha256, before_document, after_document, actor, recorded_at
```

`before_document` and `after_document` are the canonical documents on either side of the edit,
which is what makes undo a stored fact rather than a client's memory of one.

**Undo** appends a new edit of kind `undo` naming the edit it reverses, and restores that edit's
`before_document`. History is never rewritten.

It reverses **the newest edit that no undo already names**, so a person who made three edits can
take all three back. Reversing "the newest edit" instead would refuse the second undo, because by
then the newest edit is an undo, and a control that works once is not an undo. Every edit kind is
reversible, including the two element-override kinds; an earlier version reversed object edits
only, which let one override sit at the head of the log and block undo for the whole version
permanently.

Undo is still not redo. An undo edit is never itself a candidate. When every edit has been
reversed, a further undo is refused with `invalid_object_state`, as it is on a version with no
edits at all.

One case does remove a row: undoing an `add_object` deletes the `world_alternate_object` row,
because the state that edit was made against did not contain the object. The **edit log** is
append-only and enforced so by trigger; the materialised delta is current state and is not.

**Reopening** is a read. Every value in this contract is a database row, so closing the session,
reconnecting, and reading `GET /world/versions/{id}` returns the same objects, the same transforms
and the same attached behaviours. Nothing here lives in a browser view.

**Invalidated sources.** When a tombstone covers the source snapshot's dependencies, the existing
trigger writes the invalidation row. A read of the alternate version then reports
`source_invalidated: true`, and any further edit is refused with `invalidated_source_version`. The
version and its history are not deleted: the person's authored work survives the deletion of the
source it was placed against, and it simply cannot be extended against a source that is gone.

## 6. HTTP surface

All routes require a bearer token. Bodies are snake_case only. The `/world/styles` routes accept
frontend camelCase aliases because they adapt an existing client recipe; this surface has no such
prior client, so it does not invent a second casing. `web/packages/graph-client` fixtures are
snake_case, and this fixture matches them.

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/world/versions` | Every alternate version of this world, newest first |
| `POST` | `/world/versions` | Create an alternate from a source snapshot or another version |
| `GET` | `/world/versions/{version_id}` | One version with its objects, overrides and edit history |
| `POST` | `/world/versions/{version_id}/objects` | Add one authored object |
| `POST` | `/world/versions/{version_id}/objects/{object_id}/move` | Replace one object's transform |
| `POST` | `/world/versions/{version_id}/objects/{object_id}/remove` | Store a removal |
| `POST` | `/world/versions/{version_id}/objects/undo` | Reverse the newest edit not already reversed |
| `GET` | `/world/assets` | The reviewed asset registry with availability |
| `GET` | `/world/assets/{asset_key}` | One reviewed asset |
| `GET` | `/world/assets/{asset_key}/bytes` | The reviewed GLB bytes |
| `GET` | `/world/assets/{asset_key}/licence` | The licence text those bytes are published under |

The two byte routes follow `GET /geometry/{artifact_id}`: a `Response` with an `ETag` that is the
content digest, `X-Content-Type-Options: nosniff` and `Accept-Ranges: none`. They differ from it in
one header, deliberately. The point map sets `Cache-Control: no-store` because it serves a personal
derivative a tombstone must be able to reach, and a cached copy is a copy deletion cannot clear. A
reviewed CC0 mesh holds nothing personal, so it is cacheable: `private, max-age=3600`.

Cacheable, and not `immutable`. The bytes are immutable under content addressing; these URLs are
not, because they are keyed by `asset_key`, and a later migration could point that key at a
different digest. `immutable` tells the browser never to revalidate, which would leave the ETag
unable to correct it. A reviewed asset is never a citation target and never evidence.

Remove and undo are POST rather than DELETE because both carry a base token in the body and both
append history rather than destroying a row. A DELETE that stores a row and requires a request body
would misdescribe itself twice.

The problem codes are distinct, because the recovery differs:

| HTTP | Code | Recovery |
| --- | --- | --- |
| `422` | `invalid_object_data` | Correct the asset, region, transform, origin role, behaviour or parameter |
| `409` | `stale_object_base` | Read the version again and re-issue the edit against the new `state_sha256` |
| `409` | `invalid_object_state` | Do not move or remove an already-removed object, re-add an existing id, or undo an empty history |
| `409` | `invalidated_source_version` | The source was deleted; branch from a live snapshot instead |
| `424` | `unavailable_asset` | Restore the reviewed bytes; render the recorded state, never a substitute |
| `404` | `unknown_reference` | Absent and cross-workspace ids are indistinguishable |

`unknown_reference` and `unavailable_asset` reuse the existing application error classes and their
existing handlers. The four new codes are mapped inside `exulanica/api/routes/world.py`, following
the local `_problem` helper that `world_write.py` already uses, so registering this surface adds no
new global exception handler.

## 7. Wire shape

`web/packages/graph-client/test/fixtures/world-objects.json` is one complete `GET
/world/versions/{id}` body. It is the fixture the renderer task consumes, and it is stable once
published: fields may be added, and no field in it may be renamed, retyped or removed.

```text
schema_version        1
version_id            uuid
world_id              text
source_snapshot_id    uuid
parent_version_id     uuid or null
title                 text
origin                "authored"
style_version_id      uuid or null
state_sha256          64 lowercase hex, the base token for the next edit
edit_seq              integer
source_invalidated    boolean
created_by            uuid
created_at            RFC 3339
objects[]             object_id, asset{...}, region_id, transform{...},
                      origin{kind,role}, behaviour or null, removed
element_overrides[]   element_id, suppressed, transform or null
edits[]               edit_id, edit_seq, kind, object_id, element_id, undone_edit_id,
                      base_state_sha256, result_state_sha256, actor, recorded_at
```

Those sixteen names are the top level of the body. They are not nested under a `version` key, and
an object carries no `created_edit_id` or `last_edit_id`: those two are columns the repository
keeps and does not publish, because an edit id is only meaningful beside the log that explains it,
which `edits[]` already is.

`transform` always carries its own units, so a reader never has to know them from context:

```text
coordinate_space  "region_local"
coordinate_unit   "millimetre"
x_mm, y_mm, z_mm  integers
yaw_microradians  integer
scale_milli       integer, 1000 is unscaled
```

`asset` embeds the whole registry row and its availability, so a renderer holding one version body
knows what it may draw, and under what licence, without a second call:

```text
asset_key, title, summary, media_type, content_sha256, byte_size,
licence_id, licence_sha256, availability
```

`content_sha256` is the object's actual reference. There is no separate `asset_sha256` on the wire
object, because it would be that same value written twice.

`objects[]` is sorted by `object_id` and `element_overrides[]` by `element_id`. Those two orders
are load-bearing: `canonical_delta_document` sorts by the same keys, so the state digest is
computed over exactly that sequence. `edits[]` is sorted by `edit_seq` ascending, which the digest
does not cover at all; it is ordered because a log read backwards is a log misread.

## 8. What a later package extension would need

`exulanica-wmp-1.0` is untouched. `REQUIRED_PAYLOAD_PATHS` in `exulanica/world_package/package.py`
is an exact frozen set and `world_package_export.profile_version` is checked equal to
`exulanica-wmp-1.0` by migration 0028, so adding a payload path to the current profile would
invalidate every existing export. A later profile, `exulanica-wmp-1.1`, would need:

1. two new required payload paths, `world/versions.json` and `world/objects.json`, holding the
   alternate versions and their deltas in the canonical order above;
2. a reviewed-asset section listing `asset_key`, `content_sha256`, `media_type`, `byte_size`,
   `licence_id` and `licence_sha256`. Asset **bytes** stay out of the package: the package is a
   descriptor set with a Merkle manifest, and `.glb` bytes belong in the content-addressed store
   the descriptors reference;
3. a behaviour section pinning `behaviour_key` and `behaviour_version` against the registry, so a
   verifier can refuse a package naming a behaviour it does not know;
4. a verifier rule that an alternate version's `source_snapshot_id` resolves to a snapshot in the
   same package, and that its `state_sha256` re-derives from the exported delta;
5. a decision, which this document does not make, about whether an exported alternate version whose
   source snapshot was invalidated by deletion is exportable at all.

Until that profile exists, `GET /world/versions` is the only way to read this state, and the
package must not claim to carry it.

## 9. Verification

`tests/test_world_objects.py` needs no database. It covers the object id contract, including the
proof that the Python regex and the schema's CHECK are the same string and refuse the same inputs;
the canonical delta and its order independence; fixed-point refusal of floats and of booleans;
every behaviour bound; unknown region and unreviewed asset; that the generated GLB assets are
readable glTF 2.0 with outward-wound faces and reproduce the digests migration 0042 pinned; that
both registries are in `READ_ONLY_TABLES`; and that the published fixture's `state_sha256`
recomputes from the fixture's own delta.

`tests/test_world_objects_postgres.py` covers lineage from a source snapshot and from another
version, stale-base refusal under one connection and under two, multi-level undo, undo of an
element override, reopening a version on a genuinely new connection with its behaviour still
attached, cross-workspace invisibility on both the read and the write path, and a committed
tombstone invalidating every version derived from the covered snapshot. It also runs the existing
appearance preview, apply and rollback cycle against the same structural version that carries an
authored object, and counts the other planes' rows across an object edit to show neither family
writes the other's tables.

`tests/test_world_objects_api.py` covers the full add, move, remove and undo cycle over HTTP, the
reviewed asset registry including byte and licence delivery, and all six problem codes in the
table above.

Each invariant carries a negative control: a test that the guard refuses the thing it claims to
refuse, rather than passing because the operation never ran. Two of them are regressions with a
recorded cause. An object id that Python accepted and the schema refused reached the caller as a
500 rather than a 422, twice: once because the two regexes differed, and once because Python's
`$` also matches before a trailing newline where PostgreSQL's does not. Both are pinned.
