"""Redo, an undo of an undo, for every edit kind the log can hold, on a live PostgreSQL.

For every registered kind, one edit, its undo and a redo, read back from the rows:

* the redo is a row of kind ``undo`` naming the undo it reverses, one ``edit_seq`` on, repeating
  the edit's subject columns, and storing the subject as the undo left it and as the edit left it;
* the version's state token returns exactly to the token the edit produced, and the subject's
  canonical document to the edit's, an undone addition included (its retained row is a placed
  row again, which the restore of a point map or a thing did not do before redo existed).

Then the rule over a sequence: redo steps forward through every undo, an undo after a redo
reverses the redone edit, any new edit ends redo, nothing to redo is refused by name and writes
nothing, and the repository's two queries name exactly what ``exulanica.world.edit_kinds`` names
over many seeded sequences. Through the routes, the redo preview is the redo, and a redo advances
the saved entry it names.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.world import InvalidObjectState, ObjectOrigin, Transform, WorldObjectRepository
from exulanica.world.edit_kinds import redo_candidate, undo_candidate
from exulanica.world.photo_point_maps import PointMapPlacement
from exulanica.world.placed_things import ThingPlacement

from test_edit_kind_undo_postgres import (
    SUBJECT_COLUMNS,
    _environment_document,
    _log,
    _object_document,
    _object_edit,
    _point_map_document,
    _thing_document,
)
from test_photo_point_map_composition import placed as imported_placed  # noqa: F401
from test_world_environment_composition_postgres import composed as imported_composed  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_objects_postgres import world as imported_world  # noqa: F401
from thing_fixtures import kind_body, kind_reference, placeable_kind

pytestmark = pytest.mark.postgres


@pytest.fixture(name="world")
def _world_alias(request):
    return request.getfixturevalue("imported_world")


@pytest.fixture(name="composed")
def _composed_alias(request):
    return request.getfixturevalue("imported_composed")


@pytest.fixture(name="placed")
def _placed_alias(request):
    return request.getfixturevalue("imported_placed")


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _actor() -> uuid.UUID:
    return uuid.uuid4()


def _undo(worlds: WorldObjectRepository, version) -> Any:
    return worlds.undo(version.version_id, base_state_sha256=version.state_sha256, actor=_actor())


def _redo(worlds: WorldObjectRepository, version) -> Any:
    return worlds.redo(version.version_id, base_state_sha256=version.state_sha256, actor=_actor())


def _assert_redone(
    worlds: WorldObjectRepository,
    version_id: uuid.UUID,
    *,
    subject_column: str,
    subject_id: str,
    after_edit: Any,
    after_undo: Any,
    after_redo: Any,
    document_of: Callable[[Any, str], dict[str, Any] | None],
) -> None:
    """The one pin every kind shares, read from the rows."""
    *_, edit, undo, redo = _log(worlds, version_id)
    assert undo["kind"] == "undo" and undo["undone_edit_id"] == edit["edit_id"]
    assert redo["kind"] == "undo"
    assert redo["undone_edit_id"] == undo["edit_id"]
    assert redo["edit_seq"] == undo["edit_seq"] + 1
    assert {column: redo[column] for column in SUBJECT_COLUMNS} == {
        column: (subject_id if column == subject_column else None) for column in SUBJECT_COLUMNS
    }
    assert redo["base_state_sha256"] == after_undo.state_sha256
    assert redo["result_state_sha256"] == after_edit.state_sha256
    assert after_redo.state_sha256 == after_edit.state_sha256
    assert redo["before_document"] == document_of(after_undo, subject_id)
    assert redo["after_document"] == document_of(after_edit, subject_id)
    assert document_of(after_redo, subject_id) == document_of(after_edit, subject_id)
    assert worlds.version(version_id).state_sha256 == after_edit.state_sha256


@pytest.mark.parametrize(
    "kind", ["add_object", "move_object", "remove_object", "set_object_behaviour"]
)
def test_redo_restores_each_object_kind(world, kind):
    worlds, snapshot, _ = world
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=_actor()
    )
    needs_object, edit = _object_edit(kind)
    if needs_object:
        version = _object_edit("add_object")[1](worlds, version)
    after_edit = edit(worlds, version)
    after_undo = _undo(worlds, after_edit)
    after_redo = _redo(worlds, after_undo)
    _assert_redone(
        worlds,
        after_edit.version_id,
        subject_column="object_id",
        subject_id="object:pinned",
        after_edit=after_edit,
        after_undo=after_undo,
        after_redo=after_redo,
        document_of=_object_document,
    )


@pytest.mark.parametrize("kind", ["add_environment", "move_environment", "remove_environment"])
def test_redo_restores_each_environment_kind(composed, kind):
    worlds = composed.worlds
    placement = composed.placement("environment:pinned", feature=True)
    version = composed.version
    if kind != "add_environment":
        version = worlds.add_environment(
            version.version_id, placement, base_state_sha256=version.state_sha256, actor=_actor()
        )
    if kind == "add_environment":
        after_edit = worlds.add_environment(
            version.version_id, placement, base_state_sha256=version.state_sha256, actor=_actor()
        )
    elif kind == "move_environment":
        after_edit = worlds.move_environment(
            version.version_id,
            "environment:pinned",
            Transform(3_000, 0, -1_500, 1_570_796, 1_500),
            base_state_sha256=version.state_sha256,
            actor=_actor(),
        )
    else:
        after_edit = worlds.remove_environment(
            version.version_id,
            "environment:pinned",
            base_state_sha256=version.state_sha256,
            actor=_actor(),
        )
    after_undo = _undo(worlds, after_edit)
    after_redo = _redo(worlds, after_undo)
    _assert_redone(
        worlds,
        after_edit.version_id,
        subject_column="environment_instance_id",
        subject_id="environment:pinned",
        after_edit=after_edit,
        after_undo=after_undo,
        after_redo=after_redo,
        document_of=_environment_document,
    )


@pytest.mark.parametrize("kind", ["add_point_map", "move_point_map", "remove_point_map"])
def test_redo_restores_each_point_map_kind(placed, kind):
    worlds = placed.worlds()
    version_id = uuid.UUID(placed.version_id)
    placement = PointMapPlacement(
        instance_id="point-map:pinned",
        entry_id=uuid.UUID(placed.entry["entry_id"]),
        attachment_id=uuid.UUID(placed.attachment_id),
        region_id=placed.region_id,
        transform=Transform(1_200, 0, -450, 785_398, 1_000),
        origin=ObjectOrigin("authored", "personal"),
    )
    version = worlds.version(version_id)
    if kind != "add_point_map":
        version = worlds.add_point_map(
            version_id, placement, base_state_sha256=version.state_sha256, actor=_actor()
        )
    if kind == "add_point_map":
        after_edit = worlds.add_point_map(
            version_id, placement, base_state_sha256=version.state_sha256, actor=_actor()
        )
    elif kind == "move_point_map":
        after_edit = worlds.move_point_map(
            version_id,
            "point-map:pinned",
            Transform(-2_000, 0, 600, 0, 1_250),
            base_state_sha256=version.state_sha256,
            actor=_actor(),
        )
    else:
        after_edit = worlds.remove_point_map(
            version_id, "point-map:pinned", base_state_sha256=version.state_sha256, actor=_actor()
        )
    after_undo = _undo(worlds, after_edit)
    after_redo = _redo(worlds, after_undo)
    _assert_redone(
        worlds,
        version_id,
        subject_column="point_map_instance_id",
        subject_id="point-map:pinned",
        after_edit=after_edit,
        after_undo=after_undo,
        after_redo=after_redo,
        document_of=_point_map_document,
    )


def _thing_version(world) -> tuple[WorldObjectRepository, Any]:
    worlds, snapshot, _ = world
    return worlds, worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=_actor()
    )


def _place(worlds: WorldObjectRepository, version, thing_id: str = "thing:pinned") -> Any:
    return worlds.add_thing(
        version.version_id,
        ThingPlacement(
            thing_id=thing_id,
            kind=kind_reference(placeable_kind()),
            region_id="region-a",
            transform=Transform(1_200, 0, 0, 785_398, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=_actor(),
        landing=None,
    )


def _move(worlds: WorldObjectRepository, version, x_mm: int, thing_id: str = "thing:pinned"):
    return worlds.move_thing(
        version.version_id,
        thing_id,
        Transform(x_mm, 0, 0, 0, 1_000),
        base_state_sha256=version.state_sha256,
        actor=_actor(),
        landing=None,
    )


@pytest.mark.parametrize("kind", ["add_thing", "move_thing", "remove_thing"])
def test_redo_restores_each_thing_kind(world, kind):
    worlds, version = _thing_version(world)
    if kind != "add_thing":
        version = _place(worlds, version)
    if kind == "add_thing":
        after_edit = _place(worlds, version)
    elif kind == "move_thing":
        after_edit = _move(worlds, version, -2_000)
    else:
        after_edit = worlds.remove_thing(
            version.version_id,
            "thing:pinned",
            base_state_sha256=version.state_sha256,
            actor=_actor(),
        )
    after_undo = _undo(worlds, after_edit)
    after_redo = _redo(worlds, after_undo)
    _assert_redone(
        worlds,
        after_edit.version_id,
        subject_column="thing_id",
        subject_id="thing:pinned",
        after_edit=after_edit,
        after_undo=after_undo,
        after_redo=after_redo,
        document_of=_thing_document,
    )


def test_a_redone_placement_is_a_placed_row_again(world):
    """The fix redo needed: restoring a thing over its undone addition clears the flag, as an
    object's restore always has; before, the row broke its own undone-addition constraint."""
    worlds, version = _thing_version(world)
    placed = _place(worlds, version)
    redone = _redo(worlds, _undo(worlds, placed))
    row = worlds.connection.execute(
        "select removed,addition_undone,last_edit_id from world_alternate_thing "
        "where workspace_id=%s and world_id=%s and version_id=%s and thing_id=%s",
        (worlds.workspace_id, worlds.world_id, placed.version_id, "thing:pinned"),
    ).fetchone()
    assert row == {
        "removed": False,
        "addition_undone": False,
        "last_edit_id": redone.edits[-1].edit_id,
    }


