# Saved world entry

A saved world entry is the workspace-owned pointer a person uses to reopen an owned world. It
names one world, one authored alternate branch with its saved digest/edit cursor, and one immutable
appearance version. It is not a
simulation save, a generated-world specification, or a replacement for either version authority.

## Stored authority

Migration `0083_saved_world_entries.sql` defines `saved_world_entry`:

```text
entry_id             stable workspace entry identity
workspace_id         row-level security boundary
world_id             the named world shared by both version references
title                the person's name for the entry
source_kind          personal or authored
authored_version_id  exact world_alternate_version
source snapshot      reached through the authored version, immutable structural authority
authored_state_sha256 saved branch-state concurrency digest
authored_edit_seq    saved branch edit cursor
style_version_id     exact world_style_version
revision             compare-and-swap token for entry updates
created_by, created_at, updated_at
```

Composite foreign keys require both referenced versions to belong to the entry's workspace and `world_id`.
The runtime cannot bind an authored version from one named world to a style from another. FORCE
row-level security makes an absent entry and another workspace's entry indistinguishable at the
API boundary.

An alternate version ID identifies a mutable authored branch head: object and environment edits
advance its `state_sha256` and `edit_seq` under the same ID. The entry stores both values. If the
branch advances without the entry's compare-and-swap update, reads return
`availability: unavailable` and `unavailable_reason: authored_version_changed`. The surface
compares the saved and current edit counts. Adoption requires an explicit acknowledgement and
submits the exact current digest/edit cursor returned by that read. If the branch moves again,
the adoption is refused instead of selecting the newer unseen state. This is reconciliation, not
historical replay, which the object authority does not provide.

An entry created from personal sources remains after deletion invalidates its authored version's
source snapshot. Reads return
`availability: unavailable` and `unavailable_reason: source_deleted`; the browser shows the
recorded entry and refuses to open it. Authored work remains recorded by its existing authority.

## Entry and creation

`GET /world-entries` is the entry catalog. A single available entry opens directly. More than one
entry produces a choice; none is selected by recency. An unavailable entry is visible and cannot
be substituted with another world.

Creation has one source-independent first-world path and two explicit personal-source paths:

1. `POST /world-entries/starter` creates an authored starter with no personal source dependency.
2. Choose an existing authored version and an appearance version from the same named world.
3. Choose **Create from current personal sources**, which calls the protected bootstrap with the
   reviewed topology digest, receives the exact authored version it opened, and saves that version
   together with the exact style version read before bootstrap.

The starter route takes the workspace structural lock and commits one immutable structural
snapshot, its matching default style, one authored alternate, and the saved entry in one
transaction. A successful retry with the same title returns the same entry. A different title,
an unavailable entry, or a personal entry conflicts rather than replacing or selecting it.
Renaming remains an explicit entry update.

The starter has its own `world:authored:<uuid>` identity. Its structural snapshot contains one
`region:starter` region and the built-in `region.authored-ground` module version 2. Its body spawn
is four metres from the region origin. The element uses `evidence: {kind: none}`, the topology has
no source slots or dependencies, and the graph and reconstruction digests cover versioned documents
that explicitly state that there are no observed inputs. The module recipe and `builtin:` streaming
key identify a procedural renderer contract, not a capture, reconstruction, or generated asset.

### The ground a starter states

The module states a ground, and a ground states a `kind`. There are two, and a snapshot carries
exactly the one its module version states:

| Module version | Streaming key | Ground | Extents |
| --- | --- | --- | --- |
| 1 | `builtin:region.authored-ground@1` | `kind: flat` | `half_width_mm` and `half_depth_mm`, both 12000 |
| 2 | `builtin:region.authored-ground@2` | `kind: endless` | none; the shape carries no extent field |

`flat` describes a surface whose perimeter is a real edge, which is what a place rebuilt from
photographs has. `endless` states a flat plane at the stated elevation with no perimeter at all. A
starter world is empty space to build in, so it has no edge to describe and version 2 states none:
a descriptor that named a size would be authoring a wall, and every world created under it would
keep that wall for as long as it existed.

The two versions are different stored bytes and both are read. A snapshot is matched against every
supported version rather than asked which version it claims, so a stored descriptor cannot select
its own validation, and a snapshot matching none of them is an error rather than a default. A world
created under version 1 keeps its 24 metre by 24 metre ground, keeps refusing placement outside it,
and is not migrated. Changing which version an existing world states would be a separate decision
about that world, not a consequence of the module gaining a version.

