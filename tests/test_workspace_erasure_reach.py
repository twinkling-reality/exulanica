"""Every workspace table an erasure leaves in place, found by reading the migrations.

A table that carries ``workspace_id`` holds something of one workspace, and so of the people in
it. This reads the migrations the way ``tests/test_world_identity_inventory.py`` reads them for
``world_id`` and requires each such table to be one of two things: deleted from by a statement
inside a function the migrations define, or named in ``KEPT`` below with the reason its rows stay.
No database is needed.

The unresolved debt in ``KEPT`` may only shrink; new erasures may add their immutable records.
A workspace table with neither a delete nor an entry fails, and so does
an entry whose table has gained its delete or is no longer a workspace table, so the list is
always exactly what the schema holds. A new content table belongs in a function an erasure runs;
an entry for content here is a debt, not a decision that its rows may stay.

What this does not prove. A delete statement existing is not a trigger reaching it: the function
may be called by nothing, or only by an erasure narrower than a workspace's, and a delete with a
narrowing condition (one society's rows, one kind of comparison) counts for the whole table.
Text blanked in place is not counted: a table whose words an erasure sets to null while the row
stays is named in ``KEPT`` like any other, with what happens to it as its reason. A delete built
at run time from a table's name would not be seen, and neither would one issued by product code
rather than a migration, which is why ``embedding`` is listed. A table with no ``workspace_id``
column is outside this reading altogether, whatever it holds: the account tables keyed by user,
``blob`` and ``consent_record`` among them. The erasure tests that run against PostgreSQL are the
check that a tombstone removes rows; this is the check that no workspace table is forgotten.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Iterable

import pytest

import test_world_identity_inventory as world_inventory

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------------------------
# What remains, with why. Unresolved content debt may only shrink.
# ---------------------------------------------------------------------------------------------

#: The workspace's rows that belong to no one world.
_WORKSPACE = (
    "not reached yet: the workspace's own rows outside any one world, owed by a workspace erasure"
)
#: Who may enter a workspace, kept by the account plane rather than by anything made in it.
_ACCOUNT = (
    "not reached yet: the account's side of a workspace (who may enter it), which an account "
    "erasure or a workspace erasure would owe"
)
#: The door programs' documents, keyed by their digest in the workspace and shared by its grants.
_DOOR_DOCUMENT = (
    "not reached yet: a door program's document, keyed by its digest in the workspace and shared "
    "by its grants; a society erasure leaves it on purpose, so a workspace erasure owes it"
)
#: The purge worker destroys the stored object and keeps the row to say so.
_STUB = (
    "a stub row kept by the purge worker: a tombstone queues the stored object, the worker "
    "destroys it and sets purged_at, and the row stays to say the bytes are gone"
)
#: The spending ledger's rows for one workspace.
_MONEY = (
    "not reached yet: the spending ledger's rows for a workspace (figures, and who granted or "
    "revoked); whether an erasure takes a money ledger is not ruled"
)
#: One asset's withdrawal, which a restore replays.
_WITHDRAWAL = (
    "the record of one asset's withdrawal, naming who withdrew it; not reached yet at a workspace "
    "erasure"
)

#: Workspace tables no function in the migrations deletes from.
KEPT: dict[str, str] = {
    "kind_draft_start": (
        "draft/job and actor identifiers, start timing, guest/deadline policy, manifest digest "
        "and prompt version retained for recovery identity and shared hourly admission; no "
        "description or provider text; 0211 cancels linked jobs and deletes input, attempts "
        "and outcomes at workspace erasure"
    ),
    "world_draft_start": (
        "identifiers and actor/start timing retained for replay identity and hourly admission; "
        "no sentence, quote or content fingerprint; 0207 deletes all linked draft content"
    ),
    "world_draft_bound": "financial bound identifiers retained for closure after erasure",
    "world_draft_bound_closed": "financial closure markers retained after erasure",
    "account_browser_session": _ACCOUNT,
    "account_guest_entry": _ACCOUNT,
    "account_membership": _ACCOUNT,
    "account_workspace": _ACCOUNT,
    "artifact": _STUB,
    "assertion": (
        "changed in place: a tombstone retracts scene rung assertions only; every other row, "
        "with stated_by_user and object_value, stays"
    ),
    "capture": (
        "changed in place: a tombstone sets deleted_at and queues the bytes for the purge "
        "worker; the row and device_id stay"
    ),
    "capture_reconstruction_authorization": _WORKSPACE,
    "companion_answer": (
        "changed in place: a tombstone sets status withdrawn; question, answer_text, composed "
        "and actor_id stay"
    ),
    "companion_answer_citation": _WORKSPACE,
    "companion_answer_name": _WORKSPACE,
    "companion_escape": _WORKSPACE,
    "creature_draft": (
        "changed in place: a workspace tombstone cancels an unfinished draft; the row and "
        "owner_actor_id stay"
    ),
    "decoded_source": _WORKSPACE,
    "derivative_job_event": _WORKSPACE,
    "derived_artifact": (
        "changed in place by a person's withdrawal only (marked stale); nothing reaches it at a "
        "workspace erasure"
    ),
    "derived_environment_asset": _WORKSPACE,
    "dispute": _WORKSPACE,
    "door_declaration": _DOOR_DOCUMENT,
    "door_manifest": _DOOR_DOCUMENT,
    "door_mapping": _DOOR_DOCUMENT,
    "embedding": (
        "deleted by the purge worker in product code, not by a migration: a tombstone names its "
        "vectors and the worker deletes each row"
    ),
    "entity": (
        "changed in place by a person's withdrawal only (display_name set to null, deleted_at "
        "set); nothing reaches it at a workspace erasure"
    ),
    "entity_link": _WORKSPACE,
    "environment_feature_index_entry": _WORKSPACE,
    "environment_feature_index_publication": _WORKSPACE,
    "environment_source_admission": _WORKSPACE,
    "evidence_span": _WORKSPACE,
    "identity_event": _WORKSPACE,
    "identity_rejection": _WORKSPACE,
    "intake_batch": _WORKSPACE,
    "job": (
        "changed in place: a workspace tombstone cancels an unfinished creature draft's job and "
        "cuts its payload to the draft id; every other job's payload stays"
    ),
    "look_object": _STUB,
    "match_proposal": _WORKSPACE,
    "material_bake": (
        "changed in place: a tombstone cancels an unfinished bake and queues the baked bytes, "
        "which the purge worker destroys; requested_by and the receipt stay"
    ),
    "material_bake_quota": _WORKSPACE,
    "material_bake_request": _WORKSPACE,
    "material_recipe": _WORKSPACE,
    "material_recipe_source": _WORKSPACE,
    "material_recipe_withdrawal": _WITHDRAWAL,
    "never_same": _WORKSPACE,
    "occurrence": _WORKSPACE,
    "person_derivative_dependency": _WORKSPACE,
    "person_presentation_consent": _WORKSPACE,
    "person_region": _WORKSPACE,
    "person_subject": _WORKSPACE,
    "person_withdrawal_receipt": (
        "the erasure's own record: the receipt a person's withdrawal writes, naming the entity "
        "withdrawn; it stays at a workspace erasure"
    ),
    "personal_model_right": _WORKSPACE,
    "personal_model_right_use": (
        "retained consent evidence: the parent right's declared use, model identities, notice "
        "and digest stay with that immutable right; no image bytes or reference notes are held "
        "here. The parent right is not reached by workspace erasure, so its cascade does not "
        "remove this binding; workspace-level retention remains unresolved debt"
    ),
    "personal_request_receipt": _WORKSPACE,
    "piece_ask": _WORKSPACE,
    "piece_erasure_settlement": (
        "content-free erasure recovery: monetary obligations and GPU batch cancellation ids "
        "survive until recovered; completed receipts retain identities and amounts only"
    ),
    "piece_erasure_settlement_event": (
        "content-free recovery receipts: append-only GPU withdrawal, exact monetary decision "
        "and settlement survive backup restore without retaining erased request content"
    ),
    "pipeline_run": _WORKSPACE,
    "place": _WORKSPACE,
    "place_alignment": _WORKSPACE,
    "place_entity_bridge_decision": _WORKSPACE,
    "place_name_right_event": _WORKSPACE,
    "place_record": _WORKSPACE,
    "place_record_member": _WORKSPACE,
    "place_record_state_event": _WORKSPACE,
    "place_source_frame": _WORKSPACE,
    "place_version": _WORKSPACE,
    "point_map_model_right": _WORKSPACE,
    "purge_job": (
        "the erasure's own record: the purge work a tombstone queued, kept as the proof that it ran"
    ),
    "reconstruction_privacy_admission": _WORKSPACE,
    "reconstruction_privacy_admission_member": _WORKSPACE,
    "reconstruction_privacy_screening": _WORKSPACE,
    "reconstruction_scene": _WORKSPACE,
    "reconstruction_scene_build_member": _WORKSPACE,
    "reconstruction_scene_job": (
        "changed in place: a tombstone cancels a job whose member was deleted; the row stays"
    ),
    "reconstruction_scene_job_member": _WORKSPACE,
    "reconstruction_scene_member": _WORKSPACE,
    "reference_lookup": (
        "not reached by a tombstone: a retention function sets query to null thirty days after "
        "it was sent; the row stays"
    ),
    "reference_request": (
        "changed in place: a tombstone withdraws a complete or partial request and sets its "
        "bundle to null; steps and owner_actor_id stay"
    ),
    "retraction": (
        "written by a tombstone's rung retraction, and by people with retracted_by and reason; "
        "not reached yet at a workspace erasure"
    ),
    "route_permission_refusal": _WORKSPACE,
    "scene_training_artifact": _WORKSPACE,
    "scene_training_right": _WORKSPACE,
    "society_erasure": (
        "the erasure's own record: one row for each society erased, holding ids and no words; "
        "it outlives its world's registration"
    ),
    "spending_event": _MONEY,
    "spending_grant": _MONEY,
    "spending_grant_revocation": _MONEY,
    "spending_grant_state": _MONEY,
    "spending_reservation": _MONEY,
    "text_chunk": _WORKSPACE,
    "thing_erasure": (
        "the erasure's own record: one row for each creature erased, holding ids and no words"
    ),
    "tombstone": "the erasure's own record: the tombstone every deletion is traced to",
    "tombstone_embedding_target": (
        "the erasure's own record: the vectors a tombstone named for the purge worker to delete"
    ),
    "training_use_consent": _WORKSPACE,
    "user_annotation": _WORKSPACE,
    "web_picture_erasure": (
        "the erasure's own record: one row for each kept web picture erased, holding ids and its "
        "bytes' digest, and no address or words"
    ),
    "web_picture_object": _STUB,
    "world_version_tile_object": (
        "a stub row kept by the purge worker, naming the world whose version's tile it held: a "
        "tombstone queues the stored object, the worker destroys it and sets purged_at, and the "
        "row stays to say the bytes are gone"
    ),
    "world_kind_erasure": (
        "immutable erasure record: document/key fingerprints retire a version through restore, "
        "without retaining its document, labels or validation report"
    ),
    "world_erasure": (
        "the erasure's own record: identities and creation-budget figures carry world removal "
        "through restore without retaining its title, sentence or content digests"
    ),
    "workspace_asset": (
        "not reached yet as a row: a workspace tombstone purges its bytes through "
        "workspace_asset_blob; title, created_by and the declaration stay"
    ),
    "workspace_asset_blob": _STUB,
    "workspace_asset_withdrawal": _WITHDRAWAL,
    "workspace_baked_tile": _WORKSPACE,
    "workspace_preparation": (
        "changed in place: a workspace tombstone cancels an unfinished preparation; requested_by "
        "and the documents stay"
    ),
    "workspace_preparation_request": _WORKSPACE,
    "workspace_style_pack_attempt_day": _WORKSPACE,
    "workspace_style_pack_blob": _STUB,
    "workspace_style_pack_file": (
        "words blanked in place: a workspace tombstone sets path to null; the row stays"
    ),
    "workspace_style_pack_preparation": (
        "words blanked in place: a workspace tombstone cancels it and sets failure_message and "
        "report_document to null; the row stays"
    ),
    "workspace_style_pack_publish_request": (
        "words blanked in place: a workspace tombstone sets attribution and statement to null; "
        "requested_by stays"
    ),
    "workspace_style_pack_version": (
        "words blanked in place: a workspace tombstone sets the manifest, the declaration and "
        "the licence attribution to null; created_by stays"
    ),
    "workspace_style_pack_withdrawal": _WITHDRAWAL,
    "workspace_tile_quota": _WORKSPACE,
}

# ---------------------------------------------------------------------------------------------
# Reading the migrations
# ---------------------------------------------------------------------------------------------

_CREATE_TABLE = re.compile(r"create (?:unlogged )?table (?:if not exists )?([a-z_0-9]+)\s*\(")
_DROP_TABLE = re.compile(r"drop table (?:if exists )?([a-z_0-9]+)")
_RENAME_TABLE = re.compile(
    r"alter table (?:if exists )?(?:only )?([a-z_0-9]+)\s+rename to ([a-z_0-9]+)"
)
_FUNCTION = re.compile(r"create (?:or replace )?function\s+(?:[a-z_0-9]+\.)?([a-z_0-9]+)")
_DROP_FUNCTION = re.compile(r"drop function (?:if exists )?(?:[a-z_0-9]+\.)?([a-z_0-9]+)")
_DOLLAR_QUOTED = re.compile(r"(\$[a-z_]*\$)(.*?)\1", re.DOTALL)
_DELETE = re.compile(r"delete from (?:only )?(?:[a-z_0-9]+\.)?([a-z_0-9]+)")


def without_comments(sql: str) -> str:
    """The statements of one migration, as ``world_tables_from_migrations`` reads them."""
    return re.sub(r"--[^\n]*", "", sql)


def migrations() -> list[str]:
    """Every numbered migration in order, comments removed."""
    paths = sorted((ROOT / "exulanica" / "migrations").glob("[0-9]*.sql"))
    return [without_comments(path.read_text(encoding="utf-8")) for path in paths]


def tables_with(column: str, texts: Iterable[str]) -> frozenset[str]:
    """Tables the migrations leave standing that declare ``column``, at creation or by ALTER.

    A dropped table leaves the set and a renamed one stays under its new name. A temporary table
    is not a table of the schema and is not matched.
    """
    found: set[str] = set()
    for text in texts:
        events: list[tuple[int, str, tuple[str, ...]]] = []
        for match in _CREATE_TABLE.finditer(text):
            depth, index = 1, match.end()
            while depth and index < len(text):
                depth += {"(": 1, ")": -1}.get(text[index], 0)
                index += 1
            body = text[match.end() : index - 1]
            if re.search(rf"(^|,)\s*{column}\s+[a-z]", body, re.MULTILINE):
                events.append((match.start(), "add", (match.group(1),)))
        for match in re.finditer(
            rf"alter table (?:only )?([a-z_0-9]+)\s+add column (?:if not exists )?{column}\b", text
        ):
            events.append((match.start(), "add", (match.group(1),)))
        for match in _DROP_TABLE.finditer(text):
            events.append((match.start(), "drop", (match.group(1),)))
        for match in _RENAME_TABLE.finditer(text):
            events.append((match.start(), "rename", match.groups()))
        for _, kind, names in sorted(events):
            if kind == "add":
                found.add(names[0])
            elif names[0] in found:
                found.discard(names[0])
                if kind == "rename":
                    found.add(names[1])
    return frozenset(found)


def function_bodies(texts: Iterable[str]) -> dict[str, str]:
    """Each function's body as its latest definition gives it; a dropped function has none.

    A body is the dollar-quoted block that follows the function's name, so a ``do`` block, which
    follows no name, is not a function. Functions that share a name are read as one, the later
    replacing the earlier.
    """
    bodies: dict[str, str] = {}
    for text in texts:
        end = 0
        events: list[tuple[int, str, str | None]] = [
            (match.start(), match.group(1), None) for match in _DROP_FUNCTION.finditer(text)
        ]
        for block in _DOLLAR_QUOTED.finditer(text):
            heads = list(_FUNCTION.finditer(text, end, block.start()))
            if heads:
                events.append((heads[-1].start(), heads[-1].group(1), block.group(2)))
            end = block.end()
        for _, name, body in sorted(events, key=lambda event: event[0]):
            if body is None:
                bodies.pop(name, None)
            else:
                bodies[name] = body
    return bodies


def deleted_tables(texts: Iterable[str]) -> frozenset[str]:
    """Tables some function the migrations define deletes from."""
    found: set[str] = set()
    for body in function_bodies(texts).values():
        found.update(_DELETE.findall(body))
    return frozenset(found)


# ---------------------------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------------------------


def test_every_workspace_table_is_deleted_by_an_erasure_or_named_with_its_reason():
    texts = migrations()
    workspace = tables_with("workspace_id", texts)
    deleted = deleted_tables(texts)
    assert len(workspace) > 150, "the migrations answered almost nothing; the reading is wrong"
    assert len(workspace & deleted) > 30, "almost no delete was found; the reading is wrong"

    unnamed = sorted(workspace - deleted - set(KEPT))
    assert not unnamed, (
        "workspace tables no function deletes from and KEPT does not name; delete each in a "
        "function an erasure runs:\n" + "\n".join(unnamed)
    )
    gained = sorted(set(KEPT) & deleted)
    assert not gained, "KEPT tables that have gained a delete; remove the entries:\n" + "\n".join(
        gained
    )
    gone = sorted(set(KEPT) - workspace)
    assert not gone, "KEPT tables that are no longer workspace tables; remove the entries:\n" + (
        "\n".join(gone)
    )


def test_every_kept_table_says_why():
    for table, reason in KEPT.items():
        assert len(reason.split()) >= 4, f"{table} needs a reason, not {reason!r}"


def test_the_reading_is_the_one_the_world_inventory_uses():
    """The same tables for ``world_id`` as the reading this one is modelled on."""
    assert tables_with("world_id", migrations()) == world_inventory.world_tables_from_migrations()


# ---------------------------------------------------------------------------------------------
# Positive controls: the reading finds the shapes it exists to find
# ---------------------------------------------------------------------------------------------

_PLANTED = (
    """
    create table kept (workspace_id uuid not null, words text);
    create table erased (
      id uuid primary key default gen_random_uuid(),
      workspace_id uuid not null
    );
    create table shared (name text primary key);
    create unlogged table late (id uuid);
    create unlogged table quick (workspace_id uuid not null);
    create temporary table scratch (workspace_id uuid);
    create function tg_erases() returns trigger language plpgsql as $fn$
    begin
      -- delete from kept where workspace_id = new.workspace_id;
      delete from erased where workspace_id = new.workspace_id;
      return new;
    end $fn$;
    create function old_way() returns void language sql as $fn$ delete from kept $fn$;
    do $do$ begin delete from kept; end $do$;
    """,
    """
    alter table late add column workspace_id uuid;
    create or replace function old_way() returns void language sql as $fn$ select 1 $fn$;
    create function counts(out n integer) language sql as $fn$ select 1 $fn$;
    create function public.after_it() returns void language sql as $fn$
      delete from only public.late $fn$;
    """,
)


def _planted(*more: str) -> list[str]:
    return [without_comments(text) for text in (*_PLANTED, *more)]


def test_the_reading_finds_a_workspace_column_at_creation_and_by_alter():
    assert tables_with("workspace_id", _planted()) == {"kept", "erased", "late", "quick"}


def test_the_reading_finds_a_delete_only_inside_a_function_s_latest_definition():
    """Not in a comment, not in a ``do`` block, and not in a definition since replaced."""
    assert deleted_tables(_planted()) == {"erased", "late"}
    assert set(function_bodies(_planted())) == {"tg_erases", "old_way", "counts", "after_it"}


def test_a_dropped_function_deletes_nothing_and_a_dropped_table_is_no_table():
    after = _planted("drop function tg_erases(); drop table if exists late;")
    assert deleted_tables(after) == {"late"}
    assert tables_with("workspace_id", after) == {"kept", "erased", "quick"}


def test_a_renamed_table_is_read_under_its_new_name():
    after = _planted("alter table kept rename to held;")
    assert tables_with("workspace_id", after) == {"held", "erased", "late", "quick"}


def test_the_workspace_tables_are_the_schema_s(repository):
    """The migration reading above against the migrated schema's own list.

    A partition is left out, by the catalog's own flag: it is not a table the migrations create.
    ``embedding`` is partitioned by workspace, and each workspace that writes a vector gains a
    partition of its own, so a schema other tests have used holds one for each of theirs.
    """
    rows = repository.connection.execute(
        "select c.relname as table_name from pg_class c "
        "join pg_attribute a on a.attrelid=c.oid and a.attname='workspace_id' "
        "and a.attnum > 0 and not a.attisdropped "
        "where c.relnamespace=current_schema()::regnamespace "
        "and c.relkind in ('r','p') and not c.relispartition"
    ).fetchall()
    schema = frozenset(row["table_name"] for row in rows)
    assert "embedding" in schema, "the partitioned table itself is one the migrations create"
    assert len(schema) > 150, "the schema answered almost nothing; the query is wrong"
    assert tables_with("workspace_id", migrations()) == schema


@pytest.mark.parametrize("table", ["world_society", "look_version", "piece_batch"])
def test_the_tables_an_erasure_is_known_to_delete_are_found(table):
    """A society's, a creature's and a piece batch's rows, each from its own erasing function."""
    assert table in deleted_tables(migrations())
    assert table not in KEPT