def test_redo_steps_forward_through_every_undo_and_an_undo_after_it_reverses_the_redone_edit(
    world,
):
    worlds, version = _thing_version(world)
    placed = _place(worlds, version)
    first = _move(worlds, placed, 2_000)
    second = _move(worlds, first, 3_000)
    back = _undo(worlds, _undo(worlds, second))
    assert back.state_sha256 == placed.state_sha256
    forward = _redo(worlds, back)
    assert forward.state_sha256 == first.state_sha256
    forward = _redo(worlds, forward)
    assert forward.state_sha256 == second.state_sha256
    with pytest.raises(InvalidObjectState, match="no undo left to redo"):
        _redo(worlds, forward)
    again = _undo(worlds, forward)
    assert again.state_sha256 == first.state_sha256
    assert again.edits[-1].undone_edit_id == second.edits[-1].edit_id


def test_any_new_edit_ends_redo_and_nothing_to_redo_writes_nothing(world):
    worlds, version = _thing_version(world)
    with pytest.raises(InvalidObjectState, match="no undo left to redo"):
        _redo(worlds, version)
    placed = _place(worlds, version)
    undone = _undo(worlds, _move(worlds, placed, 2_000))
    moved_elsewhere = _move(worlds, undone, 5_000)
    with pytest.raises(InvalidObjectState, match="no undo left to redo"):
        _redo(worlds, moved_elsewhere)
    after = worlds.version(moved_elsewhere.version_id)
    assert (after.state_sha256, after.edit_seq) == (
        moved_elsewhere.state_sha256,
        moved_elsewhere.edit_seq,
    )