### How far an endless ground actually holds

No extent is stored, because the limit is not a property of the world. It is a property of the
renderer drawing it, and the browser binding states it as
`AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M`, currently **8192 metres**. It moves when the renderer
does, and no stored world changes when it does.

The number is measured, not chosen. A position reaches the GPU as a 32-bit float. The render origin
rebases only when the active neighborhood changes, neighborhoods are built from the scene's regions,
and a starter world's scene has none, so the whole walk is drawn at its true distance from the world
origin. The gap between one representable position and the next is then the float32 step at that
distance: 0.0019 mm at 24 metres, 0.061 mm at 1 kilometre, 0.49 mm at 8 kilometres, 0.98 mm at
8192 metres, and 1.95 mm at 16384 metres. 8192 metres is the farthest distance at which a drawn
position still resolves the millimetre, which is the unit every stored coordinate in this product
is written in.

Beyond it nothing is invented. The walking surface answers everywhere inside that radius, on a
circle so that no direction runs further than another, and answers nowhere outside it. Walking is
held inside the surface by two margins: the last 96 metres resist, as the resident field's soft
band does, and a step that would pass 8144 metres returns the person to where they last stood with
`recovery_reason: outside-field`. The refusal says the field ran out rather than that the ground
did, because on a ground that states it has no edge, running out of ground is the wrong account of
what happened. Every position movement can reach, including the compressed overshoot, is a position
the surface answers for.

`web/packages/atlas-react/test/endless-authored-ground.test.ts` measures all of it: the float32
step is read out of the bits rather than restated, the render origin is shown not to move in a
scene with no regions, and the walk is run through the world's own movement resolver one 23
millimetre frame at a time, from the origin to 8 kilometres, without a recovery.

### The spawn on a ground with no extents

The browser refuses a descriptor whose spawn is outside its own ground. On a bounded ground that is
the declared rectangle. An endless ground has no rectangle, so there is no containment left to
check, and the refusal moves rather than being deleted: the ground module version and the ground
kind are read as one fact, and a version 2 module carrying a `flat` ground, a version 1 module
carrying an `endless` one, or an endless ground carrying `half_width_mm` or `half_depth_mm` at all
are each refused as a descriptor this browser cannot read. Nothing is left that passes because it
has nothing to compare.

The development demonstration remains a separate, identified preview. It is never saved as an
owned entry. Opening an entry omits the bundled Flatiron demonstration district.

## Mutation and reopen

`PUT /world-entries/{entry_id}` carries `base_revision` and the exact authored digest/edit cursor
the caller observed. A revision or cursor mismatch returns `stale_saved_world_entry` and changes
nothing. The route never rereads a mutable authored branch and silently adopts whatever state is
newest at write time.

Authored object and environment requests may bind the active entry ID, observed entry revision,
and saved authored cursor. The server takes the workspace lock, validates that the mutation base
and actual branch digest/edit sequence both equal the saved cursor, records the authored edit,
verifies the exact returned digest/edit sequence, and advances the entry in one PostgreSQL
transaction. Comparing the edit sequence as well as the digest prevents an undo that repeats an
earlier digest from bypassing reconciliation. An absent, foreign, or stale binding rolls back the
authored edit. The browser does not resubmit an edit after an entry conflict; it says that the edit
was not recorded and requires a reload.

Bound authored writes, bound appearance writes, entry creation, and explicit cursor adoption take
the structural workspace advisory lock before any entry, authored-version, or style row lock. This
is the same lock order used by unbound object edits and source invalidation. A bound and unbound
writer therefore serialize without a row/advisory lock inversion, and deletion keeps its existing
shared serialization boundary.

Appearance apply and rollback requests use the same transaction pattern. The style authority
creates the immutable style version and advances the bound entry to that exact version before
commit. A pointer conflict therefore cannot leave a committed appearance reported as a failed
style write, and retry never resubmits an already committed style. A reload validates the saved
branch cursor and reconnects the saved style rather than selecting either authority by recency.

When a saved style is historical but another style is active on the world authority, appearance
edits are refused with an instruction to restore the visible saved appearance first. An explicit
rollback uses the live authority base to append that restoration; edits never apply to an unseen
newer appearance.

