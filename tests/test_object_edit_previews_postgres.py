"""Move, remove and undo previews: the verdict and the document the write would record.

Each preview is checked against the write it stands for, on the same stored state: a ready
preview's ``after`` is the document the write then records, a blocked preview's reason is the code
the write then answers, and an unknown or foreign id is answered as the write answers it. Every
preview is also checked to leave the version exactly as it found it.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.api.world_edit import object_problem
from exulanica.world import object_edit_preview

from test_world_objects_api import ObjectsApi, transform
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _path(api: ObjectsApi, version: dict, tail: str) -> str:
    return api.in_world(f"/world/versions/{version['version_id']}/objects/{tail}")


def _read(api: ObjectsApi, version: dict) -> dict:
    response = api.get(api.in_world(f"/world/versions/{version['version_id']}"))
    assert response.status_code == 200, response.text
    return response.json()


def _recorded(repository, edit_id: str) -> dict:
    """The documents the write stored for one edit, read from the log itself."""
    row = repository.connection.execute(
        "select before_document,after_document,undone_edit_id from world_alternate_version_edit "
        "where workspace_id=%s and edit_id=%s",
        (repository.workspace_id, uuid.UUID(edit_id)),
    ).fetchone()
    assert row is not None
    return dict(row)


def _placed(api: ObjectsApi) -> dict:
    version = api.version()
    added = api.add(version)
    assert added.status_code == 201, added.text
    return added.json()


def test_a_move_preview_is_the_document_the_move_records(objects_api, repository):
    version = _placed(objects_api)
    body = {"base_state_sha256": version["state_sha256"], "transform": transform(x_mm=2_400)}

    preview = objects_api.post(_path(objects_api, version, "object:lantern/move/preview"), body)
    assert preview.status_code == 200, preview.text
    document = preview.json()
    assert document["availability"] == "ready"
    assert document["blocked_reason"] is None
    assert document["version"]["state_sha256"] == version["state_sha256"]
    assert document["version"]["edit_seq"] == version["edit_seq"]
    change = document["would_change"]
    assert change["kind"] == "move_object"
    assert change["subject_id"] == "object:lantern"
    assert change["after"]["transform"]["x_mm"] == 2_400
    assert change["before"]["transform"]["x_mm"] == 1_200
    # Nothing moved: the version reads exactly as it did.
    assert _read(objects_api, version) == version

    moved = objects_api.post(_path(objects_api, version, "object:lantern/move"), body)
    assert moved.status_code == 200, moved.text
    edit = moved.json()["edits"][-1]
    recorded = _recorded(repository, edit["edit_id"])
    assert recorded["before_document"] == change["before"]
    assert recorded["after_document"] == change["after"]


def test_a_remove_preview_is_the_document_the_removal_records(objects_api, repository):
    version = _placed(objects_api)
    body = {"base_state_sha256": version["state_sha256"]}

    preview = objects_api.post(_path(objects_api, version, "object:lantern/remove/preview"), body)
    assert preview.status_code == 200, preview.text
    change = preview.json()["would_change"]
    assert change["kind"] == "remove_object"
    assert change["before"]["removed"] is False
    assert change["after"]["removed"] is True
    assert _read(objects_api, version) == version

    removed = objects_api.post(_path(objects_api, version, "object:lantern/remove"), body)
    assert removed.status_code == 200, removed.text
    recorded = _recorded(repository, removed.json()["edits"][-1]["edit_id"])
    assert recorded["before_document"] == change["before"]
    assert recorded["after_document"] == change["after"]


def test_an_undo_preview_names_the_edit_the_undo_reverses(objects_api, repository):
    version = _placed(objects_api)
    moved = objects_api.post(
        _path(objects_api, version, "object:lantern/move"),
        {"base_state_sha256": version["state_sha256"], "transform": transform(x_mm=2_400)},
    )
    version = moved.json()
    move_edit = version["edits"][-1]
    body = {"base_state_sha256": version["state_sha256"]}

    preview = objects_api.post(_path(objects_api, version, "undo/preview"), body)
    assert preview.status_code == 200, preview.text
    change = preview.json()["would_change"]
    assert change["kind"] == "undo"
    assert change["subject_id"] == "object:lantern"
    assert change["undoes"] == {
        "edit_id": move_edit["edit_id"],
        "edit_seq": move_edit["edit_seq"],
        "kind": "move_object",
        "subject": "object",
    }
    assert change["before"]["transform"]["x_mm"] == 2_400
    assert change["after"]["transform"]["x_mm"] == 1_200
    assert _read(objects_api, version) == version

    undone = objects_api.post(_path(objects_api, version, "undo"), body)
    assert undone.status_code == 200, undone.text
    edit = undone.json()["edits"][-1]
    assert edit["undone_edit_id"] == move_edit["edit_id"]
    recorded = _recorded(repository, edit["edit_id"])
    assert recorded["before_document"] == change["before"]
    assert recorded["after_document"] == change["after"]


def test_an_undo_preview_of_an_addition_restores_nothing(objects_api):
    version = _placed(objects_api)
    preview = objects_api.post(
        _path(objects_api, version, "undo/preview"), {"base_state_sha256": version["state_sha256"]}
    )
    change = preview.json()["would_change"]
    assert change["undoes"]["kind"] == "add_object"
    assert change["after"] is None
    assert change["before"]["object_id"] == "object:lantern"


@pytest.mark.parametrize(
    ("tail", "body_extra"),
    [
        ("object:lantern/move", {"transform": transform(x_mm=2_400)}),
        ("object:lantern/remove", {}),
        ("undo", {}),
    ],
    ids=["move", "remove", "undo"],
)
def test_a_stale_base_is_blocked_with_the_code_the_write_answers(objects_api, tail, body_extra):
    version = _placed(objects_api)
    stale = {"base_state_sha256": "0" * 64, **body_extra}

    preview = objects_api.post(_path(objects_api, version, f"{tail}/preview"), stale)
    write = objects_api.post(_path(objects_api, version, tail), stale)
    assert preview.status_code == 200, preview.text
    assert preview.json()["availability"] == "blocked"
    assert preview.json()["would_change"]["preserves"] == []
    assert write.status_code == 409
    assert preview.json()["blocked_reason"] == write.json()["code"] == "stale_object_base"


@pytest.mark.parametrize(
    ("tail", "body_extra"),
    [
        ("object:lantern/move", {"transform": transform(x_mm=2_400)}),
        ("object:lantern/remove", {}),
    ],
    ids=["move", "remove"],
)
def test_a_removed_object_is_blocked_with_the_code_the_write_answers(objects_api, tail, body_extra):
    version = _placed(objects_api)
    removed = objects_api.post(
        _path(objects_api, version, "object:lantern/remove"),
        {"base_state_sha256": version["state_sha256"]},
    ).json()
    body = {"base_state_sha256": removed["state_sha256"], **body_extra}

    preview = objects_api.post(_path(objects_api, removed, f"{tail}/preview"), body)
    assert preview.json()["availability"] == "blocked"
    write = objects_api.post(_path(objects_api, removed, tail), body)
    assert write.status_code == 409
    assert preview.json()["blocked_reason"] == write.json()["code"] == "invalid_object_state"


def test_undoing_nothing_is_blocked_with_the_code_the_write_answers(objects_api):
    version = objects_api.version()
    body = {"base_state_sha256": version["state_sha256"]}
    preview = objects_api.post(_path(objects_api, version, "undo/preview"), body)
    write = objects_api.post(_path(objects_api, version, "undo"), body)
    assert write.status_code == 409
    assert preview.json()["blocked_reason"] == write.json()["code"] == "invalid_object_state"


@pytest.mark.parametrize("tail", ["move", "remove"])
def test_an_unknown_object_is_answered_as_the_write_answers_it(objects_api, tail):
    version = _placed(objects_api)
    body = {"base_state_sha256": version["state_sha256"]}
    if tail == "move":
        body["transform"] = transform()
    preview = objects_api.post(_path(objects_api, version, f"object:nobody/{tail}/preview"), body)
    write = objects_api.post(_path(objects_api, version, f"object:nobody/{tail}"), body)
    assert preview.status_code == write.status_code == 404
    assert preview.json() == write.json()


@pytest.mark.parametrize("tail", ["object:lantern/move", "object:lantern/remove", "undo"])
def test_a_foreign_version_is_answered_as_the_write_answers_it(objects_api, tail):
    version = _placed(objects_api)
    body = {"base_state_sha256": version["state_sha256"]}
    if tail.endswith("move"):
        body["transform"] = transform()
    preview = objects_api.stranger_post(_path(objects_api, version, f"{tail}/preview"), body)
    write = objects_api.stranger_post(_path(objects_api, version, tail), body)
    assert preview.status_code == write.status_code
    assert preview.json() == write.json()
    # And the owner's version is untouched by either.
    assert _read(objects_api, version) == version


def test_each_preview_code_is_the_code_the_object_routes_answer():
    """The preview's table and the routes' table name the same code for every refusal."""
    for refused, code in object_edit_preview._REFUSALS:
        problem = object_problem(refused("probe"))
        assert problem is not None
        assert problem.body is not None
        assert f'"code":"{code}"' in problem.body.decode()
