# World project context

A world project keeps what one person chose to keep about their work in one world: goals,
preferences, open questions and tasks in their own words or in words they accepted, decisions that
name accepted records, and simulated events they want to come back to. This contract owns that
store: its identity and binding, what an item may say and where its words come from, how it is
read, shared, corrected and deleted, and the bounded context a reader may hand onward. The
[Companion](capabilities/companion.md) can resume a project from it; direct clients read and manage
all of it with no model.

The store holds what a person kept and the ids of records the world's authorities own. It copies
none of those records and is the authority for none of them: edits, appearance, controls and
simulated events stay with their owners ([world memory model](world-memory-model.md#project-projections-and-external-consumers)).

| Part | Where |
| --- | --- |
| Schema | [migration 0127](../exulanica/migrations/0127_a_world_project_keeps_what_its_person_chose.sql) |
| Repository, visibility, lifecycle | [`exulanica/world/project_context.py`](../exulanica/world/project_context.py) |
| Reference kinds and resolution | [`exulanica/world/project_context_references.py`](../exulanica/world/project_context_references.py) |
| Assembly rule | [`exulanica/world/project_context_assembly.py`](../exulanica/world/project_context_assembly.py) |
| Routes | [`exulanica/api/routes/world_projects.py`](../exulanica/api/routes/world_projects.py) |
| Independent client example | [`clients/python/exulanica_client/project_context.py`](../clients/python/exulanica_client/project_context.py) |

## Projects and their binding

A project belongs to the person who created it (the session's actor), is named by a title of 1 to
200 characters and is bound to one authored version of one world. A version id names a moving branch
head, so each binding also records the version's `state_sha256` and `edit_seq` at the moment it was
made; the binding history is append-only. A project read reports the version's state now and as it
was bound, whether the version's source was invalidated (`state: unavailable`,
`code: invalidated_source_version`) and, where the world has a saved entry, the version that entry
opens now. Rebinding to another version of the same world is an explicit write; the world of a
project never changes. Adding photographs to a personal world opens a new version for its saved
entry and leaves every project bound where it was, its bindings as recorded and every remembered
answer citing the version it read: the project's read then names both versions, and its owner
rebinds when they choose (`tests/test_project_context_personal_world.py`).

Every write carries the project's `revision`; a write with another revision is refused
`409 stale_project_context`, so of two clients writing from the same read, one succeeds and the
other reads again. Creating a project or an item accepts an `idempotency_key`: an exact retry is
answered with what the key made (200), also when it arrives while the first request is still
running, and the same key with another request is refused `409 idempotency_key_reused`. Renaming a
project clears its creation digest, which covered the old title, so its key no longer answers as
that request. A person keeps at most 50 live projects in one world.

## Items

| Kind | Basis | Words | Records named |
| --- | --- | --- | --- |
| `goal`, `preference`, `question`, `task` | `user_statement` or `inferred_suggestion` | required, 1 to 2000 characters | optional |
| `decision` | `recorded_outcome` | optional note | at least one accepted operation |
| `event` | `simulated_event` | optional note | at least one simulated event |

The basis keeps a person's own statement, a suggestion drawn by the Companion, an accepted outcome
and a simulated event apart; they do not borrow one another's truth status. A suggestion
(`inferred_suggestion`, origin `companion`) must name the person's own Companion answers it was
drawn from. It starts `proposed`, is never assembled into context, and becomes `active` only when
its owner accepts it; rejecting it erases it. A conversation is not permission to keep a profile:
no item is ever created from stored conversation by itself.

An item moves from `proposed` to `active`, from `active` to `resolved` (a goal, question or task
that is done) and from any of these to deleted. A correction is the item's next revision, filed as
the person's own words; the earlier revisions stay readable by the owner as the item's correction
history. Item text is refused when it carries a `[person X]`, `[place X]`, `[inhabitant X]` or
`[spot X]` placeholder, because an item keeps no map from a placeholder to anyone.

Bounds: 500 items per project that are not deleted, 50 revisions per item, 8 named records per
revision, 16 sources per item and 50 suggestions per project waiting for review. A refusal names the
bound (`project_item_limit_reached`, `item_revision_limit_reached`, `pending_suggestion_limit_reached`).

## Named records

Each named record is stored as the ids its authority keeps, under the names the Companion's action
receipts give the same ids, and is checked when written and resolved again at every read:
`available`, `unavailable` with the authority's code, `withdrawn`, `missing` or `mismatch`. A
reference names its `kind` and exactly the fields the table lists for it, each present, `null`
where the table allows it. A receipt says more (what an edit did and to which object, a proposal's
and a preview's status, an appearance revision), so a client keeping a receipt takes the listed
fields and nothing else; an applied appearance's `preview_id` comes from its plan's preview
receipt, or is `null`. An `operation` is a route key, such as
`POST /world/versions/{version_id}/compositions/apply`.

| Kind | Fields | Authority read at resolution |
| --- | --- | --- |
| `world_edit` | `operation`, `world_id`, `version_id`, `edit_id`, `edit_seq`, `result_state_sha256` | the version's edit history and its source's invalidation |
| `style_version` | `operation`, `world_id`, `style_version_id`, `preview_id` or `null`, `proposal_id` or `null` | the applied appearance version and its preview |
| `society_control` | `operation`, `world_id`, `version_id`, `revision`, `tick` and `state_sha256` (both for a step, both `null` for a configuration) | the society's control receipts |
| `society_event` | `world_id`, `version_id`, `event_id`, `tick`, and `input_seq`, `object_id`, `edit_seq`, `edit_id`, each or `null` (`edit_seq` and `edit_id` together) | the event and the society's current authorization of its input |
| `style_preview` | `world_id`, `preview_id` | the preview's state: open (unfinished work), applied, discarded, stale or expired |
| `companion_answer` | `answer_id` | the reader's own remembered answer |

A write refuses a record that does not exist as named (`404 unknown_reference`), disagrees with its
ids (`409 reference_mismatch`) or stands on an invalidated source (`409 invalidated_source_version`,
or `424 unavailable_society_input` for a simulated record). A write checks rows only; the
society's authorization of an input, which takes the workspace lock its own reads take, is applied
at read time. Each operation a reference may name is held to a declared write route by
`tests/test_project_context_assembly.py`.

## Visibility and sharing

Only a project's owner writes it. Row-level security separates workspaces; every statement also
names the reader, which is what separates people of one workspace. Another person of the workspace
reads a project only while its owner keeps a project share open, and an item only while it is
active or resolved and has its own open share. They read the current revision's words only: no
correction history or correction note, no proposals, no audit, and no record named in the owner's
private planes (a Companion answer); `hidden_references` counts those. A change asked by them is refused `403 not_project_owner`.
Stopping a share takes effect at the next read; a share is never reopened, so sharing again is a new
share. A suggestion waiting for review is not shared (`409 project_item_not_current`). An
unknown, foreign, deleted or not-visible project or item answers the same `404 unknown_reference`.

A person may copy their own accepted item from another of their projects, in any world of the
workspace, into a project (`reuse`); a copy into the project it comes from is refused
`422 invalid_project_context`. The copy takes the item's kind, words and records as they are
at that moment, records the item it was copied from, and is deleted with it; a later correction of
the source does not reach it. Another person's shared items are never copied, so stopping a share
leaves no copy behind.

## Context assembly

`GET /world/projects/{project_id}/context` returns the context a reader may hand onward,
assembled from current rows at every read, and the repository offers the same assembly in process
with an optional focus string that never travels in a URL. It holds the reader's visible active
items only. Items whose every required record is unavailable are left out. Order: items sharing more
words with the focus first, then goal, preference, task, question, decision, event, then the most
recently changed, then the item id. Budget: `max_entries` 1 to 64 (default 24) and `max_bytes`
1024 to 32768 (default 8192) of canonical JSON per entry; an entry that does not fit is left out
whole, never cut. Each entry carries its provenance (item, revision, kind, basis, origin, whether
the reader wrote it, when the words were recorded) and each named record with its state. The
response counts what was left out by reason (`over_budget`, `reference_unavailable`,
`pending_review`, `resolved`) and carries `assembly_sha256` over the project revision and each
entry's item and revision, which names no words.

Nothing is cached or summarized: no assembly, prompt or summary is stored, so a deleted item cannot
come back through one. A caller may keep item ids, revisions and the assembly digest, never text.
The assembly asks no model and reads no conversation transcript.

## Deletion, correction history and audit

Deleting an item, rejecting a suggestion, deleting a project, deleting the Companion answer or item
an item was drawn from, and a workspace tombstone each delete what they reach: every revision's
words, note and named records are cleared, the request digests that could confirm a guessed
sentence are cleared, a project's title is cleared, and shares close. Each cascade writes its
source's own instant and tombstone. A deletion is never refused for a stale revision. A workspace a
tombstone deleted as a whole takes no new project content: creating a project answers
`409 invalidated_source_version`, because the deletion invalidated every version's source; a write
to a deleted project answers `404 unknown_reference`; and the database's own guard refuses any
other path (`410 tombstoned`). A creation already running when the tombstone arrives is waited for
and deleted with the workspace.

What remains is the audit residue, served to the owner by `GET /world/projects/{project_id}/audit`
even after the project is deleted: the project's id, world, creation and deletion instants and
whether a tombstone deleted it; each binding's version and instant; each item's id, kind, status,
creation, review, resolution and deletion instants, deletion reason and each revision's basis,
origin and instant; each share's item, opening and closing instants. It holds no words, no named
records and no digest of words.

Clearing a value removes it from every read and from the row. Earlier row versions, write-ahead log
and backups taken before the deletion still hold the bytes until vacuum and backup rotation; a
restore re-applies every deletion its checkpoint carries (`project_context_share`,
`project_context_item` and `project_context_project` in the
[withdrawal catalog](../exulanica/deletion/withdrawals.v2.json), see
[ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md)), and a deletion made after the newest
withdrawal export is outside the window a declared recovery restores. The three kinds are replayed
in that order, each earliest first, ahead of Companion memory, so a later deletion's cascade finds
what an earlier one ended already ended: each row ends with the status, instant, reason and erasure
its deletion gave it. A row's `changed_at` and a project's revision are not replayed. A project or
item a tombstone deleted is deleted again by the replayed tombstone. No stronger erasure is
claimed.

## Policy and permission

What a person keeps can inform a proposal and can never author interaction policy, grant a
permission or change what a token may do. The project-context modules import no interaction-policy
type, no model client, no part of the Companion's asking path and no API module (an import contract
in `pyproject.toml`); no foreign key joins the project tables and the interaction-policy tables;
and a kept preference asking for more initiative leaves the policy plane unchanged
(`tests/test_project_context_policy_boundary.py`). Reads require `world.read`, writes
`world.write`, deleting an item or a project `deletion.write`.

## Operations

| Route | Permission | Does |
| --- | --- | --- |
| `GET /world/projects` | world.read | this world's projects the reader owns or that are shared with them, newest first |
| `POST /world/projects` | world.write | start a project bound to a version |
| `GET /world/projects/{project_id}` | world.read | one project, its binding and visible counts |
| `PUT /world/projects/{project_id}` | world.write | rename, or bind another version of the world |
| `DELETE /world/projects/{project_id}` | deletion.write | delete the project and everything in it |
| `GET /world/projects/{project_id}/audit` | world.read | the owner's non-content audit residue |
| `GET /world/projects/{project_id}/items` | world.read | visible items with their named records resolved |
| `POST /world/projects/{project_id}/items` | world.write | keep an item, a suggestion or a copy |
| `GET /world/projects/{project_id}/items/{item_id}/history` | world.read | the owner's correction history |
| `POST /world/projects/{project_id}/items/{item_id}/corrections` | world.write | correct an item |
| `POST /world/projects/{project_id}/items/{item_id}/review` | world.write | accept or reject a suggestion |
| `POST /world/projects/{project_id}/items/{item_id}/resolve` | world.write | close a goal, question or task |
| `DELETE /world/projects/{project_id}/items/{item_id}` | deletion.write | delete an item and its copies |
| `POST /world/projects/{project_id}/shares` | world.write | share the project or listed items |
| `DELETE /world/projects/{project_id}/shares/{share_id}` | world.write | stop one share |
| `GET /world/projects/{project_id}/context` | world.read | the bounded assembly |

Every route requires the `world_id` query parameter. Refusals are `{code, detail}` with the stable
code in `code`.

## Locking

A write takes the Companion answers it names `FOR SHARE` in id order, then its project
`FOR UPDATE`, then its items, and an item it copies `FOR SHARE` last. Deleting a Companion answer
locks its correction lineage in id order, and the cascade to the items drawn from those answers locks
their projects in id order before the items. A workspace tombstone updates answers before projects
and items, and holds the project plane's key that a creation holds shared. No path holds one of
these rows while taking the workspace advisory lock, which the structural plane's tombstone trigger
takes after them.

One kind of path does not take projects first: a deletion reaching copies of an item, which live in
other projects. Two such deletions coming at each other's projects can wait on each other; the
database ends one, and the write is tried again, up to three times, before it answers
`503 project_context_busy`. `tests/test_project_context_locking.py` stops a writer between its two
locks while a workspace tombstone or an answer deletion runs, and shows the same race deadlocks when
the cascade is planted without its project lock; `tests/test_project_context.py` holds the retry,
two requests under one idempotency key, and a creation racing its workspace's deletion.

## Not provided

Suggestions written by a model (the Companion's planner does not create them), placeholders and
saved names in item text, writing by several people to one project and membership changes (grants
are static per process), learned or embedding relevance, physical erasure of stored bytes, automatic
summaries, background activity and personality simulation are not part of this store. Whether a
project's context makes a model's answers more useful is unmeasured: that needs a held-out
evaluation with its own allocation.