The browser passes `world_id` to style, source-media, bootstrap, object, and reviewed-object reads.
Source-media reads also carry the entry’s exact `source_snapshot_id`, preserving its source
context after the global topology pointer moves. Historical style display uses the selected
style’s topology while reconciliation and writes retain the live authority base.
Authored object composition receives `authored_version_id` explicitly. The entry surface never
uses `WorldObjectsClient.connect()` without a pinned version. Composition prepare and ready
apply also address that version through
`POST /world/versions/{version_id}/compositions/preview` and
`POST /world/versions/{version_id}/compositions/apply`. Apply may carry the same optional
`saved_entry` binding as authored object edits so the reopen cursor advances with the
mutation. Attachment membership, detach, and rebind remain separate from composition apply.

## Structural rendering boundary

The entry read exposes `source_snapshot_id` and `source_snapshot_sha256` from the immutable snapshot
named by its authored version. An authored starter also exposes `authored_scene`, a validated
projection of that exact snapshot's built-in module and placements. The projection contains the
region identity, authored origin, module key and version, bounded ground dimensions, elevation,
and body spawn. Missing or unsupported starter structure is an error; the server does not fill in
default geometry.

The browser mounts the authored descriptor as a first-class region and ground. It does not create
a graph island, capture, evidence card, or reconstructed surface for it. Personal entries return
`authored_scene: null`; their current graph and reconstruction limitations remain visible.

A bounded authored floor uses the descriptor's exact horizontal bounds and elevation, its
perimeter marks the supported walking area, and it receives object shadows. An endless ground
states no perimeter to draw, so it takes the world field's own continuous surface, which runs flat
and unbroken well past the distance the renderer supports. That surface receives no object shadows
and is drawn 35 millimetres below the authored elevation, so an object placed on an endless ground
casts no shadow onto it; giving that ground an appearance of its own is the world field's work and
is not done yet. Both surfaces follow the saved appearance palette. Photo-derived scene-segment controls are absent from source-independent
starters. In-world controls expose the World menu, object placement and photo review alongside
the editable title. When the starter's Companion has no substantive turn, it presents creation
guidance and the ordinary question control rather than an acknowledgement of an unstated exchange.
The arrival prompt provides a Start building button that opens this guidance without requiring
pointer lock. Opening photo review reads the workspace's authorized source inventory independently
of composed-world topology.

Personal source admission does not mutate or rebase a starter snapshot. Reference attachment
records the relationship described below. Attachment is not a topology write and does not compose
photographs into snapshots or style. `classify_structure_style_compatibility` is the closed
check on ATTACH: the call names the saved style, authored version, and source snapshot and
returns `attachment_membership_only`. It does not pass attachment identities, so it does not
classify sourced activation, historical write bases, or expired compose inputs. Attach
admission refuses expired sources before membership is written. Reviewed-source composition
into geometry is absent. Upload completion alone is never a topology write.

## Reference photographs

A saved world can retain reviewed personal photographs as project references. Attachment is an
explicit action after source admission and human review. It does not place a photograph in the
scene, reconstruct geometry, or change the starter's source-independent origin.

`POST /world-entries/{entry_id}/source-attachments` accepts an `operation_id`, `base_revision`,
`authored_version_id`, `authored_state_sha256`, `authored_edit_seq`, `style_version_id`, and between
1 and 200 unique `sources` containing `capture_id` and `evidence_span_id`. The server resolves the
exact original digest, current personal authorization and eligible human screening. The route
requires both `world.write` and `admission.read`.

The transaction compares the complete entry cursor and the live authored state, validates every
selected source, appends immutable operation and membership records, and increments only the
entry revision. An invalid member or stale cursor refuses the whole operation. An exact retry
with the same operation identity returns the current entry without adding membership or advancing
the revision again; reuse with different request content is a conflict.

Attachment preserves source snapshot identity and digest, authored version and edit sequence,
object state and undo history, protected topology, and saved style. It increments only the
entry revision and appends membership records. Entry reads include
`source_attachments` with their original lineage and current availability. The photo drawer
reopens this collection using authorized viewer bytes. Browser retry state is scoped to the
specific entry; a refresh may update reference metadata but cannot adopt a changed scene or style
under the existing canvas.

The photo drawer presents this world's reference collection and attachment status immediately.
Upload and human review remain in a separate expandable workflow. Already-attached selections
are identified as part of the world and do not offer duplicate attachment; a selection containing
new sources without completed review or current viewer access is refused atomically. Each
reviewed photograph that is ready and not yet in the world also has its own Add to this world
action, which attaches that one photograph without changing the review selection. Recorded
reviews are described per photograph in words; receipt identities stay inside a Details
disclosure.

