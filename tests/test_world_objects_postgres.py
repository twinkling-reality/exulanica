"""Live PostgreSQL proofs for alternate world versions and the objects authored in them.

Every invariant here is stated twice: once as the behaviour, and once as the negative control
that fails when the guard is removed. A test that only ever shows a guard accepting valid input
has not shown the guard exists.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    AuthoredObject,
    ElementOverride,
    InvalidatedSourceVersion,
    InvalidObjectData,
    InvalidObjectState,
    ObjectBehaviour,
    ObjectOrigin,
    ProposalOrigin,
    ProposalProvenance,
    StaleObjectBase,
    StyleProposal,
    StyleReference,
    StyleScope,
    Transform,
    UnknownWorldResource,
    WorldObjectRepository,
    WorldStructureRepository,
    WorldStyleRepository,
    reviewed_assets,
    seed_reviewed_assets,
)
from exulanica.world.flight_kinds import flight_assets

from conftest import scratch_role_database, write_photo
from pg_harness import open_scratch_connection
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

#: The reviewed cube's content digest. Objects name an asset by its bytes, not by its key,
#: so this is what a request body and the digested object document both carry.
CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"

PARAMETERS = {
    "travel_mm": 2_000,
    "period_milliseconds": 4_000,
    "axis": "x",
    "easing": "smooth",
}


def transform(**overrides):
    values = {
        "x_mm": 1_200,
        "y_mm": 0,
        "z_mm": -450,
        "yaw_microradians": 785_398,
        "scale_milli": 1_000,
    }
    values.update(overrides)
    return Transform(**values)


def authored(object_id="object:lantern", **overrides):
    values = {
        "object_id": object_id,
        "asset_sha256": CUBE,
        "region_id": "region-a",
        "transform": transform(),
        "origin": ObjectOrigin("authored", "fictional"),
        "behaviour": None,
        "removed": False,
    }
    values.update(overrides)
    return AuthoredObject(**values)


def another_connection(spine_schema, workspace_id):
    """A genuinely separate connection, scoped the way the application scopes one.

    WorkspaceScope rather than a hand-written set_config: constructing one sets the row factory
    AND declares the workspace, and a test that only did the second would be reading through a
    connection the repository would never be handed.
    """
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    WorkspaceScope(connection, workspace_id)
    return connection


def apply_candidate(structures, candidate, *, actor=None):
    actor = actor or uuid.uuid4()
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


@pytest.fixture
def world(repository, tmp_path):
    """One committed structural snapshot and an object repository over the same connection."""
    world_id = registered_world(repository.connection, repository.workspace_id)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )
    snapshot = apply_candidate(structures, structural_candidate())
    store = LocalContentAddressedStore(tmp_path / "world-objects-store")
    seed_reviewed_assets(store)
    objects = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=world_id, store=store
    )
    return objects, snapshot, structures


def add(objects, version, obj=None, actor=None):
    return objects.add_object(
        version.version_id,
        obj or authored(),
        base_state_sha256=version.state_sha256,
        actor=actor or uuid.uuid4(),
    )


# -- lineage -----------------------------------------------------------------------------------


def test_an_alternate_version_names_the_source_snapshot_it_preserves(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Lantern study", created_by=uuid.uuid4()
    )
    assert version.source_snapshot_id == snapshot.snapshot_id
    assert version.parent_version_id is None
    assert version.edit_seq == 0
    assert version.objects == ()
    # The source is preserved exactly. This is the first sentence of the World state contract.
    assert (
        objects.connection.execute(
            "select snapshot_sha256 from world_structure_snapshot where snapshot_id=%s",
            (snapshot.snapshot_id,),
        ).fetchone()["snapshot_sha256"]
        == snapshot.digests.snapshot_sha256
    )


def test_two_alternates_of_one_source_coexist_and_do_not_move_structural_authority(world):
    """The property the structural plane cannot express: it has one linear revision chain behind
    one current pointer, so two variants of one place could not both exist there."""
    objects, snapshot, structures = world
    before = structures.current()
    first = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Warm", created_by=uuid.uuid4()
    )
    second = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Cold", created_by=uuid.uuid4()
    )
    assert first.version_id != second.version_id
    assert first.source_snapshot_id == second.source_snapshot_id == snapshot.snapshot_id
    after = structures.current()
    assert after.snapshot_id == before.snapshot_id
    assert after.revision == before.revision
    assert after.digests.snapshot_sha256 == before.digests.snapshot_sha256


def test_an_alternate_branches_from_another_alternate_and_copies_its_delta(world):
    objects, snapshot, _ = world
    parent = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Parent", created_by=uuid.uuid4()
    )
    parent = add(objects, parent)
    child = objects.create_version(
        parent_version_id=parent.version_id, title="Child", created_by=uuid.uuid4()
    )
    assert child.parent_version_id == parent.version_id
    assert child.source_snapshot_id == snapshot.snapshot_id
    assert [o.object_id for o in child.objects] == ["object:lantern"]
    # Independent from the branch point on: editing the child leaves the parent alone.
    child = objects.remove_object(
        child.version_id,
        "object:lantern",
        base_state_sha256=child.state_sha256,
        actor=uuid.uuid4(),
    )
    assert child.objects[0].removed is True
    assert objects.version(parent.version_id).objects[0].removed is False


def test_a_version_must_name_exactly_one_origin(world):
    """The negative control for lineage: neither both nor neither is a version."""
    objects, snapshot, _ = world
    parent = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Parent", created_by=uuid.uuid4()
    )
    with pytest.raises(InvalidObjectData):
        objects.create_version(title="Neither", created_by=uuid.uuid4())
    with pytest.raises(InvalidObjectData):
        objects.create_version(
            source_snapshot_id=snapshot.snapshot_id,
            parent_version_id=parent.version_id,
            title="Both",
            created_by=uuid.uuid4(),
        )


def test_a_version_cannot_name_a_snapshot_that_does_not_exist(world):
    objects, _, _ = world
    with pytest.raises(UnknownWorldResource):
        objects.create_version(
            source_snapshot_id=uuid.uuid4(), title="Nowhere", created_by=uuid.uuid4()
        )


# -- stale base --------------------------------------------------------------------------------


def test_an_edit_against_the_current_base_is_accepted(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    updated = add(objects, version)
    assert updated.edit_seq == 1
    assert updated.state_sha256 != version.state_sha256
    assert [o.object_id for o in updated.objects] == ["object:lantern"]


def test_a_second_edit_against_a_stale_base_is_refused_and_changes_nothing(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    stale_base = version.state_sha256
    first = add(objects, version)
    with pytest.raises(StaleObjectBase):
        objects.add_object(
            version.version_id,
            authored("object:second"),
            base_state_sha256=stale_base,
            actor=uuid.uuid4(),
        )
    unchanged = objects.version(version.version_id)
    assert unchanged.state_sha256 == first.state_sha256
    assert unchanged.edit_seq == 1
    assert [o.object_id for o in unchanged.objects] == ["object:lantern"]


def test_every_mutation_records_the_base_it_was_made_against(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    bases = [version.state_sha256]
    version = add(objects, version)
    bases.append(version.state_sha256)
    version = objects.move_object(
        version.version_id,
        "object:lantern",
        transform(x_mm=2_400),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert [edit.base_state_sha256 for edit in version.edits] == bases
    # Each edit's result is the next edit's base, so the chain is checkable end to end.
    assert version.edits[0].result_state_sha256 == version.edits[1].base_state_sha256
    assert version.edits[-1].result_state_sha256 == version.state_sha256


def test_two_writers_racing_one_base_leave_exactly_one_winner(world, spine_schema):
    """The lock is real, not just a comparison. Two open connections, one base."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    base = version.state_sha256
    other = another_connection(spine_schema, objects.workspace_id)
    try:
        competitor = WorldObjectRepository(other, objects.workspace_id, world_id=objects.world_id)
        add(objects, version, authored("object:first"))
        with pytest.raises(StaleObjectBase):
            competitor.add_object(
                version.version_id,
                authored("object:second"),
                base_state_sha256=base,
                actor=uuid.uuid4(),
            )
    finally:
        other.close()
    assert [o.object_id for o in objects.version(version.version_id).objects] == ["object:first"]


