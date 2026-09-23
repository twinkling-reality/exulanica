"""Undo, pinned for every edit kind the log can hold, on a live PostgreSQL.

Written before undo's dispatch moved onto the edit-kind registry, and run on the tree before that
move and on the tree after it, so the move is shown to change nothing but the one case it names:
an edit kind nobody registered. For every registered kind the pin is the whole observable result
of one undo, read back from the rows rather than from the returned body:

* the version's state token returns to the one before the edit;
* the subject's canonical document returns to the one before the edit, or the subject is gone
  when the edit was an addition;
* the undo row names the edit it reverses, repeats that edit's subject columns and leaves the
  other three empty, and stores the subject's document on both sides of the undo.

The subject columns are spelled out here rather than taken from the registry, so this file keeps
describing the log's shape if the registry is wrong.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.world import (
    ElementOverride,
    EnvironmentPlacement,
    InvalidObjectState,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    WorldObjectRepository,
    environment_instance_document,
    object_document,
    override_document,
    point_map_instance_document,
)
from exulanica.world.edit_kinds import UnregisteredEditKind
from exulanica.world.photo_point_maps import PointMapPlacement
from psycopg.types.json import Jsonb

from test_photo_point_map_composition import placed as imported_placed  # noqa: F401
from test_world_environment_composition_postgres import composed as imported_composed  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_objects_postgres import authored, transform
from test_world_objects_postgres import world as imported_world  # noqa: F401

pytestmark = pytest.mark.postgres

#: Every id column of the log, in the order the table declares them.
SUBJECT_COLUMNS = ("object_id", "element_id", "environment_instance_id", "point_map_instance_id")

MOTION = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"travel_mm": 2_000, "period_milliseconds": 4_000, "axis": "x", "easing": "smooth"},
)


@pytest.fixture(name="world")
def _world_alias(request):
    return request.getfixturevalue("imported_world")


@pytest.fixture(name="composed")
def _composed_alias(request):
    return request.getfixturevalue("imported_composed")


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="placed")
def _placed_alias(request):
    return request.getfixturevalue("imported_placed")


def _log(worlds: WorldObjectRepository, version_id: uuid.UUID) -> list[dict[str, Any]]:
    return worlds.connection.execute(
        "select edit_id,edit_seq,kind,object_id,element_id,environment_instance_id,"
        "point_map_instance_id,undone_edit_id,base_state_sha256,result_state_sha256,"
        "before_document,after_document from world_alternate_version_edit "
        "where workspace_id=%s and world_id=%s and version_id=%s order by edit_seq",
        (worlds.workspace_id, worlds.world_id, version_id),
    ).fetchall()


def _assert_undo_reversed(
    worlds: WorldObjectRepository,
    version_id: uuid.UUID,
    *,
    kind: str,
    subject_column: str,
    subject_id: str,
    before_edit: Any,
    after_edit: Any,
    after_undo: Any,
    document_of: Callable[[Any, str], dict[str, Any] | None],
) -> None:
    """The one pin every kind shares. ``document_of(version, id)`` is None when it is absent."""
    *_, edit, undo = _log(worlds, version_id)
    assert edit["kind"] == kind
    assert {column: edit[column] for column in SUBJECT_COLUMNS} == {
        column: (subject_id if column == subject_column else None) for column in SUBJECT_COLUMNS
    }
    assert undo["kind"] == "undo"
    assert undo["undone_edit_id"] == edit["edit_id"]
    assert undo["edit_seq"] == edit["edit_seq"] + 1
    assert {column: undo[column] for column in SUBJECT_COLUMNS} == {
        column: edit[column] for column in SUBJECT_COLUMNS
    }
    assert undo["base_state_sha256"] == after_edit.state_sha256
    assert undo["result_state_sha256"] == before_edit.state_sha256
    assert after_undo.state_sha256 == before_edit.state_sha256
    assert undo["before_document"] == document_of(after_edit, subject_id)
    assert undo["after_document"] == document_of(before_edit, subject_id)
    assert document_of(after_undo, subject_id) == document_of(before_edit, subject_id)
    assert worlds.version(version_id).state_sha256 == before_edit.state_sha256


# -- objects -------------------------------------------------------------------------------------


def _object_document(version, object_id: str) -> dict[str, Any] | None:
    found = [obj for obj in version.objects if obj.object_id == object_id]
    return object_document(found[0]) if found else None


def _object_edit(kind: str):
    def add(worlds, version):
        return worlds.add_object(
            version.version_id,
            authored("object:pinned"),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )

    def move(worlds, version):
        return worlds.move_object(
            version.version_id,
            "object:pinned",
            transform(x_mm=4_000, yaw_microradians=0, scale_milli=2_000),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )

    def remove(worlds, version):
        return worlds.remove_object(
            version.version_id,
            "object:pinned",
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )

    def behave(worlds, version):
        return worlds.set_object_behaviour(
            version.version_id,
            "object:pinned",
            MOTION,
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )

    return {
        "add_object": (False, add),
        "move_object": (True, move),
        "remove_object": (True, remove),
        "set_object_behaviour": (True, behave),
    }[kind]


@pytest.mark.parametrize(
    "kind", ["add_object", "move_object", "remove_object", "set_object_behaviour"]
)
def test_undo_reverses_each_object_kind(world, kind):
    worlds, snapshot, _ = world
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=uuid.uuid4()
    )
    needs_object, edit = _object_edit(kind)
    if needs_object:
        version = _object_edit("add_object")[1](worlds, version)
    before_edit = version
    after_edit = edit(worlds, before_edit)
    after_undo = worlds.undo(
        after_edit.version_id, base_state_sha256=after_edit.state_sha256, actor=uuid.uuid4()
    )
    _assert_undo_reversed(
        worlds,
        after_edit.version_id,
        kind=kind,
        subject_column="object_id",
        subject_id="object:pinned",
        before_edit=before_edit,
        after_edit=after_edit,
        after_undo=after_undo,
        document_of=_object_document,
    )


def test_undo_of_an_object_addition_retains_the_row_as_undone(world):
    worlds, snapshot, _ = world
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=uuid.uuid4()
    )
    added = _object_edit("add_object")[1](worlds, version)
    undone = worlds.undo(added.version_id, base_state_sha256=added.state_sha256, actor=uuid.uuid4())
    row = worlds.connection.execute(
        "select removed,addition_undone,last_edit_id from world_alternate_object "
        "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
        (worlds.workspace_id, worlds.world_id, added.version_id, "object:pinned"),
    ).fetchone()
    assert row == {
        "removed": True,
        "addition_undone": True,
        "last_edit_id": undone.edits[-1].edit_id,
    }


# -- element overrides ---------------------------------------------------------------------------


def _override_document(version, element_id: str) -> dict[str, Any] | None:
    found = [o for o in version.element_overrides if o.element_id == element_id]
    return override_document(found[0]) if found else None


@pytest.mark.parametrize(
    ("kind", "override"),
    [
        ("suppress_element", ElementOverride("element:region-b:root", suppressed=True)),
        (
            "transform_element",
            ElementOverride(
                "element:region-b:root", suppressed=False, transform=transform(x_mm=2_500)
            ),
        ),
    ],
)
@pytest.mark.parametrize("replacing", [False, True], ids=["first", "replacing"])
def test_undo_reverses_each_element_kind(world, kind, override, replacing):
    worlds, snapshot, _ = world
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=uuid.uuid4()
    )
    if replacing:
        # An override already stands, so undo restores it rather than taking the element back.
        version = worlds.set_element_override(
            version.version_id,
            ElementOverride(
                "element:region-b:root", suppressed=False, transform=transform(x_mm=-900)
            ),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    before_edit = version
    after_edit = worlds.set_element_override(
        version.version_id,
        override,
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    after_undo = worlds.undo(
        after_edit.version_id, base_state_sha256=after_edit.state_sha256, actor=uuid.uuid4()
    )
    _assert_undo_reversed(
        worlds,
        after_edit.version_id,
        kind=kind,
        subject_column="element_id",
        subject_id="element:region-b:root",
        before_edit=before_edit,
        after_edit=after_edit,
        after_undo=after_undo,
        document_of=_override_document,
    )


# -- environment instances -----------------------------------------------------------------------


def _environment_document(version, instance_id: str) -> dict[str, Any] | None:
    found = [i for i in version.environment_instances if i.instance_id == instance_id]
    return environment_instance_document(found[0]) if found else None


@pytest.mark.parametrize("kind", ["add_environment", "move_environment", "remove_environment"])
def test_undo_reverses_each_environment_kind(composed, kind):
    worlds = composed.worlds
    placement: EnvironmentPlacement = composed.placement("environment:pinned", feature=True)
    version = composed.version
    if kind != "add_environment":
        version = worlds.add_environment(
            version.version_id,
            placement,
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    before_edit = version
    if kind == "add_environment":
        after_edit = worlds.add_environment(
            version.version_id,
            placement,
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    elif kind == "move_environment":
        after_edit = worlds.move_environment(
            version.version_id,
            "environment:pinned",
            Transform(3_000, 0, -1_500, 1_570_796, 1_500),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    else:
        after_edit = worlds.remove_environment(
            version.version_id,
            "environment:pinned",
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    after_undo = worlds.undo(
        after_edit.version_id, base_state_sha256=after_edit.state_sha256, actor=uuid.uuid4()
    )
    _assert_undo_reversed(
        worlds,
        after_edit.version_id,
        kind=kind,
        subject_column="environment_instance_id",
        subject_id="environment:pinned",
        before_edit=before_edit,
        after_edit=after_edit,
        after_undo=after_undo,
        document_of=_environment_document,
    )


# -- photo point maps ----------------------------------------------------------------------------


def _point_map_document(version, instance_id: str) -> dict[str, Any] | None:
    found = [i for i in version.point_map_instances if i.instance_id == instance_id]
    return point_map_instance_document(found[0]) if found else None


@pytest.mark.parametrize("kind", ["add_point_map", "move_point_map", "remove_point_map"])
def test_undo_reverses_each_point_map_kind(placed, kind):
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
            version_id, placement, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
        )
    before_edit = version
    if kind == "add_point_map":
        after_edit = worlds.add_point_map(
            version_id, placement, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
        )
    elif kind == "move_point_map":
        after_edit = worlds.move_point_map(
            version_id,
            "point-map:pinned",
            Transform(-2_000, 0, 600, 0, 1_250),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    else:
        after_edit = worlds.remove_point_map(
            version_id,
            "point-map:pinned",
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )
    after_undo = worlds.undo(
        version_id, base_state_sha256=after_edit.state_sha256, actor=uuid.uuid4()
    )
    _assert_undo_reversed(
        worlds,
        version_id,
        kind=kind,
        subject_column="point_map_instance_id",
        subject_id="point-map:pinned",
        before_edit=before_edit,
        after_edit=after_edit,
        after_undo=after_undo,
        document_of=_point_map_document,
    )


# -- undo itself ---------------------------------------------------------------------------------


def test_an_undo_is_never_itself_undone_and_steps_back_through_history(world):
    """Two edits, two undos, then a refusal: undo walks back and never undoes an undo."""
    worlds, snapshot, _ = world
    empty = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=uuid.uuid4()
    )
    added = _object_edit("add_object")[1](worlds, empty)
    moved = _object_edit("move_object")[1](worlds, added)
    first = worlds.undo(empty.version_id, base_state_sha256=moved.state_sha256, actor=uuid.uuid4())
    assert first.state_sha256 == added.state_sha256
    second = worlds.undo(empty.version_id, base_state_sha256=first.state_sha256, actor=uuid.uuid4())
    assert second.state_sha256 == empty.state_sha256
    log = _log(worlds, empty.version_id)
    assert [row["kind"] for row in log] == ["add_object", "move_object", "undo", "undo"]
    assert [row["undone_edit_id"] for row in log[2:]] == [log[1]["edit_id"], log[0]["edit_id"]]
    with pytest.raises(InvalidObjectState, match="no edit left to undo"):
        worlds.undo(empty.version_id, base_state_sha256=second.state_sha256, actor=uuid.uuid4())
    assert len(_log(worlds, empty.version_id)) == 4


# -- a kind nobody registered ------------------------------------------------------------------


def _append_foreign_edit(worlds, version, *, kind: str, before_document) -> None:
    """Store an edit of a kind no migration admits, the way a lagging registry would meet one.

    Both CHECK constraints are dropped first, inside the caller's rolled-back transaction, because
    they are what keeps such a row out of a real log. The row names an object subject, as a new
    object edit would.
    """
    connection = worlds.connection
    connection.execute(
        "alter table world_alternate_version_edit "
        "drop constraint world_alternate_version_edit_kind_check"
    )
    connection.execute(
        "alter table world_alternate_version_edit "
        "drop constraint world_alternate_edit_names_its_subject"
    )
    connection.execute(
        "insert into world_alternate_version_edit (edit_id,workspace_id,world_id,version_id,"
        "edit_seq,kind,object_id,base_state_sha256,result_state_sha256,before_document,"
        "after_document,actor) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uuid.uuid4(),
            worlds.workspace_id,
            worlds.world_id,
            version.version_id,
            version.edit_seq + 1,
            kind,
            "object:pinned",
            version.state_sha256,
            version.state_sha256,
            None if before_document is None else Jsonb(before_document),
            None,
            uuid.uuid4(),
        ),
    )
    connection.execute(
        "update world_alternate_version set edit_seq=%s "
        "where workspace_id=%s and world_id=%s and version_id=%s",
        (version.edit_seq + 1, worlds.workspace_id, worlds.world_id, version.version_id),
    )


@pytest.mark.parametrize("with_document", [True, False], ids=["with-document", "without"])
def test_an_edit_kind_nobody_registered_is_refused_by_name_and_nothing_is_written(
    world, with_document
):
    """The one behaviour the registry changes, against the two pins it replaced.

    On e9dee3c2 (kept at .exulanica/lane-structure/test_edit_kind_undo_postgres.pre-change.py in
    the lane that made this change) the same row made undo raise KeyError('element_id') when it
    carried a document, and store an undo that reversed nothing when it did not. Now both are the
    registry's refusal naming the kind, and the log and the version are as they were.
    """
    worlds, snapshot, _ = world
    version = worlds.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Pinned", created_by=uuid.uuid4()
    )
    version = _object_edit("add_object")[1](worlds, version)
    with worlds.connection.transaction(force_rollback=True):
        _append_foreign_edit(
            worlds,
            version,
            kind="set_object_colour",
            before_document=(_object_document(version, "object:pinned") if with_document else None),
        )
        log = _log(worlds, version.version_id)
        with pytest.raises(UnregisteredEditKind, match="'set_object_colour'"):
            worlds.undo(
                version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
            )
        assert _log(worlds, version.version_id) == log
        assert worlds.version(version.version_id).objects == version.objects
    # The refusal is the undo route's existing 409, so no new status is invented for it.
    assert issubclass(UnregisteredEditKind, InvalidObjectState)