Each reference card shows a plain status (in this world, or in this world but not viewable and
why) and a Remove from this world action behind a confirmation that says the photo stays in the
library and this world stops using it. Reference cards host no composition controls; composition
belongs to object placement. Removed photographs are listed under Previously in this world with
Add back. Until the drawer has seen a newer eligible review of that photograph, Add back opens
the review workflow with it selected and adds nothing; recording the review adds nothing either,
and the person chooses Add back again. The drawer's view of a review is a hint, not the rule:
the receipts it reads carry no time, so a review that predates the removal can still look newer
to it, and the server refuses that with `review_required`, which the drawer explains in the same
words and sends the person back to review. Refusals are shown in words mapped from the stable
codes below, with the code itself only inside Details. An interrupted remove or add back is kept
per world, and retry sends exactly the same request.

Deleted sources, expired authorization or screening, and unavailable viewer bytes affect the
individual reference. They do not make the independently authored world unavailable. Unavailable
references retain lineage but return no viewer digest or evidence path. Genuine structural source
dependencies continue to use snapshot invalidation.

Migration `0086_saved_world_source_attachments.sql` stores operation and membership rows.
Both tables are append-only: triggers refuse `UPDATE` and `DELETE`, and the application roles
have `INSERT` and `SELECT` only. Each membership pins the authorization and screening resolved
when it was written. Reads evaluate those pinned receipts. They do not select a later
authorization or screening for the same capture.

That append-only shape is the same provenance discipline
[world-objects-contract.md](world-objects-contract.md) uses for reviewed-asset import receipts:
an existing key's provenance cannot be rebound in place.

### Removing a reference and adding it back

A person can remove a reference photograph from one world and later add it back after a new
human review. The photograph stays in the library, its media and every history row remain, and
permission is never revived without that review. The history is also the input set a later
photo-to-world step reads to learn which photographs a world currently uses, so it has to hold
under retries, concurrent writers, the restricted runtime role, and the migration of existing
data.

| Event | What it is | What it is not |
| --- | --- | --- |
| Attach | A new `operation_id` plus membership rows that pin the current reviewed personal authorization and screening, while the authored cursor, style, snapshot, and undo history stay exactly as read | A topology write, a clone of a personal snapshot over the starter, geometry, or materialization of protected composition |
| Detach | A later event naming current memberships, after which those photographs are no longer part of the world | `DELETE` of any row; deletion of media; hiding or substituting the independently authored world |
| Rebind | A later attach-shaped membership row, with a new `operation_id`, pinning a human review of a removed photograph recorded after that removal | `UPDATE` of an earlier row's receipts; reuse of any receipt an earlier membership of that photograph on that world pinned; a review recorded while the photograph was still in the world |
| Later authorization or screening receipt | Additional admission history on the capture | Reactivation of an expired membership; replacement of pinned lineage; an implicit rebind |
| Expired, deleted, or unreadable reference | Individual `source_attachments[]` unavailability with retained lineage | World `availability: unavailable`; snapshot invalidation |

Migration `0090_saved_world_source_membership_events.sql` replaces 0086's all-history
`unique (workspace_id, entry_id, capture_id)` with `saved_world_source_current_membership`: one
row per world and photograph naming the attachment the world uses, or null after a detach. It
adds append-only `saved_world_source_detach_operation` and `saved_world_source_detach` tables and a
`kind` (`attach` or `rebind`) on attachment operations. Existing attachments are backfilled as
current.

The pointer is derived state and only the database moves it. Insert triggers on attachment and
detach rows, running with the table owner's rights, maintain it: an attach inserts it and is
refused if the photograph has any membership on that world; a rebind fills a null pointer and is
refused unless exactly one removed row changes; a detach clears the pointer only when it names
the attachment the pointer holds. A write to the pointer from anywhere else is refused by its own
trigger, and the runtime role holds `SELECT` on it and nothing more. No runtime statement can
therefore change which photographs a world uses without an event row that says so, and the
event rows are themselves checked against the saved-world cursor when the transaction commits.
Foreign keys on `(workspace_id, entry_id, capture_id, attachment_id)` tie the pointer and every
detach to an attachment of the same world and photograph.

A rebind pins the newest current human review of the photograph, and that review must answer the
removal: it is refused with `review_required` when its authorization or screening was recorded at
or before the latest detach of that photograph from that world, and when either receipt was
pinned by any earlier membership of the same photograph on the same world. The database refuses
both for every rebind row, so no writer reaches a membership the route would not.

