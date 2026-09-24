# Authored world versions and created objects

Status: **DECISION** and **IMPLEMENTED** for alternate world versions, authored object add/move/
remove/behaviour/undo, durable environment placement, the reviewed asset registry, the bounded
object-behaviour registry, and the opt-in environment-instances 1.0 package extension. Object
rendering and bounded-motion controls have synthetic browser coverage, and the authored-world
1.0 package extension exists. Unified retrieval, the conversational authoring service, and
complete personal-scene visual acceptance are not implemented.

This is the fourth world plane under [ADR-0007](adr/0007-world-composition-and-customization.md).
The three that exist are appearance ([world-style-backend.md](world-style-backend.md), migrations
0017 and 0023), structural authority ([spatial-world-authority.md](spatial-world-authority.md),
migration 0020) and interaction policy (migration 0021). All three share one shape: immutable
versions, one mutable current pointer, a preview lifecycle and compare-and-swap. This plane shares
the discipline and not the lifecycle, for the reasons in section 1. It implements the World state
contract in [product-direction.md](product-direction.md) and steps 2, 3 and 4 of the first
milestone. The implementation is migration `0042_authored_world_objects.sql`,
`exulanica/world/objects.py`, `exulanica/world/object_repository.py`,
`exulanica/world/edit_kinds.py`, `exulanica/world/authored_delta.py`,
`exulanica/world/assets.py`, migration `0050_durable_environment_composition.sql`,
`exulanica/world/environment_instances.py`, and the `/world/versions` and `/world/assets` routes.

<details>
<summary>Sections</summary>

