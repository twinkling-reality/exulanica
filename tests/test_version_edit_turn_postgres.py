"""A placed thing turned where it stood is told from a move in the version read's edit log.

Both are ``move_thing`` edits; the edit log stores each edit's documents, and the version read
states ``turned_in_place`` on the edit that kept the thing's place on the ground and changed its
facing, and on no other (``exulanica/api/world_version_document.py``). Against PostgreSQL, through
the routes a page sends its changes to.
"""

from __future__ import annotations

import pytest

from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from thing_fixtures import kind_body, placeable_kind

pytestmark = pytest.mark.postgres

POSE = {"x_mm": 2_000, "y_mm": 500, "z_mm": 0, "yaw_microradians": 0}


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def test_a_turn_alone_states_it_and_a_move_a_move_with_a_turn_or_an_undo_states_none(objects_api):
    version = objects_api.version("Turns")
    root = f"/world/versions/{version['version_id']}"
    placed = objects_api.post(
        objects_api.in_world(f"{root}/things"),
        {
            "base_state_sha256": version["state_sha256"],
            "thing_id": "thing:bench",
            "kind": kind_body(placeable_kind()),
            "region_id": "region-a",
            "pose": POSE,
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    state = placed.json()["state_sha256"]

    def send(tail: str, body: dict[str, object]) -> None:
        nonlocal state
        answer = objects_api.post(
            objects_api.in_world(f"{root}/things{tail}"), {"base_state_sha256": state, **body}
        )
        assert answer.status_code == 200, answer.text
        state = answer.json()["state_sha256"]

    def move(**pose: int) -> None:
        send("/thing:bench/move", {"pose": {**POSE, **pose}})

    move(yaw_microradians=785_398)  # turned where it stood
    move(x_mm=0)  # moved along x with a turn
    move(x_mm=0, z_mm=1_000, yaw_microradians=785_398)  # moved along z with a turn
    move(x_mm=1_000, yaw_microradians=785_398)  # moved, its facing kept
    move(x_mm=1_000, y_mm=520, yaw_microradians=785_398)  # its height alone
    # The height follows the ground under a turned footprint: still turned where it stood.
    move(x_mm=1_000, y_mm=540, yaw_microradians=1_570_796)
    send("/undo", {})
    send("/thing:bench/remove", {})

    read = objects_api.get(objects_api.in_world(root))
    assert read.status_code == 200, read.text
    edits = sorted(read.json()["edits"], key=lambda edit: edit["edit_seq"])
    assert [(edit["kind"], edit.get("turned_in_place")) for edit in edits] == [
        ("add_thing", None),
        ("move_thing", True),
        ("move_thing", None),
        ("move_thing", None),
        ("move_thing", None),
        ("move_thing", None),
        ("move_thing", True),
        ("undo", None),
        ("remove_thing", None),
    ]
    # Left out, not false, where an edit did not turn a thing alone: those rows keep their bytes.
    assert sum("turned_in_place" in edit for edit in edits) == 2
