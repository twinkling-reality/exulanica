"""Under the 1.0 formats, a version whose chain changes a behaviour is withheld from export.

The edit kinds of authored-world 1.0 and of environment-instances 1.0 are closed lists, and
``set_object_behaviour`` is in neither. Writing such a chain would sign a package those verifiers
refuse, so the version is withheld and counted, as a version holding a placed depth estimate is,
and so is every version branched from it, whose parent pointer could not resolve. A behaviour
named when the object was added is inside 1.0 and still exports; the rest of the package is the
same bytes it was before the withheld version existed. The 1.1 formats admit the edit, and
``test_world_package_motion_postgres.py`` exports the same versions under them.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from exulanica.world.objects import AuthoredObject, ObjectBehaviour, ObjectOrigin, Transform
from exulanica.world_package import authored, environments, verify_package
from exulanica.world_package.export_partition import (
    REASON_KIND_NOT_ADMITTED,
    PlaneVersion,
    plan_export,
)
from exulanica.world_package.extension_formats import AUTHORED_WORLD_1_0, ENVIRONMENT_INSTANCES_1_0

from test_world_package_extension_postgres import (
    CUBE,
    MOTION,
    _export,
    _one_version_one_object,
    _urn,
)

pytestmark = pytest.mark.postgres

SLOWER = ObjectBehaviour(
    "motion.bounded-path",
    1,
    {"axis": "z", "easing": "smooth", "period_milliseconds": 9_000, "travel_mm": 1_500},
)


def _extension_texts(output: Path) -> str:
    return "\n".join(path.read_text() for path in sorted((output / "extensions").rglob("*.json")))


def _a_version_given_a_behaviour_later(objects, snapshot):
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Moved on later", created_by=uuid.uuid4()
    )
    version = objects.add_object(
        version.version_id,
        AuthoredObject(
            object_id="object:kite",
            asset_sha256=CUBE,
            region_id="region-a",
            transform=Transform(0, 0, 0, 0, 1_000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    return objects.set_object_behaviour(
        version.version_id,
        "object:kite",
        SLOWER,
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )


@pytest.mark.parametrize(
    "extensions",
    [[authored.EXTENSION_KEY], [authored.EXTENSION_KEY, environments.EXTENSION_KEY]],
    ids=["authored-alone", "with-environment-instances"],
)
def test_a_behaviour_edit_withholds_its_version_and_its_branch(
    repository, tmp_path: Path, extensions
):
    objects, snapshot, plain = _one_version_one_object(repository, tmp_path)
    before = _export(repository, tmp_path / "before.wmp", extensions=extensions)

    edited = _a_version_given_a_behaviour_later(objects, snapshot)
    branch = objects.create_version(
        parent_version_id=edited.version_id, title="Branch of it", created_by=uuid.uuid4()
    )
    assert branch.edits == () and branch.objects[0].behaviour == SLOWER
    after = _export(repository, tmp_path / "after.wmp", extensions=extensions)

    report = verify_package(after.output)
    findings = {finding.extension: finding for finding in report.extensions}
    world = findings[authored.EXTENSION_NAME].authored_world
    assert [v["version_id"] for v in world.versions] == [
        _urn("alternate-version", plain.version_id)
    ]
    assert world.withheld_versions == 2
    # Motion named when the object was added is inside 1.0 and exports as before.
    assert world.versions[0]["delta"]["objects"][0]["behaviour"] == MOTION.document()
    text = _extension_texts(after.output)
    for withheld in (edited, branch):
        assert _urn("alternate-version", withheld.version_id) not in text
        assert withheld.state_sha256 not in text
    assert "set_object_behaviour" not in text
    assert "Moved on later" not in text and "Branch of it" not in text

    # The version that was exported is the same bytes it was before the others existed.
    old = verify_package(before.output).extensions[0].authored_world
    assert old.withheld_versions == 0
    assert world.versions == old.versions
    for name in ("assets.json", "behaviours.json"):
        relative = f"{authored.EXTENSION_DIR}/{name}"
        assert (after.output / relative).read_bytes() == (before.output / relative).read_bytes()


def test_undoing_a_behaviour_edit_does_not_make_its_version_exportable(repository, tmp_path):
    """The chain still names the edit, and the verifiers refuse a chain, not a state."""
    objects, snapshot, _plain = _one_version_one_object(repository, tmp_path)
    edited = _a_version_given_a_behaviour_later(objects, snapshot)
    undone = objects.undo(
        edited.version_id, base_state_sha256=edited.state_sha256, actor=uuid.uuid4()
    )
    assert undone.objects[0].behaviour is None
    result = _export(repository, tmp_path / "undone.wmp", extensions=[authored.EXTENSION_KEY])
    world = verify_package(result.output).extensions[0].authored_world
    assert world.withheld_versions == 1
    assert _urn("alternate-version", edited.version_id) not in _extension_texts(result.output)


def test_the_partition_withholds_a_behaviour_edit_lineage_and_keeps_its_ancestors():
    root, edited, child, grandchild, sibling = (uuid.uuid4() for _ in range(5))
    environment = frozenset({"environment_instances"})
    plan = plan_export(
        (
            PlaneVersion(root, None, source_invalidated=False),
            PlaneVersion(
                edited,
                root,
                source_invalidated=False,
                chain_kinds=frozenset({"add_object", "set_object_behaviour"}),
            ),
            PlaneVersion(child, edited, source_invalidated=False, state_sections=environment),
            PlaneVersion(grandchild, child, source_invalidated=False),
            PlaneVersion(sibling, root, source_invalidated=False),
        ),
        [AUTHORED_WORLD_1_0, ENVIRONMENT_INSTANCES_1_0],
    )
    assert plan.exported[authored.EXTENSION_KEY] == (root, sibling)
    assert plan.exported[environments.EXTENSION_KEY] == ()
    counted = {key: [each.version_id for each in values] for key, values in plan.withheld.items()}
    assert counted == {
        authored.EXTENSION_KEY: [edited, grandchild],
        environments.EXTENSION_KEY: [child],
    }
    for withheld in plan.withheld.values():
        assert {(w.reason, w.names) for w in withheld} == {
            (REASON_KIND_NOT_ADMITTED, ("set_object_behaviour",))
        }