- [1. The decision: a separate plane, bound to the snapshot the way appearance is](#1-the-decision-a-separate-plane-bound-to-the-snapshot-the-way-appearance-is)
- [2. An alternate version](#2-an-alternate-version)
- [3. A created object](#3-a-created-object)
- [4. The reviewed asset registry](#4-the-reviewed-asset-registry)
- [5. Concurrency, undo, and reopening](#5-concurrency-undo-and-reopening)
- [6. HTTP surface](#6-http-surface)
- [7. Wire shape](#7-wire-shape)
- [8. Package projection](#8-package-projection)
- [9. Verification](#9-verification)
- [10. Opening the first alternate from composed sources](#10-opening-the-first-alternate-from-composed-sources)
- [11. Durable environment instances](#11-durable-environment-instances)
- [Bounded scene-extraction preparation](#bounded-scene-extraction-preparation)
- [Authored district object coordinates](#authored-district-object-coordinates)

</details>

## 1. The decision: a separate plane, bound to the snapshot the way appearance is

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

Six tables each store something no existing table can hold: an alternate version and its
lineage, an authored object, an override of a source element, an append-only edit log, a reviewed
asset catalog, and a bounded object-behaviour catalog.

### Why the interaction registry is not the behaviour registry

`interaction_capability_registry` is a per-world viewer policy. Its `category` check admits only
`comfort`, `navigation`, `disclosure` and `initiative`, and `world_interaction_policy_version`
stores one value per capability for the whole world. An object behaviour is per object, and two
lanterns in one version may hold different bounded parameters. The behaviour registry copies its shape,
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
| Additions | `world_alternate_object` rows with `removed = false` and `addition_undone = false` | Yes |
| Removals | authored objects with `removed = true` and `addition_undone = false`; source elements in `world_alternate_element_override` with `suppressed = true` | Authored objects yes; source elements no |
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

Reviewed GLBs that declare no materials receive a renderer-owned matte material derived from the
world's appearance palette. Appearance preview, apply and discard update this fallback; declared
asset materials remain unchanged. This presentation rule does not rewrite asset bytes, digests or
normals. Unaimed ground placement starts 3.5 metres ahead of the visitor so the reviewed marker's
ground contact remains visible at the supported minimum field of view. Existing saved transforms
stay fixed, and the browser's region bounds still constrain new placements.

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
than classifies. There is no automatic reality classifier here and this route specifies none.
`origin.kind` is always `authored`: this plane cannot express a claim about the source world, and
nothing it stores may be read as evidence.

A removal is stored, not executed. The row survives with `removed = true`, so the object id stays
stable and undo restores it rather than resurrecting a new identity.

### Behaviours

A behaviour is `behaviour_key` plus `behaviour_version` plus parameters, all validated against
`world_object_behaviour_registry` before any write. The registry is reviewed migration data, and
`GET /world/behaviours` serves it as the table holds it, so a client chooses a behaviour and its
parameters by asking the server rather than by keeping a copy
(`tests/test_world_behaviours_route.py` holds every advertised bound to the one enforced). A
parameter is `integer` with an inclusive minimum and maximum, `choice` over at least two values, or
`toggle`. An unknown key, an unknown version, an unknown parameter, a missing parameter, a wrong
kind, and an out-of-range value all fail closed with `invalid_object_data`.

The one seeded behaviour is the one the first milestone names.

| Key | Version | Parameters |
| --- | --- | --- |
| `motion.bounded-path` | 1 | `travel_mm` 100 to 10000, `period_milliseconds` 500 to 60000, `axis` one of `x`, `y`, `z`, `easing` one of `linear`, `smooth` |

A behaviour reaches an object in one of two edits, and both run the same check. `add_object` may
name one when the object is created. `set_object_behaviour`, through `POST
/world/versions/{version_id}/objects/{object_id}/behaviour`, gives an object that already exists a
behaviour, replaces the one it has, or takes it away when the body's required `behaviour` field is
`null`. It changes nothing else about the object. It is an edit of its own so that undo reverses
the motion and leaves the object where it stands: like a move, it stores the whole object document
on both sides, and undo restores the previous behaviour with its parameters, a clear included. An
edit that would leave the behaviour as it is, or that names a removed object, is refused with
`invalid_object_state`. A refused edit writes nothing, and a stale base answers
`stale_object_base` as every object edit does. Migration
`0096_a_placed_object_s_behaviour_can_change.sql` admits the kind in the edit log's two CHECK
constraints.

Bounded motion with trigger, stop and reset is the runtime's contract, not a stored parameter: the
registry bounds the path, and the renderer owns the controls. A behaviour cannot carry code, a
shader, a URL, or a selector, for the same reason a style recipe cannot.

The renderer moves the object from its authored transform along the named axis of its region, out
to `travel_mm` and back once every `period_milliseconds`, and reset returns it to the authored
transform exactly (`web/packages/atlas-core/src/behaviour/bounded-motion.ts`). The controls write
nothing, so a reopened object stands at rest at its authored transform and does not start by
itself. The motion advances by the renderer's frame time, which PlayCanvas caps at 0.1 s a frame:
a page drawing fewer than ten frames a second runs the motion slower than its stated period.

Two consequences outside this plane. A saved world's society recomposes its input in the same
transaction as each behaviour edit, and while any object carries a behaviour that input is
unavailable with the reason `unsupported_active_behaviour:<object id>`; taking the behaviour away
makes it available again. A version whose edit chain carries `set_object_behaviour` exports under
the 1.1 package extensions and is withheld under 1.0, as
[world-memory-package.md](world-memory-package.md#which-versions-an-extension-carries) describes; a
behaviour named by `add_object` exports with its object under either.

## 4. The reviewed asset registry

`world_reviewed_asset` is a global reviewed catalog, not tenant data. It is seeded by migration
0042 and is read-only to the runtime roles by grant, like every other registry in this schema.

Reviewed external CC0 assets can also be imported through the host administration command
`scripts/import_reviewed_world_asset.py`. Its manifest pins the asset bytes, exact upstream
license evidence, source URL/revision and producer, and the command requires `--kind`, the
asset's kind below. Validation refuses digest/size mismatches, external GLB dependencies and
unsupported codecs. It does not certify animation quality or character rig compatibility. The
command validates by default; publication retains the asset, license and canonical import receipt
before committing a registry row.

Migration 0054 adds append-only import receipts. Repeating an identical import is idempotent;
an existing key or its provenance cannot be rebound. Withdrawing a registry entry preserves
its import receipt, and the import command cannot silently republish that withdrawn key.
These global reusable assets do not grant permission to display a source-derived person.

```text
asset_key        stable reviewed name
content_sha256   SHA-256 of the GLB bytes
media_type       model/gltf-binary
byte_size        exact byte length
licence_id       CC0-1.0
licence_sha256   SHA-256 of the licence text bytes
title, summary   what the asset is
kind             object | component, declared by whoever publishes the row
```

### Which assets may be placed

The registry holds every reviewed container a catalog publishes, and only an `object` may be placed.
[`exulanica/world/asset_kinds.py`](../exulanica/world/asset_kinds.py) is the registry of kinds and
says what each permits: an `object` is reviewed geometry a person places as an authored object; a
`component` is a container another catalog composes and fetches by key, such as a character's
body, a worn part or a material pack. The publisher declares the kind and nothing infers one from a
key or a title: migration 0101 declares the three generated markers objects,
`import_reviewed_asset` requires a kind, and the character catalog's publish step
(`scripts/prepare_character_people.py --import`) declares every container it publishes a
component. The schema's `world_reviewed_asset_kind_check` lists the same kinds as the registry.

`GET /world/assets` lists only placeable assets, because it is what a client chooses an object
from. `GET /world/assets/{asset_key}`, its bytes and its licence serve every reviewed asset,
because the character renderer fetches components by key, and each view carries `placeable`.
Placing a component is refused by name: `POST /world/versions/{version_id}/objects` answers 422
`invalid_object_data` with a detail that names the asset, and composition answers
`asset_not_placeable`. The kind is checked before the bytes, because restoring missing bytes is not
the recovery for a component. An object a version already holds keeps its asset whatever its kind:
it reads, draws, moves, is removed and is undone as before. Only placing a component is refused.

Migration 0101 declares the kind of every row that existed before it by allowing, not by
defaulting. The three `(asset_key, content_sha256)` pairs 0042 pinned become objects, the pairs the
committed character import manifests name become components, and any other row stops the migration
with an error that names it. The migration reads nothing outside the database.

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

The application's lifespan calls it at boot, after the schema check and before the derivative
worker starts. It is idempotent under content addressing, so a warm start costs three hashes of
about 800 bytes and writes nothing.

Three placements were considered and two rejected. The `exulanica-db` command runs migrations and
role grants once, which is the right moment, but the composition does not mount the media volume
into that container, so it cannot reach the store. `build_services` constructs the store and would
be the tidiest line, but it resolves configuration and returns, and no test calls it: every test
builds a `Services` by hand, so seeding there would leave the one path a deployment depends on
unexercised. The lifespan runs for a hand-constructed `Services` too, which is why
`tests/test_world_objects_api.py` seeds nothing and asserts the bytes are present anyway.

The call is deliberately not wrapped in `try`/`except`. A store this cannot write is a store the
evidence path cannot write either, so it is a broken deployment rather than a degraded feature, and
it should say so at boot rather than at the first asset read.

The HTTP routes report two states and never invent a third:

- `available`: the registry row exists and the bytes are present in the store;
- `unavailable_asset`: the registry row exists and the bytes are not.

`WorldObjectRepository.reviewed_assets` also answers `unknown`, and only when it was called
without a store. That is not a third product state; it is the repository refusing to say
"present" about bytes nobody looked for. Every route passes the store, so no response carries it.

An unavailable asset yields no geometry, no placeholder mesh and no substitute imagery. This is the
same rule the source-media contract states, for the same reason: a fallback that looks like the
thing it replaces is a lie the renderer cannot take back.

Adding an object therefore requires its bytes. `WorldObjectRepository.add_object` refuses an asset
whose registry row exists and whose bytes are not in the content-addressed store, and a repository
constructed without a store refuses every addition because it cannot look, as environment
composition does. It is one rule on one code path for both routes that add objects:
`POST /world/versions/{version_id}/objects` answers 424 `unavailable_asset` through the
application-wide handler, and composition apply answers 409 `composition_blocked` with detail
`asset_bytes_unavailable`. Nothing is written in either case. Moving, removing and undoing an
object that already exists do not read its bytes, so history stays correctable after bytes go
missing.

## 5. Concurrency, undo, and reopening

Every mutation names the base it was made against: the version id and that version's
`state_sha256` at the moment the caller read it. The repository takes the same per-workspace
advisory lock the structural plane uses, `pg_advisory_xact_lock(hashtextextended(workspace_id::text,
880024))` through `exulanica/world/workspace_lock.py`, re-reads the version row `for update`, and
compares. `tests/test_workspace_lock.py` holds every other statement of that seed to the helper's
and refuses one anywhere outside the modules that already restated it. Sharing that seed rather than
minting a new one is what makes an object edit serialize against a structural commit and against
`tg_world_structure_invalidate_on_tombstone`, closing the same check-then-commit race deletion
already closes for snapshots. A mismatch changes nothing and raises
`stale_object_base`. That is the named error the World state contract asks for, and it is the same
compare-and-swap both existing world planes use.

Every applied edit appends one immutable row to `world_alternate_version_edit`:

```text
edit_id, edit_seq, kind, object_id, element_id, environment_instance_id, point_map_instance_id,
undone_edit_id, base_state_sha256, result_state_sha256, before_document, after_document, actor,
recorded_at
```

`before_document` and `after_document` are the canonical documents on either side of the edit,
which is what makes undo a stored fact rather than a client's memory of one.

**The kinds are one registry.** `exulanica/world/edit_kinds.py` lists every kind the log may hold
and the subject each one changes: an authored object, an element of the source snapshot, a placed
environment instance or a placed photo point map, each named by its own id column. Adding a kind
is still a migration, because the CHECK constraints `world_alternate_version_edit_kind_check` and
`world_alternate_edit_names_its_subject` are the storage authority, and a migration restates both
with every kind. `tests/test_edit_kinds.py` holds the registry equal to the newest migration's text
of both constraints and to the live schema's, requires an undo rule and a history field for every
subject, keeps each package verifier's closed list inside the registry with the same subjects, and
reads every `kind=` the repository writes from the source and requires it to be registered with the
subject column it writes; `tests/test_authored_delta.py` requires a delta section for every subject.
A migration that restates the constraints from an older list, dropping a kind another change
added, fails the first of those.

**Undo** appends a new edit of kind `undo` naming the edit it reverses, and restores that edit's
`before_document`. History is never rewritten.

It reverses **the newest edit that no undo already names**, so a person who made three edits can
take all three back. Reversing "the newest edit" instead would refuse the second undo, because by
then the newest edit is an undo, and a control that works once is not an undo. The repository
defines an inverse for every subject the registry names: object, element-override, environment
and photo point map edits. Undo finds it through the registry, from the edit's kind to its subject
and from the subject to the method that restores it. An edit whose kind the registry does not name
is refused before anything is written, with `invalid_object_state` and the kind in the detail,
rather than being read as some other subject's document. The ordinary runtime can reverse these
edits without deletion authority. Tests exercise that restricted role, including replacement and
restoration of element overrides and environment addition, movement and removal.

Undo is still not redo. An undo edit is never itself a candidate. When every edit has been
reversed, a further undo is refused with `invalid_object_state`, as it is on a version with no
edits at all.

Undoing an `add_object` retains its projection row with `addition_undone = true`, because the
ordinary runtime has no deletion authority. Canonical reads and authored-world package export
omit that row, restoring the exact state before the addition. Its `last_edit_id` names the actual
undo edit. A later addition may reuse that object ID through a constrained update that clears the
flag; an ordinary removed object remains a distinct, stored removal. The **edit log** remains
append-only and enforced so by trigger.

Element overrides and environment additions use the same explicit retained-projection flag.
Canonical reads, supported package projections and environment selection omit undone additions.
Replacing an override updates its projection and appends history. Reusing an undone environment
ID revalidates current source authority and exact lineage; undo never restores withdrawn source
permission. Ordinary environment movement and removal retain immutable source bindings.
Environment composition history is exported by the environment-instances package extension, not
by authored-world 1.0. Live undo and selection behavior do not grant source-use rights in that
package.

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
| `POST` | `/world/versions/{version_id}/objects/{object_id}/behaviour` | Give one object a reviewed behaviour, replace it, or take it away with `null` |
| `POST` | `/world/versions/{version_id}/objects/undo` | Reverse the newest edit not already reversed |
| `GET` | `/world/assets` | The reviewed assets a person may place, with availability |
| `GET` | `/world/assets/{asset_key}` | One reviewed asset of any kind, and whether it may be placed |
| `GET` | `/world/assets/{asset_key}/bytes` | The reviewed GLB bytes |
| `GET` | `/world/assets/{asset_key}/licence` | The licence text those bytes are published under |
| `GET` | `/world/behaviours` | The reviewed behaviour registry, with each parameter's kind and bounds |

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
| `409` | `invalid_object_state` | Do not move, remove or change the behaviour of an already-removed object, re-add an existing id, set the behaviour an object already has, or undo an empty history |
| `409` | `invalidated_source_version` | The source was deleted; branch from a live snapshot instead |
| `424` | `unavailable_asset` | Restore the reviewed bytes; an addition is refused, and the recorded state renders without a substitute |
| `404` | `unknown_reference` | Absent and cross-workspace ids are indistinguishable |

`unknown_reference` and `unavailable_asset` reuse the existing application error classes and their
existing handlers. The four object-edit codes are mapped inside `exulanica/api/world_edit.py`, following
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
licence_id, licence_sha256, availability, placeable
```

`content_sha256` is the object's actual reference. There is no separate `asset_sha256` on the wire
object, because it would be that same value written twice.

`objects[]` is sorted by `object_id` and `element_overrides[]` by `element_id`. Those two orders
are load-bearing: `canonical_delta_document` sorts by the same keys, so the state digest is
computed over exactly that sequence. `edits[]` is sorted by `edit_seq` ascending, which the digest
does not cover at all; it is ordered because a log read backwards is a log misread.

## 8. Package projection

Package projection preserves `exulanica-wmp-1.0` byte compatibility and uses the opt-in
`exulanica-wmp-ext-authored-world` 1.0 extension. It exports alternate versions, source snapshots,
authored objects, element overrides, edit chains, reviewed asset descriptors and bounded behavior
references. Asset bytes and runtime code remain excluded.

The verifier re-derives every version state digest, closes edit and parent chains, validates source
and region references, checks asset and behavior declarations, and withholds versions whose source
snapshot deletion invalidated. `import-check` reports receiver capabilities; it does not load the
world.

The canonical contract, layout, compatibility behavior, and tests for objects, overrides and
schema-version-1 deltas are in
[World Memory Package: Authored-world extension 1.0](world-memory-package.md#authored-world-extension-10).
That extension does not export `environment_instances` and does not emit schema version 2.
Environment-inclusive state is
[World Memory Package: Environment-instances extension 1.0](world-memory-package.md#environment-instances-extension-10).
That directory is lineage-closed: a parent pointer resolves there, schema-v1 ancestors keep
their honest schema-v1 delta and may appear in both directories, and a schema-v1 descendant
of an environment-bearing parent is exported there rather than under authored-world 1.0.
Society state is outside both. A receiver without the environment-instances capability must
omit those versions and must not infer objects from authored-world 1.0 as the whole authored
state.

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

`tests/test_reviewed_asset_placeability.py` publishes the committed character catalog through its
own publish step and reads it back through the routes: the list holds only the three markers, every
container reads by key as not placeable, each stored kind matches the catalog that published it,
the schema's kind check equals the registry, placing a component is refused by name on the object
route and in composition, and a version that already holds one keeps reading, composing and
editing. `tests/test_reviewed_asset_kind_migration.py` applies 0101 to schemas migrated just
below it: a registry holding only the markers, every pair 0101 allows, and rows it must refuse by
name.

`tests/test_edit_kind_undo_postgres.py` pins undo for every registered kind from the log rows: the
state token and the subject's document return to the ones before the edit, and the undo row names
the edit it reverses, repeats its subject column and stores the documents on both sides. It also
shows an unregistered kind refused with nothing written. `tests/test_edit_kinds.py` is the registry
parity described in section 5, and `tests/test_authored_delta.py` holds golden state digests for
every delta schema version and requires every section to be passed by keyword.

Each invariant carries a negative control: a test that the guard refuses the thing it claims to
refuse, rather than passing because the operation never ran. Two of them are regressions with a
recorded cause. An object id that Python accepted and the schema refused reached the caller as a
500 rather than a 422, twice: once because the two regexes differed, and once because Python's
`$` also matches before a trailing newline where PostgreSQL's does not. Both are pinned.

## 10. Opening the first alternate from composed sources

`POST /world/versions/bootstrap` accepts `base_topology_digest` (the value returned by
`GET /world/styles/current`) and an optional `title`. It accepts no source slots, evidence,
placements or replacement topology from the caller. The existing object placement button offers
this action when no alternate exists, and sends it only after the person confirms. Opening a
version does not place the selected object; the person then confirms that separate edit.

`bootstrap_world` is shared by this route and `prepare_sandbox_world`. Under the structural
workspace lock it checks the caller's digest, reads only that world's current composed contract,
and opens the first snapshot through structural preview/apply. Every source gets an element with
its original slot key and evidence binding, including missing evidence and world-owned slots.
Source IDs, region membership, missing reasons and compatibility are preserved exactly. Historical
contracts and other worlds do not contribute slots. Composition takes the same lock.

The snapshot's foreign key requires a contract keyed by the structural topology digest. Bootstrap
registers that derived contract with the exact original source rows through the shared immutable
`register_topology_history` writer. It never activates the derived contract or writes appearance
state. Ordinary composition still uses `register_topology` to register and activate a contract. The structural digest and composed digest
are different identities; neither is substituted for the other. `/world/source-media` and the
current composed digest remain unchanged, including across a retry with the original caller token.
The preservation option on structural apply refuses any candidate other than the exact plain
composition of the current contract and refuses a non-initial snapshot.

`composed.py` writes every sourced element and required destination as explicitly unplaced. It
does not invent gallery spacing, collision, or a measured place. That unplaced layout is not a
reconstruction and is not reviewed-source materialization. Authored objects remain region-local
deltas against the immutable snapshot, so a subsequent source re-compose leaves them intact.

Style bound to composed topology T1 meeting structural snapshot T2 is classified by
`classify_structure_style_compatibility`. The same `compatibility_key` is family binding only.
Hex equality between T1 and T2 is not the reason for compatibility. An existing current snapshot
is never replaced. Bootstrap reuse reports snapshot regions, not a later composed region's list.

The response contains `snapshot` (`applied` or `reused`), `snapshot_id`, `regions`, `version`
(`created` or `reused`), `version_id` and `state_sha256`. An existing current snapshot is never
replaced. If versions already exist, the newest is returned, matching the client's default; the
confirmation action explicitly reconnects to the returned ID. If only the snapshot exists, the
first alternate is created from it. Invalidated current snapshots or selected versions refuse with
`409 invalidated_source_version`. A stale composed digest always refuses with
`409 protected_topology_conflict`, even when a snapshot already exists. Repeating a successful
request creates no snapshots, previews, versions, topology contracts or audit events. A failure
opening the alternate rolls back the snapshot and its preview as well.

Verification is in `tests/test_world_bootstrap.py`, using PostgreSQL and the HTTP surface. No
migration is required. UI scope: only `web/packages/app/src/composition/objects.ts` changes, reusing
the existing placement button and confirmation surface.

## 11. Durable environment instances

Migration 0050 adds one workspace-scoped relation,
`world_alternate_environment_instance`. It is current authored state inside the existing alternate
version plane, not a second version system and not a claim about rendered quality. Its foreign keys
bind it to the owning alternate version, one admitted environment source, one derived render asset,
and, for a feature placement, one exact feature-index publication. Every foreign key includes the
workspace; the relation enables and forces row-level security.

The source side is immutable. It pins the admission, render asset and optional publication IDs;
source, render, index and receipt digests; source place; geographic frame and bounds; a
person-supplied integer anchor in that frame; and either `whole_asset` or an exact
feature ID/render-batch pair. A later provider revision or feature publication is never substituted.
The destination side is the source snapshot's region ID plus the same fixed-point region-local
transform used for authored objects. `origin.kind` remains `authored`, and the person must choose
`fictional` or `personal`; neither is inferred from geography or asset bytes.

Adding a whole asset requires current `compose` rights on the admitted source and render asset.
Adding a feature also requires the named publication to be current, the exact feature to name the
stored render batch, `compose` on its index asset, and `index` on the source, render and index
assets. All referenced content-addressed bytes must verify as present. These checks belong to the
environment source authority, `exulanica/world/environment_source_authority.py`, which the
repository asks inside its own transaction; a placed photo point map's source is asked of
`exulanica/world/point_map_source_authority.py` the same way. The repository repeats the binding
and authorization checks under `asset_read_lock()` immediately before transaction commit, after
the edit row and its society hook, so a concurrent withdrawal cannot pass an earlier check and then
commit. `tests/test_source_authorities_postgres.py` pins that lock order. New publications do not
rewrite existing placement history.

Availability is read separately from canonical authored state:

- `available`: every pinned binding is still current and all exact bytes are present;
- `unavailable_bytes`: the rows and bindings remain, but at least one pinned blob is absent;
- `withdrawn`: the admission, render asset or pinned index asset has been withdrawn;
- `binding_drift`: the pinned publication is no longer current or its exact binding no longer
  agrees with the live rows.

Availability does not participate in `state_sha256`, because a blob disappearing must not pretend
that the person authored a new version. When there are no environment rows,
`canonical_delta_document` retains the exact schema-version-1 bytes and digest. The presence of any
environment row selects schema version 2 and adds `environment_instances`, sorted by
`instance_id`.

Environment add, move and remove append to `world_alternate_version_edit` and use the existing
version `state_sha256` compare-and-swap. The HTTP routes are:

- `POST /world/versions/{version_id}/environment-instances`
- `POST /world/versions/{version_id}/environment-instances/{instance_id}/move`
- `POST /world/versions/{version_id}/environment-instances/{instance_id}/remove`
- `POST /world/versions/{version_id}/environment-instances/undo`

Move is continued composition. It succeeds only while the exact pinned binding remains current,
authorized and byte-available, and it changes only the destination transform. After withdrawal,
unavailability or binding drift it fails without changing state. Remove is a local authored
cleanup and remains allowed after withdrawal. Undo restores the stored prior authored document and
also remains allowed after withdrawal, including undoing a removal; a restored instance still
reports `withdrawn` and remains unavailable for rendering. This permits history correction without
turning undo into renewed source authorization.

The browser reads and draws available environment instances through the existing owned-district
binding. Package projection of those instances is the opt-in
`exulanica-wmp-ext-environment-instances` 1.0 extension. Unified Selection, Companion editing,
extraction, retained-database writes and real-scene visual validation remain outside the
implemented environment-instance scope. The existing reviewed CC0 asset registry and its byte
semantics are unchanged.


## Bounded scene-extraction preparation

`scripts/prepare_scene_extraction.py` prepares an object-segment candidate from an available
reconstruction and its pinned source masks. It retains source point indices, colors and provenance,
bounds the sampled input, and rechecks source availability before completing the artifact. Its PLY
uses the original scene units; it establishes neither metric scale nor a complete object's shape.
Person segments are outside this preparer's scope. The output is a candidate for review, not an
admitted render asset, collision shape or automatically placeable world object.

## Authored district object coordinates

`GET /world/versions/{version_id}/society/district` supplies the authorized region registration and
exact pinned district documents. The browser verifies the bytes, source availability, version and
frame before using the region-to-district translation. Authored objects have a separate display
root; the registration never moves reconstructed source geometry. New placement uses the district's
authored ground and bounds, with the existing confirmation and version compare-and-swap. Missing or
withdrawn registration clears that display frame and prevents pending placement from using it.

An authored object becomes a society target only through the reviewed composition adapter and one
of the existing `visit` or `rest` affordances. The typed society action API can request that a
synthetic inhabitant use the resulting canonical target, but it does not edit the object, add a
behavior, bypass clearance or grant source rights. The request and its eventual disposition are
simulation history; moving, removing or restoring the object remains authored-world history and
appends the corresponding society input.
