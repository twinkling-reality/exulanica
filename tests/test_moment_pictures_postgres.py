"""A world's History pictures, a moment's picture and a look's portrait, kept by the server
(0223), on PostgreSQL.

Put through the routes by the world's own workspace and served by their digest, kept once under
their name (a second answers the first), kept only for a moment the version records, refused for a
world that holds a photograph, out of another workspace's reach, gone with their moment when its
society is erased, and gone with their world. The rules without a database are
``test_moment_pictures.py``.
"""

from __future__ import annotations

import hashlib
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from exulanica.world.repository import WorldStyleRepository

import test_society_erasure_postgres as erasure
import test_society_stay_requests_api as stays
from style_pack_upload_support import jpeg
from test_saved_world_entries_api import _create_entry, _create_starter
from test_society_person_decisions_postgres import _services
from test_society_saved_world_api import OWNER, routes
from test_world_objects_api import ObjectsApi
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

MOMENT_RECIPE = "moment-framing/v1"
PORTRAIT_RECIPE = "portrait/v1"


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _put_moment(api: ObjectsApi, entry: dict, moment_id: uuid.UUID, data: bytes, **query):
    params = urlencode({"world_id": entry["world_id"], "recipe": MOMENT_RECIPE, **query})
    return api.client.put(
        f"/world/versions/{entry['authored_version_id']}/history/moments/{moment_id}/picture?{params}",
        headers={**api.headers, "Content-Type": "image/jpeg"},
        content=data,
    )


def _put_portrait(api: ObjectsApi, world_id: str, look: str, data: bytes):
    params = urlencode({"world_id": world_id, "look_sha256": look, "recipe": PORTRAIT_RECIPE})
    return api.client.put(
        f"/world/portraits?{params}",
        headers={**api.headers, "Content-Type": "image/jpeg"},
        content=data,
    )


def _said_moment(world, client) -> uuid.UUID:
    """A knight played by a person says a line beside another; its minute records a moment."""
    erasure._played_line(world, client, _services(client))
    society_id = erasure._society_id(world)
    connection = world["connection"]
    row = connection.execute(
        "select moment_id from world_society_moment where society_id = %s "
        "order by tick, moment_id limit 1",
        (society_id,),
    ).fetchone()
    connection.commit()
    assert row is not None, "the played line made a moment"
    return row["moment_id"]


