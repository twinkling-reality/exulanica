"""Every relation the runtime role may UPDATE is named here, with the reason it may.

Provisioning grants the writer select, insert and update on every table in the schema and takes
some back. A table a migration adds inherits that UPDATE without anyone deciding it should, and a
table where a rewrite is a hole looks no different from one where rewriting is the whole job:
``tombstone`` was the first kind until migration 0074, and nothing said so. So the set is read
from a database as provisioning leaves it, and each member must be declared below, either with the
runtime path that updates it or as a relation that keeps the grant with no runtime writer, which
is a candidate for revocation rather than a reason. The executor role may update nothing.

The second half holds the tombstone to its two walls: provisioning takes the runtime's UPDATE
away, and 0074 refuses every tombstone change but its purge completion, which only the purge role's
column grant or an administrator may record.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import (
    EXECUTOR_ROLE,
    INSERT_ONLY_TABLES,
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.ingest.repository import IngestRepository
from psycopg import sql

from conftest import scratch_role_database

#: Relations a runtime path updates, or locks with FOR UPDATE or FOR KEY SHARE, which needs UPDATE
#: too. A trigger runs as the role whose write fired it, so a trigger's update counts.
RUNTIME_UPDATES: dict[str, str] = {
    "artifact": "ingest flags an artifact for repair (ingest/spine/artifacts.py)",
    "assertion": "a retraction sets status, and supersession and withdrawal triggers do too",
    "blob": "importing purged bytes again makes the row live (ingest/spine/blobs.py upsert)",
    "capture": "a capture tombstone's trigger marks the capture deleted",
    "companion_answer": "answers are superseded and withdrawn, by the API and by a tombstone",
    "derived_artifact": "identity changes and person withdrawal mark derivatives stale",
    "derived_environment_asset": "withdrawal sets withdrawn_at (environment/repository.py)",
    "entity": "naming and merging, name and withdrawal triggers, and a bridge decision's lock",
    "entity_link": "a link's state changes (identity/links.py)",
    "environment_source_admission": "withdrawal sets withdrawn_at (environment/repository.py)",
    "identity_rejection": "a rejection is revoked and restored (identity/rejections.py)",
    "intake_batch": "a batch declares its size and closes (ingest/batch.py)",
    "job": "the derivative queue claims, renews, finishes and retries jobs",
    "person_subject": "a consent write locks its subject FOR KEY SHARE (api person consent)",
    "personal_model_right": "withdrawal, once; migration 0073 refuses every other change",
    "pipeline_run": "the ledger attaches, locks and closes runs; an event insert locks its run",
    "place": "a place bridge decision locks its place",
    "place_record": "a state event locks its record and applies to it",
    "reconstruction_scene": "a build becomes its scene's current job",
    "reconstruction_scene_job": "the scene queue claims, fails and retries; a tombstone cancels",
    "route_permission_refusal": "a repeated refusal is counted in place (api/permissions.py)",
    "stage_registry": "registering a stage moves its current version (stage_registry.py)",
    "workspace_tile_quota": "tile use is counted against the quota (api/quotas.py)",
    "world_alternate_environment_instance": "an instance moves and is removed",
    "world_alternate_object": "an object moves, changes and is removed",
    "world_alternate_version": "a version records its state digest and edit sequence, under a lock",
    "world_interaction_policy_preview": "a preview is applied, discarded or made stale",
    "world_interaction_policy_proposal": "a proposal is applied, discarded or made stale",
    "world_interaction_policy_state": "the current policy version moves, under a lock",
    "world_society": "a society advances its tick and state; request triggers lock it",
    "world_society_control": "playback leases, pauses and schedules; event triggers lock it",
    "world_structure_preview": "a preview is applied, discarded or made stale, under a lock",
    "world_structure_state": "the current snapshot moves, under a lock",
    "world_style_preview": "a preview is applied, discarded or made stale, under a lock",
    "world_style_proposal": "a proposal is applied, discarded or made stale",
    "world_style_state": "the current style version and topology digest move, under a lock",
}

#: Relations that hold UPDATE from the blanket grant, or from ``grant_workspace_partition`` for
#: ``embedding``, and that no runtime path updates or locks. Candidates for revocation, each to be
#: checked against its callers first; views are held to the check below instead.
WITHOUT_A_RUNTIME_UPDATER: frozenset[str] = frozenset(
    {
        "anchor_resolution",
        "artifact_current",
        "calibration",
        "capture_reconstruction_authorization",
        "clock_anchor",
        "companion_answer_citation",
        "companion_escape",
        "confirmed_place_entity_bridge",
        "consent_effective",
        "consent_record",
        "decoded_source",
        "derivative_job_event",
        "dispute",
        "embedding",
        "environment_feature_index_entry",
        "environment_feature_index_publication",
        "evidence_span",
        "identity_event",
        "match_proposal",
        "media_track",
        "never_same",
        "occurrence",
        "pending_match_proposal",
        "person_derivative_dependency",
        "person_presentation_consent",
        "person_region",
        "person_region_current",
        "person_withdrawal_receipt",
        "personal_request_receipt",
        "pipeline_event",
        "place_alignment",
        "place_entity_bridge_decision",
        "place_record_member",
        "place_record_state_event",
        "place_version",
        "purge_job",
        "reconstruction_privacy_admission",
        "reconstruction_privacy_admission_member",
        "reconstruction_privacy_screening",
        "reconstruction_scene_build_member",
        "reconstruction_scene_job_member",
        "reconstruction_scene_member",
        "retraction",
        "stage_definition",
        "text_chunk",
        "tombstone_embedding_target",
        "training_use_consent",
        "user_annotation",
        "world_alternate_element_override",
        "world_alternate_version_edit",
        "world_character_appearance_revision",
        "world_interaction_policy_audit_event",
        "world_interaction_policy_version",
        "world_package_export",
        "world_region_style_version",
        "world_reviewed_asset_import",
        "world_society_action_request",
        "world_society_control_event",
        "world_society_decision",
        "world_society_decision_request",
        "world_society_event",
        "world_society_input",
        "world_society_transition",
        "world_society_transition_action",
        "world_society_transition_decision",
        "world_structure_audit_event",
        "world_structure_dependency",
        "world_structure_element_identity",
        "world_structure_invalidation",
        "world_structure_placement_migration",
        "world_structure_snapshot",
        "world_structure_snapshot_element",
        "world_structure_snapshot_region",
        "world_style_audit_event",
        "world_style_version",
        "world_topology_contract",
        "world_topology_region",
        "world_topology_source",
    }
)

#: Holds UPDATE on purge_completed_at and INSERT, which is the runtime's shape, not the purger's.
_LOOKALIKE = f"{PURGE_ROLE}_update_grants_lookalike"
_PURGE = f"{PURGE_ROLE}_update_grants_suite"

_UPDATABLE = """
select distinct coalesce(pg_partition_root(c.oid), c.oid)::regclass::text as relation
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = current_schema() and c.relkind in ('r', 'p', 'v', 'm', 'f')
  and (has_table_privilege(%(role)s, c.oid, 'UPDATE')
       or exists (select 1 from pg_attribute a
                  where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
                    and has_column_privilege(%(role)s, c.oid, a.attnum, 'UPDATE')))
