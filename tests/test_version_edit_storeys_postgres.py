"""A made building's storeys change is told from a move in the version read's edit log.

Both are ``transform_element`` edits of a ``part:`` override; the edit log stores each edit's
documents, and the version read states the storeys before and after on the edit that changed them
and on no other (``exulanica/api/world_version_document.py``). Against PostgreSQL as the runtime
role, on a small town made through the API, its changes written as the parts routes write them.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.generated_worlds import town_records
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ElementOverride, Transform
from exulanica.world.town_parts import town_buildings

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def test_a_storeys_change_states_its_storeys_and_a_move_or_removal_states_none(made):
    api = made
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Storeys"})
    assert response.status_code == 201, response.text
    entry = response.json()
    workspace, world = api.repository.workspace_id, entry["world_id"]
    version_id = uuid.UUID(entry["authored_version_id"])
    snapshot = uuid.UUID(api.version(entry)["source_snapshot_id"])
    with api.database.session(workspace) as connection:
        tall, gone = (
            b.identity
            for b in town_buildings(town_records(connection, workspace, world, snapshot).records)[
                :2
            ]
        )

    def change(override: ElementOverride, building: str) -> None:
        with api.database.session(workspace) as connection:
            WorldObjectRepository(connection, workspace, world_id=world).set_part_change(
                version_id,
                override,
                base_state_sha256=api.version(entry)["state_sha256"],
                actor=api.actor,
                part_ids=frozenset({building}),
            )

    change(ElementOverride(f"part:{tall}", suppressed=False, storeys=4), tall)
    change(ElementOverride(f"part:{tall}", suppressed=False, storeys=2), tall)
    # A move keeps the storeys the version states.
    moved = Transform(x_mm=1_000, y_mm=0, z_mm=0, yaw_microradians=0, scale_milli=1_000)
    change(ElementOverride(f"part:{tall}", suppressed=False, transform=moved, storeys=2), tall)
    change(ElementOverride(f"part:{gone}", suppressed=True), gone)

    edits = sorted(api.version(entry)["edits"], key=lambda edit: edit["edit_seq"])
    parts = [edit for edit in edits if (edit["element_id"] or "").startswith("part:")]
    assert [(edit["kind"], edit.get("storeys")) for edit in parts] == [
        ("transform_element", {"before": None, "after": 4}),
        ("transform_element", {"before": 4, "after": 2}),
        ("transform_element", None),
        ("suppress_element", None),
    ]
    # Left out, not null, where an edit changed no storeys: those rows keep their bytes.
    assert "storeys" not in parts[2] and "storeys" not in parts[3]
    assert all("storeys" not in edit for edit in edits if edit not in parts[:2])