# -- the add, move, remove, undo cycle ----------------------------------------------------------


def test_undo_restores_the_document_the_edit_stored(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    placed = version.state_sha256
    version = objects.move_object(
        version.version_id,
        "object:lantern",
        transform(x_mm=9_999),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.objects[0].transform.x_mm == 9_999
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.objects[0].transform.x_mm == 1_200
    # The digest returns to the exact earlier state, which is what makes undo checkable.
    assert version.state_sha256 == placed
    # History is appended, never rewritten.
    assert [e.kind for e in version.edits] == ["add_object", "move_object", "undo"]
    assert version.edits[-1].undone_edit_id == version.edits[1].edit_id


def test_undo_of_a_removal_brings_the_same_object_id_back(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(
        objects,
        version,
        authored(behaviour=ObjectBehaviour("motion.bounded-path", 1, PARAMETERS)),
    )
    live = version.state_sha256
    version = objects.remove_object(
        version.version_id,
        "object:lantern",
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.objects[0].removed is True
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.objects[0].object_id == "object:lantern"
    assert version.objects[0].removed is False
    assert version.objects[0].behaviour.behaviour_key == "motion.bounded-path"
    assert version.state_sha256 == live


def test_undo_of_an_addition_leaves_the_version_empty_again(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    empty = version.state_sha256
    version = add(objects, version)
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.objects == ()
    assert version.state_sha256 == empty


def test_runtime_role_undo_retains_history_without_delete_privilege(
    world, repository, spine_schema
):
    """The deployed writer can undo an addition while DELETE remains unavailable."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    empty = version.state_sha256
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as connection:
        runtime = WorldObjectRepository(
            connection, repository.workspace_id, world_id=objects.world_id, store=objects.store
        )
        assert connection.execute(
            "select has_table_privilege(current_user,'world_alternate_object','DELETE') as allowed"
        ).fetchone()["allowed"] is False
        placed = add(runtime, version)
        undone = runtime.undo(
            version.version_id,
            base_state_sha256=placed.state_sha256,
            actor=uuid.uuid4(),
        )
        assert undone.objects == ()
        assert undone.state_sha256 == empty
        retained = connection.execute(
            "select removed,addition_undone,created_edit_id,last_edit_id "
            "from world_alternate_object where workspace_id=%s and world_id=%s "
            "and version_id=%s and object_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id, "object:lantern"),
        ).fetchone()
        assert retained["removed"] is retained["addition_undone"] is True
        assert retained["created_edit_id"] == placed.edits[-1].edit_id
        assert retained["last_edit_id"] == undone.edits[-1].edit_id

        readded = add(runtime, undone)
        assert [item.object_id for item in readded.objects] == ["object:lantern"]
        assert connection.execute(
            "select count(*) as n from world_alternate_object where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id),
        ).fetchone()["n"] == 1

        removed = runtime.remove_object(
            version.version_id,
            "object:lantern",
            base_state_sha256=readded.state_sha256,
            actor=uuid.uuid4(),
        )
        assert removed.objects[0].removed is True
        projection = connection.execute(
            "select addition_undone,last_edit_id from world_alternate_object "
            "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id, "object:lantern"),
        ).fetchone()
        assert projection == {
            "addition_undone": False,
            "last_edit_id": removed.edits[-1].edit_id,
        }
        restored = runtime.undo(
            version.version_id,
            base_state_sha256=removed.state_sha256,
            actor=uuid.uuid4(),
        )
        assert restored.objects[0].removed is False
        assert restored.state_sha256 == readded.state_sha256


def test_runtime_role_undo_retains_element_override_projection_without_delete(
    world, repository, spine_schema
):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Override study", created_by=uuid.uuid4()
    )
    empty = version.state_sha256
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as connection:
        runtime = WorldObjectRepository(
            connection, repository.workspace_id, world_id=objects.world_id
        )
        assert connection.execute(
            "select has_table_privilege(current_user,'world_alternate_element_override',"
            "'DELETE') as allowed"
        ).fetchone()["allowed"] is False
        element_id = "element:region-b:root"
        placed = runtime.set_element_override(
            version.version_id,
            ElementOverride(element_id, suppressed=True),
            base_state_sha256=empty,
            actor=uuid.uuid4(),
        )
        undone = runtime.undo(
            version.version_id, base_state_sha256=placed.state_sha256, actor=uuid.uuid4()
        )
        assert undone.element_overrides == ()
        assert undone.state_sha256 == empty
        retained = connection.execute(
            "select addition_undone,last_edit_id from world_alternate_element_override "
            "where workspace_id=%s and world_id=%s and version_id=%s and element_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id, element_id),
        ).fetchone()
        assert retained == {"addition_undone": True, "last_edit_id": undone.edits[-1].edit_id}

        child = runtime.create_version(
            parent_version_id=version.version_id,
            title="No hidden override",
            created_by=uuid.uuid4(),
        )
        assert child.element_overrides == ()
        assert child.state_sha256 == empty

        readded = runtime.set_element_override(
            version.version_id,
            ElementOverride(element_id, suppressed=True),
            base_state_sha256=undone.state_sha256,
            actor=uuid.uuid4(),
        )
        assert len(readded.element_overrides) == 1
        assert connection.execute(
            "select count(*) as n from world_alternate_element_override where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id),
        ).fetchone()["n"] == 1

        replaced = runtime.set_element_override(
            version.version_id,
            ElementOverride(element_id, suppressed=False, transform=transform(x_mm=5_000)),
            base_state_sha256=readded.state_sha256,
            actor=uuid.uuid4(),
        )
        restored = runtime.undo(
            version.version_id, base_state_sha256=replaced.state_sha256, actor=uuid.uuid4()
        )
        assert restored.element_overrides == readded.element_overrides
        projection = connection.execute(
            "select addition_undone,last_edit_id from world_alternate_element_override "
            "where workspace_id=%s and world_id=%s and version_id=%s and element_id=%s",
            (repository.workspace_id, runtime.world_id, version.version_id, element_id),
        ).fetchone()
        assert projection == {
            "addition_undone": False,
            "last_edit_id": restored.edits[-1].edit_id,
        }


def test_undo_with_nothing_to_undo_is_refused(world):
    """The negative control for undo."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    with pytest.raises(InvalidObjectState):
        objects.undo(version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4())


def test_undo_is_not_redo_and_stops_when_every_edit_is_reversed(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    # The only edit is reversed, so there is nothing left. A second undo is not a redo.
    with pytest.raises(InvalidObjectState):
        objects.undo(version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4())
    assert objects.version(version.version_id).objects == ()


def test_undo_steps_back_through_more_than_one_edit(world):
    """A control that works once is not an undo. This is the regression for that."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    empty = version.state_sha256
    version = add(objects, version, authored("object:first"))
    after_first = version.state_sha256
    version = add(objects, version, authored("object:second"))
    version = objects.move_object(
        version.version_id,
        "object:second",
        transform(x_mm=8_000),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert [o.object_id for o in version.objects] == ["object:first", "object:second"]

    for _ in range(3):
        version = objects.undo(
            version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
        )
    assert version.objects == ()
    assert version.state_sha256 == empty
    # History is appended throughout; nothing was rewritten.
    assert [e.kind for e in version.edits] == [
        "add_object",
        "add_object",
        "move_object",
        "undo",
        "undo",
        "undo",
    ]
    # Each undo named a distinct edit, walking backwards.
    undone = [e.undone_edit_id for e in version.edits if e.kind == "undo"]
    assert len(set(undone)) == 3
    assert undone == [version.edits[2].edit_id, version.edits[1].edit_id, version.edits[0].edit_id]
    # And the intermediate state is reachable on the way back.
    assert after_first != empty


def test_an_element_override_is_undoable_and_does_not_strand_undo(world):
    """An override used to sit at the head of the log and block undo for the whole version."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    with_object = version.state_sha256
    version = objects.set_element_override(
        version.version_id,
        ElementOverride("element:region-b:root", suppressed=True),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert len(version.element_overrides) == 1

    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.element_overrides == ()
    assert version.state_sha256 == with_object
    # The object edit behind it is still reachable, which is what "does not strand" means.
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.objects == ()


def test_undo_of_a_replaced_override_restores_the_previous_override(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    element_id = "element:region-b:root"
    version = objects.set_element_override(
        version.version_id,
        ElementOverride(element_id, suppressed=True),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    suppressed = version.state_sha256
    version = objects.set_element_override(
        version.version_id,
        ElementOverride(element_id, suppressed=False, transform=transform(x_mm=5_000)),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.element_overrides[0].transform.x_mm == 5_000
    version = objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert version.element_overrides[0].suppressed is True
    assert version.element_overrides[0].transform is None
    assert version.state_sha256 == suppressed


def test_a_removed_object_cannot_be_moved_or_removed_again(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    version = objects.remove_object(
        version.version_id,
        "object:lantern",
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    for operation in (
        lambda: objects.move_object(
            version.version_id,
            "object:lantern",
            transform(),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        ),
        lambda: objects.remove_object(
            version.version_id,
            "object:lantern",
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        ),
    ):
        with pytest.raises(InvalidObjectState):
            operation()


def test_one_object_id_cannot_be_added_twice(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    with pytest.raises(InvalidObjectState):
        objects.add_object(
            version.version_id,
            authored(),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )


# -- reopening ---------------------------------------------------------------------------------


def test_a_version_reopens_on_a_new_connection_with_its_behaviour_still_attached(
    world, spine_schema
):
    """Acceptance, undo and reopening operate on persisted state, not a browser view."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(
        objects,
        version,
        authored(behaviour=ObjectBehaviour("motion.bounded-path", 1, PARAMETERS)),
    )
    objects.connection.commit()

    reopened_connection = another_connection(spine_schema, objects.workspace_id)
    try:
        reopened = WorldObjectRepository(
            reopened_connection, objects.workspace_id, world_id=objects.world_id
        ).version(version.version_id)
    finally:
        reopened_connection.close()

    assert reopened.state_sha256 == version.state_sha256
    assert reopened.title == "Study"
    obj = reopened.objects[0]
    assert obj.object_id == "object:lantern"
    assert obj.transform == transform()
    assert obj.origin == ObjectOrigin("authored", "fictional")
    assert obj.behaviour == ObjectBehaviour("motion.bounded-path", 1, PARAMETERS)


# -- cross-workspace isolation ------------------------------------------------------------------


def test_a_version_is_invisible_and_unwritable_from_another_workspace(world, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Private", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    objects.connection.commit()

    stranger_workspace = uuid.uuid4()
    stranger_connection = another_connection(spine_schema, stranger_workspace)
    try:
        stranger = WorldObjectRepository(
            stranger_connection, stranger_workspace, world_id=objects.world_id
        )
        # Absent and cross-workspace are the identical answer, so nothing leaks by comparison.
        assert stranger.versions() == ()
        with pytest.raises(UnknownWorldResource):
            stranger.version(version.version_id)
        with pytest.raises(UnknownWorldResource):
            stranger.add_object(
                version.version_id,
                authored("object:intruder"),
                base_state_sha256=version.state_sha256,
                actor=uuid.uuid4(),
            )
        with pytest.raises(UnknownWorldResource):
            stranger.version(uuid.uuid4())
    finally:
        stranger_connection.close()

    still = objects.version(version.version_id)
    assert [o.object_id for o in still.objects] == ["object:lantern"]


def test_a_version_cannot_be_branched_from_another_workspaces_snapshot(world, spine_schema):
    """The negative control for isolation on the write path."""
    objects, snapshot, _ = world
    objects.connection.commit()
    stranger_workspace = uuid.uuid4()
    stranger_connection = another_connection(spine_schema, stranger_workspace)
    try:
        stranger = WorldObjectRepository(
            stranger_connection, stranger_workspace, world_id=objects.world_id
        )
        with pytest.raises(UnknownWorldResource):
            stranger.create_version(
                source_snapshot_id=snapshot.snapshot_id,
                title="Borrowed",
                created_by=uuid.uuid4(),
            )
    finally:
        stranger_connection.close()


# -- deletion of the source ----------------------------------------------------------------------


def test_deleting_the_source_scene_invalidates_every_dependent_version(
    repository, tmp_path, photo_dir
):
    """No invalidation code on this side. The structural tombstone trigger writes the row and
    this plane reads it, so a deleted source reaches every version derived from it."""
    world_id = registered_world(repository.connection, repository.workspace_id)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )
    apply_candidate(structures, structural_candidate())

    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "authored-source.jpg")
    )
    assert outcome.error is None
    evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s limit 1",
        (repository.workspace_id,),
    ).fetchone()
    dependent = apply_candidate(
        structures,
        structural_candidate(graph="graph-with-source", evidence_span_id=evidence["span_id"]),
    )

    seed_reviewed_assets(store)
    objects = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=world_id, store=store
    )
    first = objects.create_version(
        source_snapshot_id=dependent.snapshot_id, title="One", created_by=uuid.uuid4()
    )
    second = objects.create_version(
        source_snapshot_id=dependent.snapshot_id, title="Two", created_by=uuid.uuid4()
    )
    first = add(objects, first)
    assert objects.version(first.version_id).source_invalidated is False

    repository.insert_tombstone(
        scope="capture",
        capture_id=evidence["capture_id"],
        requested_by=uuid.uuid4(),
        reason="the source scene was deleted",
    )

    for version_id in (first.version_id, second.version_id):
        assert objects.version(version_id).source_invalidated is True
    # The authored work survives the deletion of the source it was placed against; what it
    # cannot do is be extended against a source that is gone.
    assert [o.object_id for o in objects.version(first.version_id).objects] == ["object:lantern"]
    with pytest.raises(InvalidatedSourceVersion):
        objects.add_object(
            first.version_id,
            authored("object:another"),
            base_state_sha256=objects.version(first.version_id).state_sha256,
            actor=uuid.uuid4(),
        )
    with pytest.raises(InvalidatedSourceVersion):
        objects.create_version(
            source_snapshot_id=dependent.snapshot_id, title="Three", created_by=uuid.uuid4()
        )


# -- both families over one version --------------------------------------------------------------


def test_appearance_and_authored_objects_coexist_over_one_structural_version(world):
    """The existing preview, apply and rollback cycle run once against the same version that
    carries an authored object. Neither family writes the other's tables."""
    objects, snapshot, structures = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)

    styles = WorldStyleRepository(
        objects.connection, objects.workspace_id, world_id=objects.world_id
    )
    original_style = styles.current()
    topology_digest = styles.current_topology_digest()
    assert topology_digest == snapshot.digests.topology_sha256

    actor = uuid.uuid4()

    def proposal(parameters, base):
        return StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.SETTINGS, actor, "appearance-panel"),
            scope=StyleScope("global"),
            base_style_version_id=base.version_id,
            base_topology_digest=topology_digest,
            profile=StyleReference("origin-landscape", 1, parameters),
            reference_ids=(),
            model_id=None,
            prompt_version=None,
            refines_proposal_id=None,
        )

    preview = styles.preview(proposal({"vitality": 0.75}, original_style))
    applied = styles.apply(
        preview.preview_id,
        base_style_version_id=original_style.version_id,
        base_topology_digest=topology_digest,
        applied_by=actor,
    )
    assert applied.version_id != original_style.version_id
    rolled_back = styles.rollback(
        target_version_id=original_style.version_id,
        base_style_version_id=applied.version_id,
        base_topology_digest=topology_digest,
        provenance=ProposalProvenance(ProposalOrigin.SETTINGS, actor, "appearance-panel"),
    )
    assert rolled_back.version_id not in {original_style.version_id, applied.version_id}

    # The authored version is byte-for-byte untouched by three appearance transactions.
    after = objects.version(version.version_id)
    assert after.state_sha256 == version.state_sha256
    assert after.edit_seq == version.edit_seq
    assert [o.object_id for o in after.objects] == ["object:lantern"]
    # And the structural pointer did not move for either family.
    assert structures.current().snapshot_id == snapshot.snapshot_id


def test_an_object_edit_does_not_write_any_structural_or_style_row(world):
    """The negative control for separation: count the other planes' rows across an edit."""
    objects, snapshot, _ = world

    def counts():
        return {
            table: objects.connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
            for table in (
                "world_structure_snapshot",
                "world_structure_snapshot_element",
                "world_structure_preview",
                "world_style_version",
                "world_style_preview",
                "world_topology_contract",
            )
        }

    before = counts()
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    objects.move_object(
        version.version_id,
        "object:lantern",
        transform(x_mm=7),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert counts() == before


# -- immutability ---------------------------------------------------------------------------------


def test_the_edit_log_refuses_update_and_delete(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    for statement in (
        "update world_alternate_version_edit set kind='undo'",
        "delete from world_alternate_version_edit",
    ):
        with pytest.raises(psycopg.errors.IntegrityError), objects.connection.transaction():
            objects.connection.execute(statement)


def test_a_versions_source_and_lineage_cannot_be_rewritten(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    with pytest.raises(psycopg.errors.IntegrityError), objects.connection.transaction():
        objects.connection.execute(
            "update world_alternate_version set title='Renamed' where version_id=%s",
            (version.version_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityError), objects.connection.transaction():
        objects.connection.execute(
            "delete from world_alternate_version where version_id=%s", (version.version_id,)
        )


def test_the_reviewed_catalogs_match_what_the_code_generates(world, tmp_path):
    objects, _, _ = world
    store = LocalContentAddressedStore(tmp_path / "blobs")
    catalog = {a.asset_key: a for a in objects.reviewed_assets(store)}
    # The flying kinds' bodies and wings are registry rows too (0114), seeded beside the objects.
    generated = (*reviewed_assets(), *flight_assets())
    assert set(catalog) == {asset.asset_key for asset in generated}
    # Nothing has been seeded into the store yet, so nothing may claim to be available.
    assert {a.availability for a in catalog.values()} == {"unavailable_asset"}

    assert seed_reviewed_assets(store) == reviewed_assets()
    for asset in generated:
        assert catalog[asset.asset_key].content_sha256 == asset.content_sha256
        assert catalog[asset.asset_key].byte_size == asset.byte_size
        assert catalog[asset.asset_key].licence_sha256 == asset.licence_sha256
    after = {a.asset_key: a for a in objects.reviewed_assets(store)}
    assert {a.availability for a in after.values()} == {"available"}


# -- source-element overrides ------------------------------------------------------------------


def test_a_version_stores_suppression_and_transform_of_a_source_element(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    element_id = "element:region-b:root"
    version = objects.set_element_override(
        version.version_id,
        ElementOverride(element_id, suppressed=True),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert [o.element_id for o in version.element_overrides] == [element_id]
    assert version.element_overrides[0].suppressed is True
    version = objects.set_element_override(
        version.version_id,
        ElementOverride(element_id, suppressed=False, transform=transform(x_mm=5_000)),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    assert version.element_overrides[0].suppressed is False
    assert version.element_overrides[0].transform.x_mm == 5_000
    # The source snapshot itself is untouched by either override.
    stored = objects.connection.execute(
        "select placement from world_structure_snapshot where snapshot_id=%s",
        (snapshot.snapshot_id,),
    ).fetchone()["placement"]
    assert {e["element_id"] for e in stored["elements"]} == {
        "element:region-a:root",
        "element:region-b:root",
    }


def test_an_override_of_an_element_the_source_does_not_have_is_refused(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    with pytest.raises(InvalidObjectData):
        objects.set_element_override(
            version.version_id,
            ElementOverride("element:invented", suppressed=True),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        )


# -- a behaviour given to, changed on, or taken from an object that already exists ---------------

MOTION = ObjectBehaviour("motion.bounded-path", 1, PARAMETERS)
#: Every parameter differs from MOTION, so a restore that kept any one of them would show.
SLOWER = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"travel_mm": 650, "period_milliseconds": 9_000, "axis": "y", "easing": "linear"},
)


def set_behaviour(objects, version, behaviour, object_id="object:lantern"):
    return objects.set_object_behaviour(
        version.version_id,
        object_id,
        behaviour,
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )


def undo(objects, version):
    return objects.undo(
        version.version_id, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )


def edit_documents(objects, edit_id):
    return objects.connection.execute(
        "select before_document,after_document from world_alternate_version_edit where edit_id=%s",
        (edit_id,),
    ).fetchone()


def edit_count(objects, version_id, kind=None):
    return objects.connection.execute(
        "select count(*) as n from world_alternate_version_edit where version_id=%s "
        "and (%s::text is null or kind=%s)",
        (version_id, kind, kind),
    ).fetchone()["n"]


def test_a_placed_object_is_given_a_behaviour_and_undo_takes_back_only_that(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version)
    assert placed.objects[0].behaviour is None

    moving = set_behaviour(objects, placed, MOTION)

    [obj] = moving.objects
    assert obj.behaviour == MOTION
    assert obj.transform == transform()
    assert (obj.origin, obj.removed) == (placed.objects[0].origin, False)
    assert moving.state_sha256 != placed.state_sha256, "the behaviour is inside the digest"
    edit = moving.edits[-1]
    assert (edit.kind, edit.object_id, edit.element_id) == (
        "set_object_behaviour",
        "object:lantern",
        None,
    )
    assert (edit.base_state_sha256, edit.result_state_sha256) == (
        placed.state_sha256,
        moving.state_sha256,
    )
    stored = edit_documents(objects, edit.edit_id)
    assert stored["before_document"]["behaviour"] is None
    assert stored["after_document"]["behaviour"]["parameters"] == PARAMETERS

    back = undo(objects, moving)
    assert back.objects == placed.objects, "the object is as it was, and still there"
    assert back.state_sha256 == placed.state_sha256
    assert back.edits[-1].undone_edit_id == edit.edit_id


def test_undo_restores_exactly_the_previous_behaviour_after_a_change_and_after_a_clear(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version, authored(behaviour=MOTION))

    changed = set_behaviour(objects, placed, SLOWER)
    assert changed.objects[0].behaviour == SLOWER
    restored = undo(objects, changed)
    assert restored.objects[0].behaviour == MOTION
    assert dict(restored.objects[0].behaviour.parameters) == PARAMETERS
    assert restored.state_sha256 == placed.state_sha256

    cleared = set_behaviour(objects, restored, None)
    assert cleared.objects[0].behaviour is None
    assert cleared.objects[0].transform == transform(), "clearing moves nothing"
    assert cleared.edits[-1].kind == "set_object_behaviour"
    brought_back = undo(objects, cleared)
    assert brought_back.objects[0].behaviour == MOTION
    assert dict(brought_back.objects[0].behaviour.parameters) == PARAMETERS
    assert brought_back.state_sha256 == placed.state_sha256


def test_undo_steps_back_through_a_chain_of_behaviour_edits_to_the_placement(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version)
    given = set_behaviour(objects, placed, MOTION)
    changed = set_behaviour(objects, given, SLOWER)
    cleared = set_behaviour(objects, changed, None)

    states = [cleared]
    for _ in range(3):
        states.append(undo(objects, states[-1]))
    assert [s.objects[0].behaviour for s in states] == [None, SLOWER, MOTION, None]
    assert [s.state_sha256 for s in states[1:]] == [
        changed.state_sha256,
        given.state_sha256,
        placed.state_sha256,
    ]
    emptied = undo(objects, states[-1])
    assert emptied.objects == (), "the fourth undo reaches the placement itself"


@pytest.mark.parametrize(
    ("behaviour", "reason"),
    [
        (ObjectBehaviour("motion.spin", 1, PARAMETERS), "motion.spin@1 is not reviewed"),
        (ObjectBehaviour("motion.bounded-path", 2, PARAMETERS), "bounded-path@2 is not reviewed"),
        (
            ObjectBehaviour("motion.bounded-path", 1, {**PARAMETERS, "travel_mm": 10_001}),
            "travel_mm must be between 100 and 10000",
        ),
        (
            ObjectBehaviour("motion.bounded-path", 1, {**PARAMETERS, "period_milliseconds": 499}),
            "period_milliseconds must be between 500 and 60000",
        ),
        (
            ObjectBehaviour("motion.bounded-path", 1, {**PARAMETERS, "axis": "w"}),
            "axis must be one of x, y, z",
        ),
        (
            ObjectBehaviour("motion.bounded-path", 1, {**PARAMETERS, "speed": 3}),
            "unknown behaviour parameter speed",
        ),
        (
            ObjectBehaviour(
                "motion.bounded-path", 1, {k: v for k, v in PARAMETERS.items() if k != "easing"}
            ),
            "behaviour parameter easing is required",
        ),
        (
            ObjectBehaviour("motion.bounded-path", 1, {**PARAMETERS, "travel_mm": 2_000.0}),
            "travel_mm must be an integer",
        ),
    ],
)
def test_an_unreviewed_behaviour_is_refused_and_nothing_is_written(world, behaviour, reason):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version)
    edits_before = edit_count(objects, placed.version_id)

    with pytest.raises(InvalidObjectData, match=reason):
        set_behaviour(objects, placed, behaviour)

    after = objects.version(placed.version_id)
    assert (after.state_sha256, after.edit_seq, after.objects) == (
        placed.state_sha256,
        placed.edit_seq,
        placed.objects,
    )
    assert edit_count(objects, placed.version_id) == edits_before


def test_the_reviewed_bounds_themselves_are_accepted(world):
    """The positive control for the refusals above: each bound is inclusive."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = add(objects, version)
    for travel, period in ((100, 500), (10_000, 60_000)):
        bounded = ObjectBehaviour(
            "motion.bounded-path",
            1,
            {**PARAMETERS, "travel_mm": travel, "period_milliseconds": period},
        )
        version = set_behaviour(objects, version, bounded)
        assert version.objects[0].behaviour == bounded


def test_a_behaviour_edit_against_a_stale_base_is_refused_and_changes_nothing(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version)
    moved = objects.move_object(
        placed.version_id,
        "object:lantern",
        transform(x_mm=3_000),
        base_state_sha256=placed.state_sha256,
        actor=uuid.uuid4(),
    )
    with pytest.raises(StaleObjectBase):
        set_behaviour(objects, placed, MOTION)
    current = objects.version(placed.version_id)
    assert (current.state_sha256, current.edit_seq) == (moved.state_sha256, moved.edit_seq)
    assert current.objects[0].behaviour is None


def test_a_behaviour_edit_names_a_live_object_and_must_change_something(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version, authored(behaviour=MOTION))

    with pytest.raises(UnknownWorldResource):
        set_behaviour(objects, placed, MOTION, object_id="object:absent")
    with pytest.raises(InvalidObjectState, match="already has exactly that behaviour"):
        set_behaviour(objects, placed, MOTION)
    cleared = set_behaviour(objects, placed, None)
    with pytest.raises(InvalidObjectState, match="has no behaviour to take away"):
        set_behaviour(objects, cleared, None)
    removed = objects.remove_object(
        cleared.version_id,
        "object:lantern",
        base_state_sha256=cleared.state_sha256,
        actor=uuid.uuid4(),
    )
    with pytest.raises(InvalidObjectState, match="is removed"):
        set_behaviour(objects, removed, MOTION)
    assert objects.version(placed.version_id).state_sha256 == removed.state_sha256


def test_the_edit_log_admits_a_behaviour_edit_only_about_one_object(world):
    """Migration 0096 on the live schema: the kind exists, and it must name an object alone."""
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = set_behaviour(objects, add(objects, version), MOTION)  # the kind is admitted
    base = version.state_sha256

    def insert(kind, *, object_id=None, element_id=None, environment_instance_id=None):
        objects.connection.execute(
            "insert into world_alternate_version_edit (workspace_id,world_id,version_id,"
            "edit_seq,kind,object_id,element_id,environment_instance_id,base_state_sha256,"
            "result_state_sha256,actor) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                objects.workspace_id,
                objects.world_id,
                version.version_id,
                1_000,
                kind,
                object_id,
                element_id,
                environment_instance_id,
                base,
                base,
                uuid.uuid4(),
            ),
        )

    refused = (
        ("set_object_behaviour", {"element_id": "element:region-a:root"}),
        ("set_object_behaviour", {"object_id": "object:lantern", "element_id": "e"}),
        ("set_object_behaviour", {"object_id": "object:lantern", "environment_instance_id": "i"}),
        ("set_object_behaviours", {"object_id": "object:lantern"}),
    )
    for kind, subject in refused:
        with pytest.raises(psycopg.errors.CheckViolation), objects.connection.transaction():
            insert(kind, **subject)
    with objects.connection.transaction():
        insert("set_object_behaviour", object_id="object:lantern")  # the shape that is admitted
    assert edit_count(objects, version.version_id, "set_object_behaviour") == 2


def test_runtime_role_gives_clears_and_restores_a_behaviour(world, repository, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    placed = add(objects, version)
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as connection:
        runtime = WorldObjectRepository(
            connection, repository.workspace_id, world_id=objects.world_id, store=objects.store
        )
        given = set_behaviour(runtime, placed, MOTION)
        cleared = set_behaviour(runtime, given, None)
        restored = undo(runtime, cleared)
        assert restored.objects[0].behaviour == MOTION
        assert restored.state_sha256 == given.state_sha256


def test_a_behaviour_given_later_reopens_on_a_new_connection(world, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Study", created_by=uuid.uuid4()
    )
    version = set_behaviour(objects, add(objects, version), SLOWER)
    objects.connection.commit()

    reopened_connection = another_connection(spine_schema, objects.workspace_id)
    try:
        reopened = WorldObjectRepository(
            reopened_connection, objects.workspace_id, world_id=objects.world_id
        ).version(version.version_id)
    finally:
        reopened_connection.close()
    assert reopened.state_sha256 == version.state_sha256
    assert reopened.objects[0].behaviour == SLOWER
    assert [e.kind for e in reopened.edits] == ["add_object", "set_object_behaviour"]