"""


def _updatable(connection, role: str) -> set[str]:
    rows = connection.execute(_UPDATABLE, {"role": role}).fetchall()
    return {row["relation"] for row in rows}


@pytest.fixture
def provisioned(repository):
    """The runtime and executor roles as provisioning leaves them, with an embedding partition."""
    connection = repository.connection
    provision_runtime_role(connection)
    provision_runtime_role(connection, role=EXECUTOR_ROLE, read_only=True)
    provision_workspace(connection, repository.workspace_id)
    return connection


def test_every_relation_the_runtime_may_update_is_declared(provisioned):
    declared = set(RUNTIME_UPDATES) | WITHOUT_A_RUNTIME_UPDATER
    assert not set(RUNTIME_UPDATES) & WITHOUT_A_RUNTIME_UPDATER
    assert all(reason.strip() for reason in RUNTIME_UPDATES.values())
    actual = _updatable(provisioned, RUNTIME_ROLE)
    assert actual - declared == set(), (
        "the runtime role may UPDATE these and nothing here says why; declare each with the path "
        "that updates it, or revoke the grant"
    )
    assert declared - actual == set(), "declared here but no longer updatable; remove them"
    assert not actual & set(INSERT_ONLY_TABLES)
    # The partition provisioning created is counted as its parent, so it was really looked at.
    assert (
        provisioned.execute(
            "select count(*) as n from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and c.relispartition "
            "and pg_partition_root(c.oid) = 'embedding'::regclass "
            "and has_table_privilege(%s, c.oid, 'UPDATE')",
            (RUNTIME_ROLE,),
        ).fetchone()["n"]
        == 1
    )


def test_the_executor_may_update_nothing(provisioned):
    assert _updatable(provisioned, EXECUTOR_ROLE) == set()


def test_no_view_the_runtime_may_update_writes_with_its_owners_rights(provisioned):
    """An updatable view writes its table as the view's owner unless it says otherwise."""
    rows = provisioned.execute(
        "select c.relname, pg_relation_is_updatable(c.oid, true) as events, "
        "coalesce('security_invoker=true' = any(c.reloptions), false) as invoker "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = current_schema() and c.relkind = 'v' "
        "and has_table_privilege(%s, c.oid, 'UPDATE')",
        (RUNTIME_ROLE,),
    ).fetchall()
    assert rows, "the check found no view to hold"
    for row in rows:
        assert row["relname"] in WITHOUT_A_RUNTIME_UPDATER
        assert row["events"] == 0 or row["invoker"], row["relname"]


# -- the tombstone ---------------------------------------------------------------------------------


