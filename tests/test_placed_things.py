"""A thing placed in an authored version by its kind, as the pure rules hold it.

What is shown here, with no database:

*   a placed thing's document names its kind by key, version and digest and its pose in its region,
    with no look and no asset;
*   a placement is refused by name for each rule it breaks: its id, its region, its pose, its
    origin, a kind that is not shipped, a version that is not, and a digest that is not the
    shipped one;
*   a kind named without its digest is the shipped one's, and a stated digest must be it;
*   a shipped kind version never changes: the lock beside the kinds pins each shipped document by
    digest and the loader refuses any other, so a change is a new version beside it (the sword's
    second version is one).
"""

from __future__ import annotations

import copy
import json
import shutil

import pytest
from exulanica.things.kinds import (
    KINDS_DIRECTORY,
    ThingKindRefused,
    read_kind_lock,
    shipped_thing_kinds,
)
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import (
    PlacedThing,
    ThingKindReference,
    named_kind,
    placed_thing_document,
    validate_placed_thing,
)

REGIONS = frozenset({"region-a", "region-b"})


def _thing(**changes) -> PlacedThing:
    values = {
        "thing_id": "knight:by-the-well",
        "kind": named_kind("knight", 1),
        "region_id": "region-a",
        "transform": Transform(2_000, 500, 0, 1_570_796, 1_000),
        "origin": ObjectOrigin("authored", "fictional"),
    }
    values.update(changes)
    return PlacedThing(**values)


def test_a_placed_thing_names_its_kind_and_pose_and_nothing_of_how_it_is_drawn():
    knight = shipped_thing_kinds()[("knight", 1)]
    document = placed_thing_document(validate_placed_thing(_thing(), region_ids=REGIONS))
    assert document == {
        "kind": {"kind": "knight", "sha256": knight.sha256, "version": 1},
        "origin": {"kind": "authored", "role": "fictional"},
        "region_id": "region-a",
        "removed": False,
        "thing_id": "knight:by-the-well",
        "transform": {
            "coordinate_space": "region_local",
            "coordinate_unit": "millimetre",
            "scale_milli": 1_000,
            "x_mm": 2_000,
            "y_mm": 500,
            "yaw_microradians": 1_570_796,
            "z_mm": 0,
        },
    }
    assert "look" not in str(document) and "asset" not in str(document)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"thing_id": "Knight"}, id="an-uppercase-id"),
        pytest.param({"thing_id": "knight\n"}, id="an-id-with-a-trailing-newline"),
        pytest.param({"thing_id": "k" * 201}, id="an-id-too-long"),
        pytest.param({"region_id": "region-z"}, id="a-region-the-snapshot-lacks"),
        pytest.param(
            {"transform": Transform(0, 0, 0, 0, 2_000)}, id="a-scale-other-than-its-own-size"
        ),
        pytest.param({"transform": Transform(0, 0, 0, 7_000_000, 1_000)}, id="a-yaw-past-a-turn"),
        pytest.param({"origin": ObjectOrigin("authored", "real")}, id="an-origin-role-unstated"),
        pytest.param({"origin": ObjectOrigin("observed", "personal")}, id="an-origin-not-authored"),
        pytest.param({"kind": ThingKindReference("dragon", 1, "a" * 64)}, id="a-kind-not-shipped"),
        pytest.param(
            {"kind": ThingKindReference("knight", 9, "a" * 64)}, id="a-version-not-shipped"
        ),
        pytest.param(
            {"kind": ThingKindReference("knight", 1, "a" * 64)}, id="a-digest-not-the-shipped-one"
        ),
    ],
)
def test_a_placement_is_refused_by_name_for_each_rule_it_breaks(changes):
    validate_placed_thing(_thing(), region_ids=REGIONS)  # the positive control
    with pytest.raises(InvalidThingPlacement):
        validate_placed_thing(_thing(**copy.deepcopy(changes)), region_ids=REGIONS)


def test_a_kind_named_without_its_digest_is_the_shipped_one_and_a_stated_one_must_be_it():
    shipped = shipped_thing_kinds()
    sword = named_kind("sword", 2)
    assert sword == ThingKindReference("sword", 2, shipped[("sword", 2)].sha256)
    assert named_kind("sword", 2, shipped[("sword", 2)].sha256) == sword
    with pytest.raises(InvalidThingPlacement):
        named_kind("sword", 2, shipped[("sword", 1)].sha256)
    with pytest.raises(InvalidThingPlacement):
        named_kind("sword", 3)


def test_a_shipped_kind_version_never_changes(tmp_path):
    # Every shipped version loads at the digest the lock beside the kinds names.
    assert {key: kind.sha256 for key, kind in shipped_thing_kinds().items()} == read_kind_lock()
    directory = tmp_path / "kinds"

    def refused(change) -> str:
        shutil.rmtree(directory, ignore_errors=True)
        shutil.copytree(KINDS_DIRECTORY, directory)
        change(sorted(directory.glob("*.json")))
        with pytest.raises(ThingKindRefused) as caught:
            shipped_thing_kinds(directory)
        return caught.value.code

    def edited(paths):
        document = json.loads(paths[0].read_text(encoding="utf-8"))
        document["summary"] += " Changed in place."
        paths[0].write_text(json.dumps(document), encoding="utf-8")

    def unlocked(paths):
        document = json.loads(paths[0].read_text(encoding="utf-8"))
        document["version"] = 99
        (directory / f"{document['kind']}.v99.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    # The positive control: an exact copy loads under the same lock.
    shutil.copytree(KINDS_DIRECTORY, directory)
    assert {key: kind.sha256 for key, kind in shipped_thing_kinds(directory).items()} == (
        read_kind_lock()
    )
    # A shipped document changed in place, a version the lock does not name, and a locked version
    # with no file are each refused by name.
    assert refused(edited) == "thing_kind_not_locked"
    assert refused(unlocked) == "thing_kind_not_locked"
    assert refused(lambda paths: paths[0].unlink()) == "thing_kind_not_locked"
