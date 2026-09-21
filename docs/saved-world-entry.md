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
`region:starter` region and the built-in `region.authored-ground` module version 1. The module is a
24 metre by 24 metre flat authored surface at elevation zero. Its body spawn is four metres from
the region origin. The element uses `evidence: {kind: none}`, the topology has no source slots or
dependencies, and the graph and reconstruction digests cover versioned documents that explicitly
state that there are no observed inputs. The module recipe and `builtin:` streaming key identify a
procedural renderer contract, not a capture, reconstruction, or generated asset.

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
uses `WorldObjectsClient.connect()` without a pinned version.

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

The authored floor uses the descriptor's exact horizontal bounds and elevation. Its perimeter
marks the supported walking area, and its surface receives object shadows and follows the saved
appearance palette. Photo-derived scene-segment controls are absent from source-independent
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
new sources without completed review or current viewer access is refused atomically.

Deleted sources, expired authorization or screening, and unavailable viewer bytes affect the
individual reference. They do not make the independently authored world unavailable. Unavailable
references retain lineage but return no viewer digest or evidence path. Genuine structural source
dependencies continue to use snapshot invalidation.

Migration `0086_saved_world_source_attachments.sql` stores one membership row per capture on an
entry (`unique (workspace_id, entry_id, capture_id)`). Operation and membership tables are
append-only: triggers refuse `UPDATE` and `DELETE`, and the application roles have `INSERT` and
`SELECT` only. Each membership pins the authorization and screening resolved at attach time.
Reads evaluate those pinned receipts. They do not select a later authorization or screening for
the same capture.

That stored uniqueness and append-only shape is the same provenance discipline
[world-objects-contract.md](world-objects-contract.md) uses for reviewed-asset import receipts:
an existing key's provenance cannot be rebound in place. Rebind is a later membership with a new
`operation_id` after a new human review, not an `UPDATE` of the first row. The 0086 unique names
every historical row, so a second membership for the same capture cannot be inserted while that
row exists. Detach-event rows and current-membership uniqueness are not in that migration.

| Event | What it is | What it is not |
| --- | --- | --- |
| Attach | A new `operation_id` plus membership rows that pin the current reviewed personal authorization and screening, while the authored cursor, style, snapshot, and undo history stay exactly as read | A topology write, a clone of a personal snapshot over the starter, geometry, or materialization of protected composition |
| Detach | A later unavailability event that names an existing membership so the reference is no longer part of the current collection | `DELETE` of the membership or operation row; hiding or substituting the independently authored world |
| Rebind | A later attach-shaped membership with a new `operation_id` after a new human review of the same capture | `UPDATE` of the prior row's `authorization_id` or `screening_id`; reuse of the prior `operation_id` with different receipts |
| Later authorization or screening receipt | Additional admission history on the capture | Reactivation of an expired membership; replacement of pinned lineage; an implicit rebind |
| Expired, deleted, or unreadable reference | Individual `source_attachments[]` unavailability with retained lineage | World `availability: unavailable`; snapshot invalidation |

`POST /world-entries/{entry_id}/source-attachments` is attach. It refuses a capture that already
has a membership row, including after that membership's pinned receipts expire and after a later
eligible receipt exists. Exact retry of the same `operation_id` and request body returns the
current entry. A different body on that `operation_id` is `source_attachment_operation_conflict`.

The public HTTP surface does not delete a membership row or patch pinned authorization or
screening. Detach and rebind are membership events. They are not public `DELETE` or `PATCH`
routes.

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

## Verification

`tests/test_saved_world_entries_api.py` executes exact reopen, cursor adoption races, atomic
authored and appearance advancement, transaction rollback, source invalidation, cross-world
reference refusal, and cross-workspace non-disclosure against PostgreSQL. Browser tests in
`web/packages/app/test/world-entry-api.test.ts`, `world-entry-surface.test.ts`,
`world-objects-api.test.ts`, and `world-style-api.test.ts` verify explicit recovery, bound writes,
creation, appearance save/reload, named-world propagation, and the absence of newest-version
inference.

Reference-attachment coverage includes atomic mixed-source refusal, exact retry and operation
identity conflicts, live authored-cursor drift, preserved object undo, authorization and screening
expiry, a later admission receipt that does not reactivate an expired membership, source deletion,
and unavailable viewer bytes. Browser component tests cover entry-scoped retry, same-scene
metadata refresh, response ordering, and explicit refusal of ineligible selections.

## Starter placement boundary

The browser constrains starter object placement and movement to the declared authored ground and
refuses to draw saved objects outside that supported area. The general authored-object API retains
its existing region ownership and transform validation; it does not enforce the starter ground's
finite horizontal bounds. This browser constraint is not a server-side spatial admission guarantee.