@pytest.mark.parametrize("seed", range(6))
def test_the_queries_name_what_the_rule_names(world, seed):
    """The repository's two queries against ``edit_kinds``' rule, step by step, from the rows."""
    rng = random.Random(seed)
    worlds, version = _thing_version(world)
    version = _place(worlds, version, "thing:a")
    version = _place(worlds, version, "thing:b")
    for step in range(24):
        edits = worlds.version(version.version_id).edits
        expected_undo, expected_redo = undo_candidate(edits), redo_candidate(edits)
        try:
            named = worlds.validate_undo(version.version_id, base_state_sha256=version.state_sha256)
            assert named.edit_id == expected_undo, step
        except InvalidObjectState:
            assert expected_undo is None, step
        try:
            named = worlds.validate_redo(version.version_id, base_state_sha256=version.state_sha256)
            assert named.edit_id == expected_redo, step
        except InvalidObjectState:
            assert expected_redo is None, step
        choice = rng.choices(("move", "undo", "redo"), weights=(2, 3, 3))[0]
        # Only a thing that stands placed can be moved: an undone placement is not in the version.
        present = sorted(thing.thing_id for thing in worlds.version(version.version_id).things)
        if choice == "move" and present:
            version = _move(worlds, version, rng.randrange(-9, 9) * 1_000, rng.choice(present))
        elif choice == "undo" and expected_undo is not None:
            version = _undo(worlds, version)
        elif choice == "redo" and expected_redo is not None:
            version = _redo(worlds, version)