Each half closes a measured gap. Comparing only the most recent membership let a third membership
pin the first membership's receipts once the second review expired. Requiring only receipts this
world had not used let a renewal recorded while the photograph was still a reference bring it
back, so the person made no decision after choosing to remove it, which is exactly what the
drawer says they do.

`POST /world-entries/{entry_id}/source-attachments` is attach. A photograph the world currently
uses is refused as `invalid_source_attachment`, including after its pinned receipts expire and
after a later eligible receipt exists. A photograph removed from the world is refused as
`rebind_required`: adding it back is a rebind. Exact retry of the same `operation_id` and request
body returns the current entry. The attach request digest is unchanged since 0086, so an
attachment recorded before 0090 retries as the same request.

`POST /world-entries/{entry_id}/source-detachments` accepts an `operation_id`, the entry cursor
the caller read (`base_revision`, `authored_version_id`, `authored_state_sha256`,
`authored_edit_seq`, `style_version_id`) and 1 to 200 `selections` naming current `attachment_id`s.
The cursor must equal the saved cursor. The live authored branch and the world's availability are
not consulted: a detach reads and writes no scene, style, or snapshot, so it cannot adopt unseen
state, and a world whose branch drifted or whose source was deleted can still stop using a
photograph. The pinned receipts are not consulted either. Removing an expired or deleted
reference is allowed, because a detach only reduces use. The route requires `world.write`; it
reads no admission receipt and answers with the same entry `GET` returns under `world.read`, so
`admission.read` would guard nothing there.

`POST /world-entries/{entry_id}/source-rebinds` accepts the same cursor and 1 to 200 `sources`
naming `capture_id` and `evidence_span_id`. It is attach-shaped: the complete cursor and the live
authored branch must match, the world must be available, the same structure and style check runs,
and the server resolves the receipts. It requires `world.write` and `admission.read`.

Every membership event takes the workspace lock before the entry row, as every other entry writer
does, and advances the entry revision exactly once without moving the authored cursor or style.
Two writers from the same resume point therefore serialize, and the second is refused as
`stale_saved_world_entry`. An `operation_id` names one request in one workspace across attach,
rebind, and detach, whichever world it was sent to. The recorded operation is looked up before
any cursor or authority check, so an exact retry returns the current entry after the world moved
on, after a newer review, and after the pinned review expired. The detach and rebind request
digests cover the client's body, cursor included, and the caller; they do not cover receipts the
server resolved. Reusing an identity for a different request, kind, or world is a 409:
`source_attachment_operation_conflict` on attach and `membership_event_operation_conflict` on
detach and rebind. The database refuses a duplicate identity across both operation tables too.

| Code | Status | Meaning |
| --- | --- | --- |
| `stale_saved_world_entry` | 409 | The world changed since the cursor was read |
| `membership_event_operation_conflict` | 409 | The `operation_id` already names a different request |
| `membership_unavailable` | 422 | Detach names an attachment the world does not use, or rebind names a photograph the world never used |
| `membership_current` | 422 | Rebind names a photograph the world still uses |
| `review_required` | 422 | The photograph's current review was already used by this world, or predates its removal; a new review is needed |
| `authority_unavailable` | 422 | No current human-reviewed personal authorization, or no authorized viewer bytes |
| `entry_unavailable` | 422 | Rebind on a world that cannot be opened |
| `invalid_detach`, `invalid_rebind` | 422 | A selection is repeated or outside 1 to 200 |
| `rebind_required` | 422 | Attach names a photograph removed from this world |

Entry reads return the current collection in `source_attachments` and the removed photographs in
`previous_source_attachments`: one row per photograph, its most recent membership lineage, the
detach that ended it, and whether the original photograph is still a live source
(`availability`, `unavailable_reason: source_unavailable`). A removed reference returns no
viewer digest or evidence path. `SavedWorldEntryRepository.membership_ledger` returns the complete
history: every membership with its kind, every detach, and every operation.

Rebind rows take the table's `uuidv7()` default like attach rows. Migration 0090 is forward-only.
After the first rebind two attachment rows name one photograph on one world, so 0086's constraint
cannot be restored over them; recovery is a restore from backup.

## HTTP surface

