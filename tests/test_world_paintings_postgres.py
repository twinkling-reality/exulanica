"""A world's paintings (0226), on PostgreSQL: kept by the operator's painting run, read by the
world's readers.

Kept with what made them and served by their digest, the same bytes kept once, refused for a
world that holds a photograph, out of another workspace's reach, and gone with their world, which
nobody else can delete them before.
"""

from __future__ import annotations

import hashlib

import psycopg
import pytest
from exulanica.world.saved_entry_pictures import PictureRefused
from exulanica.world.world_paintings import WorldPaintingRepository

from style_pack_upload_support import jpeg
from test_saved_world_entries_api import _create_entry, _create_starter
from test_society_stay_requests_api import app  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres

PAINTER = {
    "models": [
        {"repository": "Tongyi-MAI/Z-Image", "revision": "04cc4abb7c50", "licence": "apache-2.0"},
        {
            "repository": "alibaba-pai/Z-Image-Fun-Controlnet-Union-2.1",
            "revision": "755999a93490",
            "licence": "apache-2.0",
        },
    ],
    "control": "depth",
    "steps": 25,
}


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _keep(repository, world_id: str, data: bytes, view: str = "first"):
    return WorldPaintingRepository(repository.connection, repository.workspace_id).keep(
        world_id,
        view=view,
        recipe="z-image-depth/v1",
        data=data,
        media_type="image/jpeg",
        camera={"fov_deg": 70, "camera_to_world_column_major": [1.0] * 16},
        words={"prompt": "a quiet harbour town at dusk", "seed": 11},
        painter=PAINTER,
        held_permille=930,
        cost_microusd=21000,
        run_id="graphics-p1",
    )


def test_a_painting_is_kept_by_the_run_and_read_with_what_made_it(objects_api, repository):
    entry = _create_starter(objects_api)
    world = entry["world_id"]
    data = jpeg(1280, 720)
    kept = _keep(repository, world, data)
    assert kept.sha256 == hashlib.sha256(data).hexdigest()
    assert (kept.width, kept.height) == (1280, 720)
    # The same bytes kept again are the one painting.
    assert _keep(repository, world, data).sha256 == kept.sha256
    read = objects_api.get(f"/world/paintings?world_id={world}")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["profile"] == "exulanica.world-paintings/v1"
    assert body["label"] == "invented appearance"
    [painting] = body["paintings"]
    assert painting["sha256"] == kept.sha256 and painting["view"] == "first"
    assert painting["painter"] == PAINTER and painting["held_permille"] == 930
    assert painting["label"] == "invented appearance"
    picture = objects_api.get(f"/world/paintings/{kept.sha256}?world_id={world}")
    assert picture.status_code == 200 and picture.content == data
    assert picture.headers["content-type"] == "image/jpeg"


def test_a_world_that_holds_a_photograph_is_given_no_painting(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    with pytest.raises(PictureRefused) as refused:
        _keep(repository, entry["world_id"], jpeg(640, 360))
    assert refused.value.code == "picture_of_photographs"


def test_another_workspace_neither_reads_nor_learns_of_them(objects_api, repository):
    entry = _create_starter(objects_api)
    world = entry["world_id"]
    kept = _keep(repository, world, jpeg(640, 360))
    stranger = objects_api.stranger_get(f"/world/paintings/{kept.sha256}?world_id={world}")
    assert stranger.status_code == 404 and stranger.json()["code"] == "unknown_reference"
    invented = objects_api.stranger_get(f"/world/paintings/{kept.sha256}?world_id=nobody-s-world")
    assert invented.json() == stranger.json()
    listed = objects_api.stranger_get(f"/world/paintings?world_id={world}")
    assert listed.status_code == 404 and listed.json() == stranger.json()
    # Under the routes, the rows themselves are the workspace's alone, for the table's owner too.
    forced = repository.connection.execute(
        "select relrowsecurity and relforcerowsecurity as forced from pg_class "
        "where oid = 'world_painting'::regclass"
    ).fetchone()["forced"]
    assert forced


def test_they_go_with_their_world_and_nobody_else_deletes_them(objects_api, repository):
    entry = _create_starter(objects_api)
    _keep(repository, entry["world_id"], jpeg(640, 360))
    admin = repository.connection
    workspace = repository.workspace_id

    def count() -> int:
        return admin.execute(
            "select count(*) as n from world_painting where workspace_id = %s", (workspace,)
        ).fetchone()["n"]

    assert count() == 1
    # The schema's owner, which row-level security does not bind, is refused by name.
    with pytest.raises(psycopg.errors.CheckViolation, match="erased whole"), admin.transaction():
        admin.execute("delete from world_painting where workspace_id = %s", (workspace,))
    # The world's erasure deletes its identity last, and the identity's trigger deletes them first.
    with admin.transaction():
        admin.execute("set local role exulanica_definer")
        admin.execute("select set_config('exulanica.workspace_id', %s, true)", (str(workspace),))
        admin.execute("select participation_erase(%s, %s)", (workspace, entry["world_id"]))
        admin.execute("select world_erase_rows(%s, %s)", (workspace, entry["world_id"]))
    assert count() == 0
