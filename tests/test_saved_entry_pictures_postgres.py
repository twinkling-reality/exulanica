"""A saved world's picture, kept by the server and served with its entry (0218), on PostgreSQL.

Put through the route by the world's own workspace, served with the entry and by its digest, held
to what the world is now, refused for a world that holds a photograph, out of another workspace's
reach, and gone with its entry. The rules without a database are ``test_saved_entry_pictures.py``.
"""

from __future__ import annotations

import hashlib
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from psycopg import sql

from style_pack_upload_support import jpeg
from test_saved_world_entries_api import _create_entry, _create_starter
from test_world_objects_api import ObjectsApi
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _shows(entry: dict) -> dict[str, str]:
    """What a picture of ``entry`` as it is now shows."""
    return {
        "authored_version_id": entry["authored_version_id"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "style_version_id": entry["style_version_id"],
    }


def _put(api: ObjectsApi, entry: dict, data: bytes, shows: dict[str, str] | None = None):
    query = urlencode(shows or _shows(entry))
    return api.client.put(
        f"/world-entries/{entry['entry_id']}/picture?{query}",
        headers={**api.headers, "Content-Type": "image/jpeg"},
        content=data,
    )


def test_a_picture_put_by_the_world_s_workspace_is_served_with_its_entry_and_by_its_digest(
    objects_api,
):
    entry = _create_starter(objects_api)
    data = jpeg(640, 360)
    put = _put(objects_api, entry, data)
    assert put.status_code == 200, put.text
    digest = hashlib.sha256(data).hexdigest()
    assert put.json()["sha256"] == digest and put.json()["current"] is True

    served = objects_api.get(f"/world-entries/{entry['entry_id']}").json()["picture"]
    assert served["sha256"] == digest and (served["width"], served["height"]) == (640, 360)
    assert served["current"] is True
    listed = {one["entry_id"]: one for one in objects_api.get("/world-entries").json()}
    assert listed[entry["entry_id"]]["picture"]["sha256"] == digest

    picture = objects_api.get(f"/world-entries/{entry['entry_id']}/picture?sha256={digest}")
    assert picture.status_code == 200 and picture.content == data
    assert picture.headers["content-type"] == "image/jpeg"
    assert picture.headers["etag"] == f'"{digest}"'
    assert "immutable" in picture.headers["cache-control"]
    other = objects_api.get(f"/world-entries/{entry['entry_id']}/picture?sha256={'0' * 64}")
    assert other.status_code == 404 and other.json()["code"] == "picture_not_found"


def test_a_new_picture_replaces_the_old_and_one_of_the_world_as_it_was_is_refused(objects_api):
    entry = _create_starter(objects_api)
    first, second = jpeg(640, 360), jpeg(1280, 720)
    assert _put(objects_api, entry, first).status_code == 200
    assert _put(objects_api, entry, second).status_code == 200
    served = objects_api.get(f"/world-entries/{entry['entry_id']}").json()["picture"]
    assert served["sha256"] == hashlib.sha256(second).hexdigest()
    gone = hashlib.sha256(first).hexdigest()
    assert (
        objects_api.get(f"/world-entries/{entry['entry_id']}/picture?sha256={gone}").status_code
        == 404
    )

    stale = {**_shows(entry), "authored_state_sha256": "f" * 64}
    refused = _put(objects_api, entry, jpeg(640, 360), stale)
    assert refused.status_code == 409 and refused.json()["code"] == "picture_not_current"
    # The refused picture replaced nothing.
    still = objects_api.get(f"/world-entries/{entry['entry_id']}").json()["picture"]
    assert still["sha256"] == hashlib.sha256(second).hexdigest()


def test_a_world_that_holds_a_photograph_is_refused_a_picture(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    refused = _put(objects_api, entry, jpeg(640, 360))
    assert refused.status_code == 422 and refused.json()["code"] == "picture_of_photographs"
    assert objects_api.get(f"/world-entries/{entry['entry_id']}").json()["picture"] is None


def test_a_refused_body_is_said_by_name(objects_api):
    entry = _create_starter(objects_api)
    query = urlencode(_shows(entry))
    path = f"/world-entries/{entry['entry_id']}/picture?{query}"
    png = objects_api.client.put(
        path, headers={**objects_api.headers, "Content-Type": "image/png"}, content=b"\x89PNG"
    )
    assert png.status_code == 415 and png.json()["code"] == "picture_media_type"
    after = _put(objects_api, entry, jpeg(640, 360) + b"after the end")
    assert after.status_code == 422 and after.json()["code"] == "picture_refused"


def test_another_workspace_neither_sees_nor_reads_the_picture(objects_api):
    entry = _create_starter(objects_api)
    data = jpeg(640, 360)
    assert _put(objects_api, entry, data).status_code == 200
    digest = hashlib.sha256(data).hexdigest()
    stranger = objects_api.stranger_get(
        f"/world-entries/{entry['entry_id']}/picture?sha256={digest}"
    )
    assert stranger.status_code == 404 and stranger.json()["code"] == "unknown_reference"
    invented = objects_api.stranger_get(f"/world-entries/{uuid.uuid4()}/picture?sha256={digest}")
    assert invented.json() == stranger.json()
    assert all(
        one["entry_id"] != entry["entry_id"]
        for one in objects_api.stranger_get("/world-entries").json()
    )


def test_the_picture_goes_with_its_entry_and_nobody_else_deletes_it(objects_api, repository):
    entry = _create_starter(objects_api)
    assert _put(objects_api, entry, jpeg(640, 360)).status_code == 200
    admin = repository.connection
    workspace = repository.workspace_id
    count = sql.SQL("select count(*) as n from saved_world_entry_picture where workspace_id = %s")
    assert admin.execute(count, (workspace,)).fetchone()["n"] == 1
    # The schema's owner, which row-level security does not bind, is refused by name.
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="erased whole"),
        admin.transaction(),
    ):
        admin.execute("delete from saved_world_entry_picture where workspace_id = %s", (workspace,))
    # The world's erasure deletes its entry, and the entry's trigger deletes its picture first.
    with admin.transaction():
        admin.execute("set local role exulanica_definer")
        admin.execute("select set_config('exulanica.workspace_id', %s, true)", (str(workspace),))
        admin.execute("select participation_erase(%s, %s)", (workspace, entry["world_id"]))
        admin.execute("select world_erase_rows(%s, %s)", (workspace, entry["world_id"]))
    assert admin.execute(count, (workspace,)).fetchone()["n"] == 0