| Method | Route | Result |
| --- | --- | --- |
| `GET` | `/world-entries` | Workspace entry catalog with availability |
| `GET` | `/world-entries/candidates` | Unsaved authored versions and explicit style choices |
| `POST` | `/world-entries` | Save a personal authored branch cursor and exact style version |
| `POST` | `/world-entries/starter` | Atomically create or exactly reuse the source-independent authored starter |
| `GET` | `/world-entries/{entry_id}` | One entry, with cross-workspace IDs answered as absent |
| `PUT` | `/world-entries/{entry_id}` | Compare and advance the exact version references |
| `POST` | `/world-entries/{entry_id}/source-attachments` | Attach reviewed reference photographs while preserving the world cursor |
| `POST` | `/world-entries/{entry_id}/source-detachments` | Remove references from the current collection; no row or media is deleted |
| `POST` | `/world-entries/{entry_id}/source-rebinds` | Add removed references back under a new human review, as new membership rows |

## Verification

`tests/test_authored_starter_scene.py` pins the exact bytes each ground module version commits,
version 1's taken from the tree that created the worlds already holding it, and checks that a
snapshot written at either version reads back as that version's own ground, that an unsupported
version is refused, and that a snapshot the module did not write is refused at both versions.

`tests/test_saved_world_entries_api.py` executes exact reopen, cursor adoption races, atomic
authored and appearance advancement, refusal of a bound appearance edit while the saved style
is historical, rollback that restores that appearance onto the live authority, transaction
rollback, source invalidation, cross-world reference refusal, and cross-workspace
non-disclosure against PostgreSQL. Browser tests in
`web/packages/app/test/world-entry-api.test.ts`, `world-entry-surface.test.ts`,
`world-objects-api.test.ts`, and `world-style-api.test.ts` verify explicit recovery, bound writes,
creation, appearance save/reload, named-world propagation, and the absence of newest-version
inference. `world-entry-api.test.ts` also refuses every descriptor whose ground kind and ground
module version disagree, and every endless ground that declares an extent.
`web/packages/atlas-react/test/endless-authored-ground.test.ts` measures the walking surface, the
field an endless ground admits and the walk itself; `objects-surface.test.ts` covers placement and
drawing on both grounds, including that the object bound and the walking surface are one number.

Reference-attachment coverage includes atomic mixed-source refusal, exact retry and operation
identity conflicts, live authored-cursor drift, preserved object undo, authorization and screening
expiry, a later admission receipt that does not reactivate an expired membership, source deletion,
and unavailable viewer bytes. `tests/test_source_membership_events.py` runs detach and rebind
through an application connected as the runtime role: rows and media survive a detach; attach of
a removed photograph is `rebind_required`; a rebind without a new review, with receipts any
earlier membership pinned, or with a review recorded before the removal is refused, through the
route and again as a forged row the database rejects; a review recorded after the removal is
accepted; two detach and rebind cycles keep every event; expired and
deleted references can be removed; exact retries survive a cursor move, a newer review, and
expiry; operation identities are unique across kinds and worlds; concurrent writers from one resume
point serialize; another workspace's token sees and changes nothing; and direct runtime-role and
owner statements cannot move the pointer or forge an event that moves it the wrong way. The
stored pointer is compared with a replay of the events in each case.
`tests/test_saved_world_membership_backfill.py` migrates a schema to 0089, fills it through the
real repository, ingest and privacy receipts, applies 0090 as a superuser and as a table owner
without superuser or `BYPASSRLS`, and requires identical row counts, one pointer per attachment,
and identical `GET /world-entries/{entry_id}` bodies before and after, for available references
and for references whose authorization expired, whose review expired, and whose original
photograph was deleted. A 0090 made to fail mid-transaction leaves FORCE row-level security as it
found it. Browser component tests
cover entry-scoped retry, same-scene metadata refresh, response ordering, and explicit refusal of
ineligible selections. `web/packages/app/test/personal-intake.test.ts` also covers removal only
after confirmation, Add back through a new review with no automatic return, refusal words with
the code inside Details, exact retry of an unanswered change, adding one reviewed photograph
directly, and review receipts in words; `world-entry-api.test.ts` covers the detach and rebind
request bodies and the removed-reference parse.

## Starter placement boundary

The browser constrains starter object placement and movement to the ground the descriptor states,
and refuses to draw saved objects outside that supported area. On a bounded ground that is the
declared rectangle. On an endless ground it is the same radius the walking surface answers for, so
an object can never be saved somewhere a person could not stand: both read one constant. The
region's placement reach follows the same rule, and stays a finite number on an endless ground for
the same reason, so a refusal can still name a distance.

The general authored-object API retains its existing region ownership and transform validation; it
enforces neither bound. This browser constraint is not a server-side spatial admission guarantee.
