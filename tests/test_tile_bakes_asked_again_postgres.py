"""A generated town's tiles asked to be baked again
(``POST /world/versions/{version_id}/tiles/bakes``): a tile whose bake failed gets one bake
queued, and reads as baking; asked again while it waits, or once every tile is baked, nothing more
is queued; another workspace is answered as for a world it cannot see.

Against PostgreSQL as a deployment runs it, the tiles baked by the stand-in tessellator
``tests/test_generated_worlds.py`` bakes with. A token without ``world.write`` is refused by the
route sweep in ``tests/test_route_permissions.py``, as every declared route is.
"""

from __future__ import annotations

import contextlib
import dataclasses

import psycopg
import pytest
from exulanica.db.tiles_role import provision_tiles_role
from exulanica.ingest.generated_tiles import GeneratedTileBaker
from exulanica.store.configured import local_content_stores
from exulanica.world.generated_worlds import BAKE_JOB_KIND
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