def _pictures_of(connection, moment_id) -> int:
    row = connection.execute(
        "select count(*) as n from world_moment_picture where moment_id = %s", (moment_id,)
    ).fetchone()
    connection.commit()
    return row["n"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_moment_s_picture_is_kept_once_served_and_erased_with_its_society(app):
    world, client = app
    moment = _said_moment(world, client)
    scope, version, _ = routes(world)

    def put(data: bytes, recipe: str = MOMENT_RECIPE):
        return client.put(
            f"{version}/history/moments/{moment}/picture",
            params={**scope, "recipe": recipe},
            headers={**OWNER, "Content-Type": "image/jpeg"},
            content=data,
        )

    data = jpeg(600, 340)
    kept = put(data)
    assert kept.status_code == 200, kept.text
    digest = hashlib.sha256(data).hexdigest()
    assert kept.json() == {"sha256": digest, "width": 600, "height": 340}

    served = client.get(f"/world/pictures/{digest}", headers=OWNER, params=scope)
    assert served.status_code == 200 and served.content == data
    assert (
        served.headers["etag"] == f'"{digest}"' and "immutable" in served.headers["cache-control"]
    )
    missing = client.get(f"/world/pictures/{'0' * 64}", headers=OWNER, params=scope)
    assert missing.status_code == 404 and missing.json()["code"] == "picture_not_found"

    # Another page drew the same moment by the same recipe: refused, and told the one kept.
    again = put(jpeg(640, 360))
    assert again.status_code == 409 and again.json()["code"] == "picture_kept"
    assert again.json()["kept"]["sha256"] == digest
    # Another recipe is another name.
    assert put(jpeg(640, 360), recipe="moment-framing/v2").status_code == 200

    # The moment filed under another version of its world, one the world holds: as unknown as any.
    connection = world["connection"]
    with connection.transaction():
        style = WorldStyleRepository(connection, world["workspace"], world_id=world["world_id"])
        other = world["objects"].create_version(
            source_snapshot_id=world["binding"].source_snapshot_id,
            title="Another version",
            style_version_id=style.current().version_id,
            created_by=world["session"].actor,
        )
    misfiled = client.put(
        f"/world/versions/{other.version_id}/history/moments/{moment}/picture",
        params={**scope, "recipe": "moment-framing/v3"},
        headers={**OWNER, "Content-Type": "image/jpeg"},
        content=jpeg(640, 360),
    )
    assert misfiled.status_code == 404 and misfiled.json()["code"] == "unknown_reference"

    # A society's erasure deletes its moments, and each moment its pictures first (the moment's
    # own trigger): none of them stays for the world's erasure.
    assert _pictures_of(connection, moment) == 2, "both pictures are there before"
    erased = client.delete(version + "/society", headers=OWNER, params=scope)
    assert erased.status_code == 204, erased.text
    assert _pictures_of(connection, moment) == 0


def test_a_moment_of_a_version_the_world_does_not_hold_and_a_bad_recipe_are_refused(objects_api):
    entry = _create_starter(objects_api)
    stray = objects_api.client.put(
        f"/world/versions/{uuid.uuid4()}/history/moments/{uuid.uuid4()}/picture?"
        + urlencode({"world_id": entry["world_id"], "recipe": MOMENT_RECIPE}),
        headers={**objects_api.headers, "Content-Type": "image/jpeg"},
        content=jpeg(640, 360),
    )
    assert stray.status_code == 404 and stray.json()["code"] == "unknown_reference"
    # A moment the version does not record is as unknown as a version the world does not hold.
    unrecorded = _put_moment(objects_api, entry, uuid.uuid4(), jpeg(640, 360))
    assert unrecorded.status_code == 404 and unrecorded.json() == stray.json()
    recipe = _put_moment(objects_api, entry, uuid.uuid4(), jpeg(640, 360), recipe="Framing")
    assert recipe.status_code == 422 and recipe.json()["code"] == "picture_recipe"
    after = _put_moment(objects_api, entry, uuid.uuid4(), jpeg(640, 360) + b"after the end")
    assert after.status_code == 422 and after.json()["code"] == "picture_refused"


def test_a_look_s_portrait_is_kept_once_and_read_for_the_looks_asked(objects_api):
    entry = _create_starter(objects_api)
    world = entry["world_id"]
    look, other = hashlib.sha256(b"teo").hexdigest(), hashlib.sha256(b"ines").hexdigest()
    data = jpeg(256, 256)
    put = _put_portrait(objects_api, world, look, data)
    assert put.status_code == 200, put.text
    read = objects_api.get(f"/world/portraits?world_id={world}&looks={look},{other}")
    assert read.status_code == 200
    body = read.json()
    assert (
        body["profile"] == "exulanica.world-look-portraits/v1" and body["recipe"] == PORTRAIT_RECIPE
    )
    assert body["portraits"] == {
        look: {"sha256": hashlib.sha256(data).hexdigest(), "width": 256, "height": 256},
        other: None,
    }
    again = _put_portrait(objects_api, world, look, jpeg(256, 256))
    assert again.status_code == 409 and again.json()["code"] == "picture_kept"
    # A portrait is square.
    wide = _put_portrait(objects_api, world, other, jpeg(640, 360))
    assert wide.status_code == 422 and wide.json()["code"] == "picture_size"


def test_a_world_that_holds_a_photograph_is_given_no_history_pictures(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    moment = _put_moment(objects_api, entry, uuid.uuid4(), jpeg(640, 360))
    assert moment.status_code == 422 and moment.json()["code"] == "picture_of_photographs"
    portrait = _put_portrait(
        objects_api, entry["world_id"], hashlib.sha256(b"x").hexdigest(), jpeg(256, 256)
    )
    assert portrait.status_code == 422 and portrait.json()["code"] == "picture_of_photographs"


def test_another_workspace_neither_reads_nor_learns_of_them(objects_api):
    entry = _create_starter(objects_api)
    data = jpeg(256, 256)
    look = hashlib.sha256(b"teo").hexdigest()
    assert _put_portrait(objects_api, entry["world_id"], look, data).status_code == 200
    digest = hashlib.sha256(data).hexdigest()
    stranger = objects_api.stranger_get(f"/world/pictures/{digest}?world_id={entry['world_id']}")
    assert stranger.status_code == 404 and stranger.json()["code"] == "unknown_reference"
    invented = objects_api.stranger_get(f"/world/pictures/{digest}?world_id=nobody-s-world")
    assert invented.json() == stranger.json()
    portraits = objects_api.stranger_get(
        f"/world/portraits?world_id={entry['world_id']}&looks={'a' * 64}"
    )
    assert portraits.status_code == 404 and portraits.json() == stranger.json()


def test_they_go_with_their_world_and_nobody_else_deletes_them(objects_api, repository):
    entry = _create_starter(objects_api)
    look = hashlib.sha256(b"teo").hexdigest()
    assert _put_portrait(objects_api, entry["world_id"], look, jpeg(256, 256)).status_code == 200
    admin = repository.connection
    workspace = repository.workspace_id

    def counts() -> tuple[int, int]:
        return tuple(
            admin.execute(
                f"select count(*) as n from {table} where workspace_id = %s", (workspace,)
            ).fetchone()["n"]
            for table in ("world_moment_picture", "world_look_portrait")
        )

    # A moment's picture needs a recorded moment, which a starter has none of; a moment's picture
    # going with its moment is the test above, and with its world test_world_erasure_postgres.py.
    assert counts() == (0, 1)
    # The schema's owner, which row-level security does not bind, is refused by name.
    for table in ("world_look_portrait",):
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="erased whole"),
            admin.transaction(),
        ):
            admin.execute(f"delete from {table} where workspace_id = %s", (workspace,))
    # The world's erasure deletes its identity last, and the identity's trigger deletes them first.
    with admin.transaction():
        admin.execute("set local role exulanica_definer")
        admin.execute("select set_config('exulanica.workspace_id', %s, true)", (str(workspace),))
        admin.execute("select participation_erase(%s, %s)", (workspace, entry["world_id"]))
        admin.execute("select world_erase_rows(%s, %s)", (workspace, entry["world_id"]))
    assert counts() == (0, 0)