def _root(api, version: dict) -> str:
    return f"/world/versions/{version['version_id']}"


def test_the_redo_preview_is_the_redo_and_a_redo_writes_through_the_route(objects_api):
    version = objects_api.version("Redo")
    root = _root(objects_api, version)
    placed = objects_api.post(
        objects_api.in_world(f"{root}/things"),
        {
            "base_state_sha256": version["state_sha256"],
            "thing_id": "thing:pinned",
            "kind": kind_body(placeable_kind()),
            "region_id": "region-a",
            "pose": {"x_mm": 1_000, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    nothing = objects_api.post(
        objects_api.in_world(f"{root}/things/redo/preview"),
        {"base_state_sha256": placed.json()["state_sha256"]},
    )
    assert nothing.json()["blocked_reason"] == "invalid_object_state"
    undone = objects_api.post(
        objects_api.in_world(f"{root}/things/undo"),
        {"base_state_sha256": placed.json()["state_sha256"]},
    )
    assert undone.status_code == 200, undone.text
    preview = objects_api.post(
        objects_api.in_world(f"{root}/things/redo/preview"),
        {"base_state_sha256": undone.json()["state_sha256"]},
    )
    assert preview.status_code == 200, preview.text
    verdict = preview.json()
    assert verdict["availability"] == "ready"
    assert verdict["would_change"]["kind"] == "redo"
    assert verdict["would_change"]["undoes"]["edit_id"] == str(
        undone.json()["edits"][-1]["edit_id"]
    )
    redone = objects_api.post(
        objects_api.in_world(f"{root}/things/redo"),
        {"base_state_sha256": undone.json()["state_sha256"]},
    )
    assert redone.status_code == 200, redone.text
    assert redone.json()["state_sha256"] == placed.json()["state_sha256"]
    [thing] = redone.json()["things"]
    assert thing["removed"] is False
    assert verdict["would_change"]["after"] == {
        key: value for key, value in thing.items() if key in verdict["would_change"]["after"]
    }
    stale = objects_api.post(
        objects_api.in_world(f"{root}/things/redo"),
        {"base_state_sha256": undone.json()["state_sha256"]},
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_object_base")
