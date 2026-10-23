"""A generated town's tiles asked to be baked again
(``POST /world/versions/{version_id}/tiles/bakes``): a tile whose bake failed gets one bake
queued, and reads as baking; asked again while it waits, or once every tile is baked, nothing more
is queued; another workspace is answered as for a world it cannot see. A tile whose latest job
ended failed beside a servable stored bake, which reads failed until a job of its own ends done,
is queued again too, a public tile and a version's changed tile alike. Two asks at once queue one
bake per tile: the world's bake queue is checked and changed under its own lock.

Against PostgreSQL as a deployment runs it, the tiles baked by the stand-in tessellator
``tests/test_generated_worlds.py`` bakes with. A token without ``world.write`` is refused by the
route sweep in ``tests/test_route_permissions.py``, as every declared route is.
"""

from __future__ import annotations

import contextlib
import dataclasses
import threading
import uuid

import psycopg
import pytest
from exulanica.db.tiles_role import provision_tiles_role
from exulanica.ingest.generated_tiles import GeneratedTileBaker
from exulanica.store.configured import local_content_stores
from exulanica.world import generated_worlds
from exulanica.world.generated_worlds import (
    BAKE_JOB_KIND,
    generation_receipt,
    queue_workspace_bakes,
    queue_world_bakes,
    town_records,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ElementOverride
from exulanica.world.town_parts import town_buildings
from exulanica.world.version_tiles import VERSION_BAKE_JOB_KIND
from psycopg.rows import dict_row

from conftest import scratch_role_database
from personal_world_support import STRANGER_TOKEN
from test_generated_worlds import _stub_tessellator
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TILES_ROLE = "exulanica_tiles_asked_again_suite"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


@pytest.fixture(name="town")
def _town(made, spine_schema, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A small town made through the API, its bakes queued and not yet baked, and its baker."""
    _psycopg, scratch = spine_schema
    api = made
    owner = api.repository.connection
    provision_tiles_role(owner, role=TILES_ROLE)
    owner.commit()
    stores = local_content_stores(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, tiles=stores.tiles, content_stores=stores
    )
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Asked again"})
    assert response.status_code == 201, response.text

    @contextlib.contextmanager
    def publisher():  # type: ignore[no-untyped-def]
        database = scratch_role_database(scratch, TILES_ROLE)
        with psycopg.connect(database.url, autocommit=True, row_factory=dict_row) as connection:
            yield connection

    baker = GeneratedTileBaker(
        session=api.database.session,
        publisher=publisher,
        store=stores.tiles,
        web_directory=_stub_tessellator(tmp_path, monkeypatch),
        worker="test",
        version_stores=stores.version_tiles,
    )
    return api, response.json(), baker


def _jobs(api, world_id: str) -> list[tuple[list[int], str]]:  # type: ignore[no-untyped-def]
    """Each bake job of the world, as its tile and state, oldest first, read as the owner."""
    connection = api.repository.connection
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select payload->'tile' as tile, state from job where kind = %s "
            "and payload->>'world_id' = %s order by created_at, job_id",
            (BAKE_JOB_KIND, world_id),
        ).fetchall()
    connection.commit()
    return [(list(row["tile"]), str(row["state"])) for row in rows]


def _fail_every_bake(api, world_id: str) -> None:  # type: ignore[no-untyped-def]
    """End the world's queued bakes failed, as a bake that raised is ended."""
    connection = api.repository.connection
    connection.execute(
        "update job set state = 'failed', last_error = 'a stand-in fault', completed_at = now() "
        "where kind = %s and payload->>'world_id' = %s and state = 'queued'",
        (BAKE_JOB_KIND, world_id),
    )
    connection.commit()


def _fail_latest(api, kind: str, world_id: str) -> int:  # type: ignore[no-untyped-def]
    """End each tile's latest bake job of ``kind`` failed, as a job that died after its first
    publish on its last claim is ended, its stored bake kept; how many were ended so."""
    connection = api.repository.connection
    ended = connection.execute(
        "update job set state = 'failed', last_error = 'a stand-in fault after publish' "
        "where job_id in (select distinct on (coalesce(payload->>'tile_inputs_digest', "
        "payload->>'tile')) job_id from job where kind = %s and payload->>'world_id' = %s "
        "order by coalesce(payload->>'tile_inputs_digest', payload->>'tile'), created_at desc, "
        "job_id desc)",
        (kind, world_id),
    ).rowcount
    connection.commit()
    return ended


def _ask(api, entry: dict, token: str | None = None):  # type: ignore[no-untyped-def]
    path = (
        f"/world/versions/{entry['authored_version_id']}/tiles/bakes?world_id={entry['world_id']}"
    )
    return api.post(path, {}) if token is None else api.post(path, {}, token=token)


def _states(api, entry: dict) -> list[str]:  # type: ignore[no-untyped-def]
    response = api.get(f"/world-entries/{entry['entry_id']}")
    assert response.status_code == 200, response.text
    return [tile["state"] for tile in response.json()["generated_ground"]["tiles"]]


def test_a_failed_bake_asked_again_is_queued_once_and_baked(town):
    api, entry, baker = town
    tiles = len(entry["generated_ground"]["tiles"])
    # The positive control: while its first bakes wait, asking queues nothing more.
    answer = _ask(api, entry)
    assert (answer.status_code, answer.json()) == (202, {"queued": 0})
    assert [state for _tile, state in _jobs(api, entry["world_id"])] == ["queued"] * tiles

    _fail_every_bake(api, entry["world_id"])
    assert set(_states(api, entry)) == {"failed"}
    answer = _ask(api, entry)
    assert (answer.status_code, answer.json()) == (202, {"queued": tiles})
    assert set(_states(api, entry)) == {"baking"}
    # Asked again while those wait: still one bake per tile.
    assert _ask(api, entry).json() == {"queued": 0}
    assert sorted(state for _tile, state in _jobs(api, entry["world_id"])) == (
        ["failed"] * tiles + ["queued"] * tiles
    )

    assert {outcome.status for outcome in baker.drain([api.repository.workspace_id])} == {"baked"}
    assert set(_states(api, entry)) == {"baked"}
    # Every tile baked: nothing is missing, so nothing is queued.
    assert _ask(api, entry).json() == {"queued": 0}


def test_another_workspace_is_answered_as_for_a_world_it_cannot_see(town):
    api, entry, _baker = town
    _fail_every_bake(api, entry["world_id"])
    foreign = _ask(api, entry, token=STRANGER_TOKEN)
    assert foreign.status_code == 404, foreign.text
    # Nothing was queued for the owner's world by the stranger's ask.
    assert "queued" not in {state for _tile, state in _jobs(api, entry["world_id"])}
    unknown = api.post(
        f"/world/versions/{entry['authored_version_id']}/tiles/bakes?world_id=world:generated:unknown",
        {},
    )
    assert unknown.status_code == 404, unknown.text


def test_a_world_no_recipe_composed_has_no_tiles_to_bake(made):
    starter = made.post("/world-entries/starter", {"title": "My world"})
    assert starter.status_code == 200, starter.text
    untiled = _ask(made, starter.json())
    assert (untiled.status_code, untiled.json()["code"]) == (404, "unknown_reference")


def test_a_tile_read_failed_beside_its_stored_bake_is_queued_again_and_reads_baked(town):
    api, entry, baker = town
    assert {outcome.status for outcome in baker.drain([api.repository.workspace_id])} == {"baked"}
    # The positive control: every tile baked and its job done, nothing is queued.
    assert _ask(api, entry).json() == {"queued": 0}
    tiles = _fail_latest(api, BAKE_JOB_KIND, entry["world_id"])
    assert tiles == len(entry["generated_ground"]["tiles"])
    assert set(_states(api, entry)) == {"failed"}
    assert _ask(api, entry).json() == {"queued": tiles}
    assert _ask(api, entry).json() == {"queued": 0}
    outcomes = baker.drain([api.repository.workspace_id])
    assert [outcome.status for outcome in outcomes] == ["baked"] * tiles
    assert set(_states(api, entry)) == {"baked"}


def test_a_changed_tile_read_failed_beside_its_stored_bake_is_queued_again(town):
    api, entry, baker = town
    workspace = api.repository.workspace_id
    assert {outcome.status for outcome in baker.drain([workspace])} == {"baked"}
    version = api.version(entry)
    snapshot = version["source_snapshot_id"]
    with api.database.session(workspace) as connection:
        generated = town_records(connection, workspace, entry["world_id"], snapshot)
        [building, *_rest] = [one.identity for one in town_buildings(generated.records)]
        WorldObjectRepository(connection, workspace, world_id=entry["world_id"]).set_part_change(
            version["version_id"],
            ElementOverride(f"part:{building}", suppressed=True),
            base_state_sha256=version["state_sha256"],
            actor=api.actor,
            part_ids=frozenset({building}),
        )
    # Removing a building alters a tile: asked, its changed tile is queued and baked.
    changed = _ask(api, entry).json()["queued"]
    assert changed >= 1
    assert {outcome.status for outcome in baker.drain([workspace])} == {"baked"}
    assert _ask(api, entry).json() == {"queued": 0}
    assert _fail_latest(api, VERSION_BAKE_JOB_KIND, entry["world_id"]) == changed
    assert "failed" in _states(api, entry)
    assert _ask(api, entry).json() == {"queued": changed}
    assert {outcome.status for outcome in baker.drain([workspace])} == {"baked"}
    assert set(_states(api, entry)) == {"baked"}


def test_two_asks_at_once_queue_each_failed_tile_once(town):
    api, entry, _baker = town
    tiles = len(entry["generated_ground"]["tiles"])
    _fail_every_bake(api, entry["world_id"])
    workspace = api.repository.workspace_id
    snapshot = uuid.UUID(api.version(entry)["source_snapshot_id"])
    holding, release = threading.Event(), threading.Event()
    first: list[int] = []

    def held() -> None:
        """An ask held between its check and its commit, as a concurrent one is."""
        with api.database.session(workspace) as connection, connection.transaction():
            scope = (connection, workspace, entry["world_id"], snapshot)
            digest, receipt = generation_receipt(*scope)
            first.append(len(queue_world_bakes(*scope, receipt, digest)))
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=held)
    thread.start()
    assert holding.wait(10)
    # The route is asked while the held ask holds the lock, and reads what it queued once it ends.
    threading.Timer(1.0, release.set).start()
    answer = _ask(api, entry)
    thread.join(10)
    assert first == [tiles]
    assert (answer.status_code, answer.json()) == (202, {"queued": 0})
    assert [state for _tile, state in _jobs(api, entry["world_id"])].count("queued") == tiles


def test_the_worker_look_over_and_an_ask_at_once_queue_each_failed_tile_once(town, monkeypatch):
    """The tile worker looks its workspace over on a session with no transaction of its own: held
    between reading a tile's stored bake and queueing it, an ask meanwhile still queues nothing."""
    api, entry, _baker = town
    tiles = len(entry["generated_ground"]["tiles"])
    _fail_every_bake(api, entry["world_id"])
    workspace = api.repository.workspace_id
    holding, release = threading.Event(), threading.Event()
    looking: dict[str, int] = {}
    read = generated_worlds.current_bake

    def held_read(connection, digest):  # type: ignore[no-untyped-def]
        if threading.get_ident() == looking.get("thread") and not holding.is_set():
            holding.set()
            release.wait(10)
        return read(connection, digest)

    monkeypatch.setattr(generated_worlds, "current_bake", held_read)
    looked: list[int] = []

    def look_over() -> None:
        looking["thread"] = threading.get_ident()
        with api.database.session(workspace) as connection:
            looked.append(len(queue_workspace_bakes(connection, workspace)))

    thread = threading.Thread(target=look_over)
    thread.start()
    assert holding.wait(10)
    threading.Timer(1.0, release.set).start()
    answer = _ask(api, entry)
    thread.join(10)
    assert looked == [tiles]
    assert (answer.status_code, answer.json()) == (202, {"queued": 0})
    assert [state for _tile, state in _jobs(api, entry["world_id"])].count("queued") == tiles
