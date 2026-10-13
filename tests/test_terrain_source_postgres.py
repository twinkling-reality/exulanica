"""Exact current terrain authority uses real saved versions and ordinary authored edits."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.errors import InvalidatedSourceVersion, StaleObjectBase, UnknownWorldResource
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.terrain_source import read_terrain_source

from test_heightfield_authoring import authoring
from test_society_made_world import PLATE
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _create(made):
    response = made.post(
        "/worlds/generated/terrain", {"title": "Contact authority", "authoring": authoring()}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _object():
    return AuthoredObject(
        "object:terrain-test",
        PLATE.content_sha256,
        "region:generated",
        Transform(1000, 1500, -1000, 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )


def test_empty_source_is_verified_and_object_removal_and_undo_stay_unavailable(made):
    entry = _create(made)
    version_id = uuid.UUID(entry["authored_version_id"])
    path = f"/world/versions/{version_id}/terrain-contact?world_id={entry['world_id']}"
    positive = made.get(path)
    assert positive.status_code == 200, positive.text
    assert positive.json()["status"] == "verified"
    assert positive.json()["profile"] == "exulanica.terrain-source-proof/v1"
    assert "no-store" in positive.headers["cache-control"].split(", ")
    with made.database.session(made.repository.workspace_id) as connection:
        repo = WorldObjectRepository(
            connection, made.repository.workspace_id, world_id=entry["world_id"], store=made.store
        )
        empty = read_terrain_source(repo, version_id)
        assert empty.status == "verified" and empty.reason is None
        assert empty.geometry_sha256 == authoring()["geometry_sha256"]
        assert empty.authored_state_sha256 == entry["authored_state_sha256"]
        assert empty.source_snapshot_id == entry["source_snapshot_id"]
        added = repo.add_object(
            version_id, _object(), base_state_sha256=empty.authored_state_sha256, actor=made.actor
        )
        changed = read_terrain_source(repo, version_id)
        assert (
            changed.status == "unavailable" and changed.reason == "authored_occupancy_unreconciled"
        )
        with pytest.raises(StaleObjectBase):
            read_terrain_source(repo, version_id, expected_state_sha256=empty.authored_state_sha256)
        removed = repo.remove_object(
            version_id, _object().object_id, base_state_sha256=added.state_sha256, actor=made.actor
        )
        assert read_terrain_source(repo, version_id).status == "unavailable"
        unremoved = repo.undo(version_id, base_state_sha256=removed.state_sha256, actor=made.actor)
        undone = repo.undo(version_id, base_state_sha256=unremoved.state_sha256, actor=made.actor)
        assert not undone.objects, "positive control: read-model delta omits undone additions"
        assert connection.execute(
            "select addition_undone from world_alternate_object where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (made.repository.workspace_id, entry["world_id"], version_id),
        ).fetchone()["addition_undone"]
        assert read_terrain_source(repo, version_id).status == "unavailable"
    unavailable = made.get(path)
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json()["reason"] == "authored_occupancy_unreconciled"
    stale = made.get(path + "&expected_state_sha256=" + added.state_sha256)
    assert stale.status_code == 409, stale.text


def test_foreign_or_invented_version_is_concealed_and_invalidated_source_refuses(made):
    entry = _create(made)
    version_id = uuid.UUID(entry["authored_version_id"])
    with made.database.session(made.repository.workspace_id) as connection:
        repo = WorldObjectRepository(
            connection, made.repository.workspace_id, world_id=entry["world_id"]
        )
        with pytest.raises(UnknownWorldResource):
            read_terrain_source(repo, uuid.uuid4())
    from personal_world_support import STRANGER_TOKEN

    path = f"/world/versions/{version_id}/terrain-contact?world_id={entry['world_id']}"
    assert made.get(path, token=STRANGER_TOKEN).status_code == 404
    foreign = uuid.uuid4()
    with made.database.session(foreign) as connection:
        repo = WorldObjectRepository(connection, foreign, world_id=entry["world_id"])
        # World scope denies before any private receipt is returned.
        with pytest.raises(UnknownWorldResource):
            read_terrain_source(repo, version_id)
    # Fixture construction records the same source invalidation consumed by every editor.
    admin = made.repository.connection
    tombstone = admin.execute(
        "insert into tombstone (workspace_id,scope,capture_id,requested_by,reason) "
        "values (%s,'capture',%s,%s,'test') returning tombstone_id",
        (made.repository.workspace_id, uuid.uuid4(), made.actor),
    ).fetchone()["tombstone_id"]
    admin.execute(
        "insert into world_structure_invalidation "
        "(workspace_id,world_id,snapshot_id,tombstone_id,reason) "
        "values (%s,%s,%s,%s,'test source withdrawn')",
        (
            made.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
            tombstone,
        ),
    )
    admin.commit()
    with made.database.session(made.repository.workspace_id) as connection:
        repo = WorldObjectRepository(
            connection, made.repository.workspace_id, world_id=entry["world_id"]
        )
        with pytest.raises(InvalidatedSourceVersion):
            read_terrain_source(repo, version_id)

    response = made.get(path)
    assert response.status_code == 409, response.text


def test_edit_during_source_read_cannot_return_verified_proof(made, monkeypatch):
    import exulanica.world.terrain_source as terrain_source

    entry = _create(made)
    version_id = uuid.UUID(entry["authored_version_id"])
    original = terrain_source._has_retained_delta

    def edit_after_occupancy_read(repository, requested_version):
        occupied = original(repository, requested_version)
        assert occupied is False
        # A separate committed ordinary writer races the read after its occupancy result.
        with made.database.session(made.repository.workspace_id) as writer_connection:
            writer = WorldObjectRepository(
                writer_connection,
                made.repository.workspace_id,
                world_id=entry["world_id"],
                store=made.store,
            )
            writer.add_object(
                version_id,
                _object(),
                base_state_sha256=entry["authored_state_sha256"],
                actor=made.actor,
            )
        return occupied

    monkeypatch.setattr(terrain_source, "_has_retained_delta", edit_after_occupancy_read)
    with made.database.session(made.repository.workspace_id) as connection:
        repository = WorldObjectRepository(
            connection, made.repository.workspace_id, world_id=entry["world_id"]
        )
        with pytest.raises(StaleObjectBase):
            read_terrain_source(repository, version_id)