def _tombstone(repository: IngestRepository) -> uuid.UUID:
    return repository.insert_tombstone(
        scope="assertion", assertion_id=uuid.uuid4(), requested_by=uuid.uuid4(), reason="test"
    )


def _row(connection, tombstone_id: uuid.UUID) -> dict:
    return dict(
        connection.execute(
            "select * from tombstone where tombstone_id=%s", (tombstone_id,)
        ).fetchone()
    )


REWRITES = (
    "effective_at = now() + interval '1 year'",
    "requested_by = gen_random_uuid()",
    "scope = 'workspace'",
    "assertion_id = gen_random_uuid()",
    "reason = 'something else'",
    "blocklist_hash = true",
)


def _grant(connection, statement: str, *names: str) -> None:
    connection.execute(sql.SQL(statement).format(*(sql.Identifier(name) for name in names)))


def _create_lookalike(connection) -> None:
    if connection.execute("select 1 from pg_roles where rolname=%s", (_LOOKALIKE,)).fetchone():
        return
    connection.execute(sql.SQL("create role {} nologin").format(sql.Identifier(_LOOKALIKE)))


def test_the_runtime_role_appends_tombstones_and_never_updates_one(
    provisioned, repository, spine_schema
):
    """Wall 1: the grant is gone, so the statement fails before any trigger runs."""
    _, scratch = spine_schema
    workspace = repository.workspace_id
    with scratch_role_database(scratch, RUNTIME_ROLE).session(workspace) as app:
        mine = _tombstone(IngestRepository(app, workspace))
        assert _row(app, mine)["purge_completed_at"] is None
        for change in ("purge_completed_at = now()", *REWRITES):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="tombstone"):
                app.execute(f"update tombstone set {change} where tombstone_id=%s", (mine,))


def test_reprovisioning_takes_back_an_update_granted_before(provisioned):
    _grant(provisioned, "grant update on tombstone to {}", RUNTIME_ROLE)
    assert "tombstone" in _updatable(provisioned, RUNTIME_ROLE)
    provision_runtime_role(provisioned)
    assert "tombstone" not in _updatable(provisioned, RUNTIME_ROLE)


def test_a_tombstone_is_written_once_whoever_holds_update(provisioned, repository, spine_schema):
    """Wall 2, for the owner, a runtime role provisioned before wall 1, and the purge role."""
    _, scratch = spine_schema
    workspace = repository.workspace_id
    owned = _tombstone(repository)
    before = _row(provisioned, owned)
    for change in REWRITES:
        with pytest.raises(psycopg.errors.CheckViolation, match="written once"):
            provisioned.execute(f"update tombstone set {change} where tombstone_id=%s", (owned,))
    assert _row(provisioned, owned) == before
    # The owner records and clears a completion, as a migration and an offline restore do.
    for value in ("now()", "null"):
        provisioned.execute(
            f"update tombstone set purge_completed_at={value} where tombstone_id=%s", (owned,)
        )

    # A runtime role that still holds the old full-table grant.
    _grant(provisioned, "grant update on tombstone to {}", RUNTIME_ROLE)
    with scratch_role_database(scratch, RUNTIME_ROLE).session(workspace) as app:
        for change in REWRITES:
            with pytest.raises(psycopg.errors.CheckViolation, match="written once"):
                app.execute(f"update tombstone set {change} where tombstone_id=%s", (owned,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="purge worker"):
            app.execute(
                "update tombstone set purge_completed_at=now() where tombstone_id=%s", (owned,)
            )
    provision_runtime_role(provisioned)

    # A role with the purger's column grant and the runtime's INSERT is not the purger.
    _create_lookalike(provisioned)
    _grant(provisioned, "grant usage on schema {} to {}", scratch, _LOOKALIKE)
    _grant(provisioned, "grant select, insert on tombstone to {}", _LOOKALIKE)
    _grant(provisioned, "grant update (purge_completed_at) on tombstone to {}", _LOOKALIKE)
    with (
        scratch_role_database(scratch, _LOOKALIKE).session(workspace) as other,
        pytest.raises(psycopg.errors.InsufficientPrivilege, match="purge worker"),
    ):
        other.execute(
            "update tombstone set purge_completed_at=now() where tombstone_id=%s", (owned,)
        )

    # The purge role: its column grant alone, which is how the trigger knows it.
    provision_purge_role(provisioned, role=_PURGE)
    with scratch_role_database(scratch, _PURGE).session(workspace) as purge:
        for change in REWRITES:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                purge.execute(f"update tombstone set {change} where tombstone_id=%s", (owned,))
        purge.execute(
            "update tombstone set purge_completed_at=now() where tombstone_id=%s", (owned,)
        )
    after = _row(provisioned, owned)
    assert after["purge_completed_at"] is not None
    assert {k: v for k, v in after.items() if k != "purge_completed_at"} == {
        k: v for k, v in before.items() if k != "purge_completed_at"
    }
