"""A visitor's workspace starts on an arrival world that is already baked.

A generated town's seed is drawn from its recipe and its identity, so a town made for a fresh
identity has tiles nobody has baked, and is drawn only after the tile worker's two bakes of each.
An arrival world names a fixed identity instead (``exulanica/world/arrival-worlds.v1.json``): every
workspace's copy is the same town, and a tile whose bake is already stored queues no job. The
installation bakes the arrival worlds once in its own workspace; every later copy reads baked at
once. The control is a town made for a fresh identity beside it, which still waits for its bakes.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.store.namespaces import tile_store
from exulanica.world.arrival_worlds import (
    ArrivalWorldsInvalid,
    load_arrival_worlds,
    make_arrival_world,
)
from exulanica.world.generated_worlds import BAKE_JOB_KIND, generated_tiles
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world_package.projector import project_world_package

from personal_world_support import STRANGER_TOKEN
from test_generated_worlds import _baker
from test_society_made_world import made as imported_made  # noqa: F401


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _copy(api, workspace: uuid.UUID, world):
    """``world`` made in ``workspace`` as the runtime role, with the tiles it reads and the bake
    jobs it queued."""
    with api.database.session(workspace) as connection:
        repository = SavedWorldEntryRepository(connection, workspace, api.store)
        entry = make_arrival_world(repository, world, created_by=uuid.uuid4())
        tiles = generated_tiles(connection, workspace, entry.world_id, entry.source_snapshot_id)
        jobs = connection.execute(
            "select count(*) n from job where workspace_id=%s and kind=%s "
            "and payload->>'world_id'=%s",
            (workspace, BAKE_JOB_KIND, entry.world_id),
        ).fetchone()["n"]
    return entry, tiles, jobs


@pytest.mark.postgres
def test_a_second_workspace_s_arrival_world_opens_baked_with_no_job(made, tmp_path, monkeypatch):
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    (world, *_) = load_arrival_worlds()
    installation = api.repository.workspace_id

    first, waiting, queued = _copy(api, installation, world)
    assert queued == len(waiting) > 0
    assert {tile.state for tile in waiting} == {"baking"}
    outcomes = _baker(api, store, tmp_path, monkeypatch).drain([installation])
    assert {outcome.status for outcome in outcomes} == {"baked"}

    visitor = uuid.uuid4()
    copy, tiles, jobs = _copy(api, visitor, world)
    assert copy.world_id == first.world_id == world.world_id
    assert jobs == 0
    assert {tile.state for tile in tiles} == {"baked"}
    with api.database.session(installation) as connection:
        baked = generated_tiles(connection, installation, first.world_id, first.source_snapshot_id)
    assert [tile.baked_tile_id for tile in tiles] == [tile.baked_tile_id for tile in baked]

    # The control: the same recipe for a fresh identity, in the same visitor's workspace, has
    # tiles nobody baked, and waits for them.
    with api.database.session(visitor) as connection:
        repository = SavedWorldEntryRepository(connection, visitor, api.store)
        fresh = repository.create_generated(
            title="Fresh", recipe_key=world.recipe, created_by=uuid.uuid4()
        )
        fresh_tiles = generated_tiles(connection, visitor, fresh.world_id, fresh.source_snapshot_id)
    assert {tile.state for tile in fresh_tiles} == {"baking"}

    # Asking again answers the copy the workspace already holds.
    again, _, _ = _copy(api, visitor, world)
    assert again.entry_id == copy.entry_id


@pytest.mark.postgres
def test_one_arrival_identity_in_two_workspaces_is_two_worlds_neither_can_see(
    made, tmp_path, monkeypatch
):
    """The same arrival world made in two workspaces: both are made; each workspace reads its own
    and is refused the other's exactly as it is refused something that does not exist; the tiles
    are shared, baked once, with no job for the second; and a package projected as the owner, for
    whom row-level security scopes nothing, carries its own workspace's world."""
    api = made
    store = tile_store(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(api.client.app.state.services, tiles=store)
    (world, *_) = load_arrival_worlds()
    owner = api.repository.workspace_id
    stranger = api.client.app.state.services.tokens.session_for(STRANGER_TOKEN).workspace_id
    # The stranger's copy first, so a lookup by identity alone would meet it before the owner's.
    theirs, _, _ = _copy(api, stranger, world)
    _baker(api, store, tmp_path, monkeypatch).drain([stranger])
    mine, tiles, jobs = _copy(api, owner, world)
    # (a) both are made, as two worlds of one identity.
    assert mine.world_id == theirs.world_id == world.world_id
    assert mine.entry_id != theirs.entry_id
    assert mine.source_snapshot_id != theirs.source_snapshot_id
    # (c) one bake serves both: no job for the second, the same stored tiles.
    assert jobs == 0 and {tile.state for tile in tiles} == {"baked"}
    # (b) each reads only its own, and is refused the other's as it is refused nothing at all.
    for token, own, other in ((None, mine, theirs), (STRANGER_TOKEN, theirs, mine)):
        kwargs = {"token": token} if token else {}
        listed = [entry["entry_id"] for entry in api.get("/world-entries", **kwargs).json()]
        assert str(own.entry_id) in listed and str(other.entry_id) not in listed
    # A version the other workspace holds reads as a version nobody holds.
    for token, other in ((None, theirs), (STRANGER_TOKEN, mine)):
        kwargs = {"token": token} if token else {}
        foreign = api.get(f"/world-entries/{other.entry_id}", **kwargs)
        absent = api.get(f"/world-entries/{uuid.uuid4()}", **kwargs)
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json()["code"] == absent.json()["code"]
        version = api.get(
            f"/world/versions/{other.authored_version_id}/society?world_id={world.world_id}",
            **kwargs,
        )
        nobody = api.get(
            f"/world/versions/{uuid.uuid4()}/society?world_id={world.world_id}", **kwargs
        )
        assert version.status_code == nobody.status_code
        assert version.json().get("code") == nobody.json().get("code")
    # The package of the owner's world, projected on the owner's connection, is the owner's.
    projected = project_world_package(
        api.repository.connection,
        workspace_id=owner,
        actor=uuid.uuid4(),
        output=tmp_path / "package",
        private_key=Ed25519PrivateKey.generate(),
        world_id=world.world_id,
    )
    assert projected.structure_snapshot_id == mine.source_snapshot_id


def _catalog(tmp_path, worlds) -> dict[str, str]:
    path = tmp_path / "arrival.json"
    path.write_text(json.dumps({"profile": "exulanica.arrival-worlds/v1", "worlds": worlds}))
    return {"EXULANICA_ARRIVAL_WORLDS": str(path)}


def test_the_shipped_catalog_loads_and_names_generated_identities():
    worlds = load_arrival_worlds({})
    assert worlds
    assert all(world.world_id.startswith("world:generated:") for world in worlds)


@pytest.mark.parametrize(
    ("worlds", "named"),
    [
        ([], "names no arrival world"),
        (
            [{"key": "a", "recipe": "small_town", "title": "A", "world_id": "world:authored:x"}],
            "is not world:generated:",
        ),
        (
            [
                {
                    "key": "a",
                    "recipe": "small_town",
                    "title": "A",
                    "world_id": "world:generated:8d8ea411-9010-446b-9699-dce63add6a2a",
                },
                {
                    "key": "a",
                    "recipe": "small_town",
                    "title": "B",
                    "world_id": "world:generated:11111111-1111-4111-8111-111111111111",
                },
            ],
            "repeats an arrival world's key",
        ),
    ],
)
def test_an_arrival_catalog_that_does_not_say_what_is_read_is_refused_by_name(
    tmp_path, worlds, named
):
    with pytest.raises(ArrivalWorldsInvalid, match=named):
        load_arrival_worlds(_catalog(tmp_path, worlds))
