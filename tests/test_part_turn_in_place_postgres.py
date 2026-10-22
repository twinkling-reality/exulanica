"""A made part turned where it stood is told from a move in the version read's edit log (0225).

A part's first change stores no pose before (it stood as the world was made), so its documents
cannot tell a turn; the parts route states it as it writes the change, from where the part stood
as made (the kind worker's check answers it), and the version read says ``turned_in_place`` on
that edit alone (``exulanica/api/world_version_document.py``). On the fixture farm through the
API, as tests/test_site_parts_postgres.py moves its parts; a half turn keeps the barn's footprint.
"""

from __future__ import annotations

import pytest
from exulanica.world import saved_entries
from exulanica.world.object_repository import part_turned_in_place
from exulanica.world.site_parts import QUARTER_TURNS

from test_site_parts_postgres import FARM, _farm, _move, _parts, _path
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_farm_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)


def test_a_part_turned_where_it_stood_states_it_and_a_move_or_an_undo_states_none(made):
    api = made
    entry = _farm(api)
    barn = _parts(api, entry)["barn"]
    east, north = barn["centre_mm"]

    for pose in (
        (east, north, 2),  # turned where it was made: its first change, no pose of its own before
        (east - 3_000, north, 2),  # moved, its turn kept
        (east - 3_000, north, 0),  # turned where it stands now
        (east, north, 2),  # moved back with a turn
    ):
        answer = _move(api, entry, barn, *pose)
        assert answer.status_code == 200, answer.text
    undone = api.post(
        _path(entry, "/things/undo"), {"base_state_sha256": answer.json()["state_sha256"]}
    )
    assert undone.status_code == 200, undone.text

    edits = sorted(api.get(_path(entry)).json()["edits"], key=lambda edit: edit["edit_seq"])
    assert [(edit["kind"], edit.get("turned_in_place")) for edit in edits] == [
        ("transform_element", True),
        ("transform_element", None),
        ("transform_element", True),
        ("transform_element", None),
        ("undo", None),
    ]
    # Left out, not false, where an edit did not turn a part alone.
    assert sum("turned_in_place" in edit for edit in edits) == 2


def test_the_rule_reads_the_pose_before_or_the_made_centre_and_never_guesses():
    def override(east: int, north: int, turns: int) -> dict[str, object]:
        pose = {"x_mm": east, "y_mm": 0, "z_mm": -north, "yaw_microradians": QUARTER_TURNS[turns]}
        return {"element_id": "part:barn", "suppressed": False, "transform": pose}

    assert part_turned_in_place(None, override(5_000, 7_000, 2), (5_000, 7_000))
    assert not part_turned_in_place(None, override(5_000, 7_000, 0), (5_000, 7_000))
    assert not part_turned_in_place(None, override(4_000, 7_000, 2), (5_000, 7_000))
    assert part_turned_in_place(override(4_000, 7_000, 2), override(4_000, 7_000, 1), None)
    assert not part_turned_in_place(override(4_000, 7_000, 2), override(4_000, 6_000, 1), None)
    # No made centre to read and no pose before: unknowable, so no turn.
    assert not part_turned_in_place(None, override(5_000, 7_000, 2), None)
    # A storeys change states no pose after: no turn.
    stood = {"element_id": "part:barn", "suppressed": False, "transform": None, "storeys": 3}
    assert not part_turned_in_place(override(4_000, 7_000, 2), stood, (5_000, 7_000))
