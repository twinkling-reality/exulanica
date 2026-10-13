"""Generated-world removal and restore retain no content or reusable creation allowance."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.world.errors import UnknownWorldResource, WorldRemoved
from exulanica.world.world_erasure import WorldErasureRefused, erase_world, removal_preview
from exulanica.world.worlds import (
    WORLD_COUNT_POLICY,
    refuse_past_limit,
    register_world,
    require_world,
)

from test_generated_worlds import _town
from test_purge import purged as purged
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _through_a_restore
from test_world_objects_api import objects_api as objects_api

pytestmark = pytest.mark.postgres


def test_removal_erases_content_cancels_jobs_and_keeps_budget(objects_api, repository):
    api = objects_api
    entry = _town(api, "Words gone with our world")
    workspace, world = repository.workspace_id, entry["world_id"]
    with api.client.app.state.services.database.session(workspace) as connection:
        held = require_world(connection, workspace, world)
        preview = removal_preview(connection, workspace, world, actor=held.created_by)
        assert preview["title"] == "Words gone with our world"
        assert preview["counts"]["saved_entries"] == 1
        erasure, entries, receipts = erase_world(
            connection, workspace, world, erased_by=held.created_by
        )
        assert str(entries[0]) == entry["entry_id"]
        assert receipts
        row = connection.execute(
            "select * from world_erasure where erasure_id=%s", (erasure,)
        ).fetchone()
        assert row["tiles"] > 0
        assert set(row) == {
            "workspace_id",
            "erasure_id",
            "world_id",
            "tombstone_id",
            "erased_by",
            "erased_at",
            "made_at",
            "tiles",
        }
        assert not connection.execute(
            "select 1 from saved_world_entry where world_id=%s", (world,)
        ).fetchall()
        assert not connection.execute(
            "select 1 from world_generation_receipt where world_id=%s", (world,)
        ).fetchall()
        assert {
            r["state"]
            for r in connection.execute(
                "select state from job where payload->>'world_id'=%s", (world,)
            )
        } == {"cancelled"}
        with pytest.raises(WorldRemoved):
            require_world(connection, workspace, world)
        with pytest.raises(WorldRemoved):
            register_world(
                connection,
                workspace,
                world_id=world,
                kind="generated",
                created_by=held.created_by,
                reason="retry",
            )
        policy = dataclasses.replace(
            WORLD_COUNT_POLICY,
            tiles_a_day={
                "kind": "generated",
                "limit": row["tiles"],
                "guest_limit": row["tiles"],
                "window_seconds": 86400,
            },
        )
        from exulanica.world.worlds import TileBudgetReached

        with pytest.raises(TileBudgetReached):
            refuse_past_limit(connection, workspace, "generated", policy=policy, tiles=1)
    with (
        api.client.app.state.services.database.session(uuid.uuid4()) as connection,
        pytest.raises(UnknownWorldResource),
    ):
        require_world(connection, uuid.uuid4(), world)


def test_other_actor_cannot_remove_world_and_owner_can(objects_api, repository):
    api = objects_api
    entry = _town(api, "Kept until authorized")
    workspace, world = repository.workspace_id, entry["world_id"]
    with api.client.app.state.services.database.session(workspace) as connection:
        with pytest.raises(WorldErasureRefused, match="creator"):
            erase_world(connection, workspace, world, erased_by=uuid.uuid4())
        assert require_world(connection, workspace, world)
        erase_world(connection, workspace, world, erased_by=uuid.uuid4(), by_owner=True)


def test_removed_world_cannot_return_from_backup(purged, commands, tmp_path):
    workspace, actor = purged.workspace_id, uuid.uuid4()
    world = f"world:generated:{uuid.uuid4()}"
    with purged.database().session(workspace) as connection:
        register_world(
            connection,
            workspace,
            world_id=world,
            kind="generated",
            created_by=actor,
            reason="restore fixture",
        )

    def held():
        return bool(
            purged.rows(
                "select 1 from world_identity where workspace_id=%s and world_id=%s",
                workspace,
                world,
            )
        )

    def remove():
        with purged.database().session(workspace) as connection:
            erase_world(connection, workspace, world, erased_by=actor)

    assert not _through_a_restore(purged, tmp_path, withdraw=remove, current=held)
    with purged.database().session(workspace) as connection, pytest.raises(WorldRemoved):
        register_world(
            connection,
            workspace,
            world_id=world,
            kind="generated",
            created_by=actor,
            reason="restored retry",
        )


def test_removal_is_carried_when_backup_predates_creation(purged, commands, tmp_path):
    from test_restore_replay import _backup, _restore
    from test_restore_replay_search_entries import _seal
    from test_restore_replay_withdrawals import _replay

    workspace, actor = purged.workspace_id, uuid.uuid4()
    world = f"world:generated:{uuid.uuid4()}"
    dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        register_world(
            connection,
            workspace,
            world_id=world,
            kind="generated",
            created_by=actor,
            reason="after backup",
        )
        erase_world(connection, workspace, world, erased_by=actor)
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    _replay(source, marker)
    with purged.database().session(workspace) as connection, pytest.raises(WorldRemoved):
        require_world(connection, workspace, world)


def test_routes_remove_only_generated_owned_world_and_read_410(objects_api, repository):
    api = objects_api
    entry = _town(api, "Remove this world")
    world = entry["world_id"]
    path = f"/worlds/{world}"
    assert api.get(path + "/removal").json()["title"] == "Remove this world"
    assert api.stranger_get(path + "/removal").status_code == 404
    assert api.client.delete(path).status_code == 401
    response = api.client.delete(path, headers=api.headers)
    assert response.status_code == 204, response.text
    assert api.get(path + "/removal").status_code == 410
    response = api.client.delete(path, headers=api.headers)
    assert response.status_code == 410, response.text
    assert api.get(api.in_world("/world/versions", world)).status_code == 410
    assert api.stranger_get(path + "/removal").status_code == 404
    # Existing photograph/starter worlds do not enter the generated-world deletion boundary.
    assert api.client.delete(f"/worlds/{api.world_id}", headers=api.headers).status_code in (
        403,
        409,
    )


def test_removal_runs_as_runtime_role_and_sealed_restore_preserves_world(
    objects_api, repository, spine_schema
):
    from exulanica.db.roles import provision_runtime_role

    from conftest import scratch_role_database
    from test_existence_oracle import _RUNTIME_ROLE

    api = objects_api
    entry = _town(api, "Runtime removal")
    workspace, world = repository.workspace_id, entry["world_id"]
    provision_runtime_role(repository.connection, role=_RUNTIME_ROLE)
    repository.connection.commit()
    database = scratch_role_database(spine_schema[1], _RUNTIME_ROLE)
    with database.session(workspace) as connection:
        erase_world(connection, workspace, world, erased_by=api.actor)
    # The seal refuses before the erasure's tombstone or record is written.
    entry = _town(api, "Sealed world")
    world = entry["world_id"]
    repository.connection.execute(
        "insert into restore_control (checkpoint_id,checkpoint_sha256,state) "
        "values (%s,%s,'sealed')",
        (uuid.uuid4(), "b" * 64),
    )
    repository.connection.commit()
    try:
        with database.session(workspace) as connection:
            with pytest.raises(WorldErasureRefused, match="sealed"):
                erase_world(connection, workspace, world, erased_by=api.actor)
            assert require_world(connection, workspace, world)
    finally:
        repository.connection.execute("delete from restore_control")
        repository.connection.commit()


def test_world_erasure_explains_missing_project_withdrawals_but_not_other_worlds(
    objects_api, repository
):
    from exulanica.deletion.withdrawals import Carried, stale_withdrawals
    from exulanica.world.project_context import ItemBasis, ItemKind, ProjectContextRepository

    api = objects_api
    entries = [_town(api, "Removed project world"), _town(api, "Unrelated project world")]
    connection, workspace = repository.connection, repository.workspace_id
    for entry in entries:
        projects = ProjectContextRepository(connection, workspace, api.actor, entry["world_id"])
        project, _ = projects.create_project(
            title="Notes", version_id=uuid.UUID(entry["authored_version_id"])
        )
        item, _created = projects.add_item(
            project.project_id,
            base_revision=project.revision,
            kind=ItemKind.GOAL,
            basis=ItemBasis.USER_STATEMENT,
            text="Keep private words",
            idempotency_key=uuid.uuid4(),
        )
        projects.share(
            project.project_id,
            base_revision=projects.project(project.project_id).revision,
            project=True,
            item_ids=[item.item_id],
        )
        projects.delete_project(project.project_id)
    carried = [
        Carried(
            "world_erasure", {"workspace_id": str(workspace), "world_id": entries[0]["world_id"]}
        )
    ]
    kinds = {"project_context_project", "project_context_item", "project_context_share"}
    before = [(kind, row) for kind, row in stale_withdrawals(connection, []) if kind in kinds]
    after = [(kind, row) for kind, row in stale_withdrawals(connection, carried) if kind in kinds]
    assert {kind for kind, _ in before} == kinds
    assert len(before) == 2 * len(after)
    assert {kind for kind, _ in after} == kinds


def test_open_generation_blocks_removal_without_losing_request(objects_api, repository):
    from exulanica.generation import store
    from exulanica.generation.requests import (
        GPU_PROVIDER,
        LookReference,
        generation_catalogs,
        plan_requests,
    )
    from exulanica.world.style_pack_library import style_pack_library

    api = objects_api
    entry = _town(api, "Pending generation")
    connection, workspace = repository.connection, repository.workspace_id
    library = style_pack_library()
    pack = library.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=library)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    store.create_piece_requests(
        connection,
        workspace,
        requested_by=api.actor,
        world_id=entry["world_id"],
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(planned[0].variants)],
    )
    connection.commit()
    response = api.client.delete(f"/worlds/{entry['world_id']}", headers=api.headers)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "generation_pending"
    assert require_world(connection, workspace, entry["world_id"])
    assert connection.execute(
        "select 1 from piece_request where world_id=%s", (entry["world_id"],)
    ).fetchone()


def test_record_cannot_forge_budget_or_resurrect_removed_registration(objects_api, repository):
    import psycopg

    api = objects_api
    entry = _town(api, "Record binding")
    workspace, world = repository.workspace_id, entry["world_id"]
    with api.client.app.state.services.database.session(workspace) as connection:
        held = require_world(connection, workspace, world)
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="budget"),
            connection.transaction(),
        ):
            tombstone = connection.execute(
                "insert into tombstone (workspace_id,scope,requested_by,reason) "
                "values (%s,'world',%s,'test') returning tombstone_id",
                (workspace, api.actor),
            ).fetchone()["tombstone_id"]
            connection.execute(
                "insert into world_erasure "
                "(workspace_id,world_id,tombstone_id,erased_by,made_at,tiles) "
                "values (%s,%s,%s,%s,%s,0)",
                (workspace, world, tombstone, api.actor, held.created_at),
            )
        assert require_world(connection, workspace, world)
        assert not connection.execute(
            "select 1 from world_erasure where world_id=%s", (world,)
        ).fetchone()
        erase_world(connection, workspace, world, erased_by=api.actor)
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="removed world"),
            connection.transaction(),
        ):
            connection.execute(
                "insert into world_identity (workspace_id,world_id,kind,provenance,created_by) "
                "values (%s,%s,'generated','{}',%s)",
                (workspace, world, api.actor),
            )
