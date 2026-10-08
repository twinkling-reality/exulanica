"""Scenes as data: the catalog, its lock, each refusal by name, and poses equal to the builder's.

What is shown here, with no database:

*   every scene the catalog ships reads and is locked at its digest; a file the lock does not name
    at its digest, and a lock line with no file, are refused;
*   a scene is refused by name for each rule, each against the shipped scene as a positive control;
*   a place becomes the same pose here as in ``scripts/demo/build_scene.py``, which reaches a server
    from outside and shares no code with it, for a starter's arrival and for an arrival facing east;
*   a world's arrival is read from its entry, and a scene laid out for another ground is refused.
"""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from exulanica.world.generated_worlds import GeneratedGround, GeneratedSite
from exulanica.world.objects import Transform
from exulanica.world.placed_things import UNSCALED_MILLI
from exulanica.world.scenes import (
    SCENES_DIRECTORY,
    SCENES_LOCK,
    SceneArrival,
    SceneRefused,
    places,
    read_scene,
    scene_arrival,
    shipped_scene,
    shipped_scenes,
)
from exulanica.world.starter import (
    AUTHORED_STARTER_COMPOSER,
    AUTHORED_STARTER_COMPOSER_VERSION,
    authored_starter_candidate,
    authored_starter_scene,
)

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_scene", ROOT / "scripts/demo/build_scene.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scene"] = module
    spec.loader.exec_module(module)
    return module


def _shipped_document() -> dict:
    (path,) = sorted(SCENES_DIRECTORY.glob("*.v*.json"))[:1]
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_shipped_scene_reads_and_is_locked_at_its_digest():
    found = shipped_scenes()
    assert found, "the catalog ships a scene"
    for (key, version), scene in found.items():
        assert shipped_scene(key, version, scene.sha256).sha256 == scene.sha256
    with pytest.raises(SceneRefused, match="scene_unshipped"):
        shipped_scene(*next(iter(found)), "0" * 64)


def test_a_changed_file_and_a_lock_line_with_no_file_are_refused(tmp_path):
    directory = tmp_path / "scenes"
    shutil.copytree(SCENES_DIRECTORY, directory)
    lock = directory / SCENES_LOCK.name
    shipped_scenes(directory, lock=lock)  # the positive control: a faithful copy reads
    (path,) = sorted(directory.glob("*.v*.json"))[:1]
    document = json.loads(path.read_text(encoding="utf-8"))
    document["summary"] = document["summary"] + " Changed."
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SceneRefused, match="scene_not_locked"):
        shipped_scenes(directory, lock=lock)
    path.unlink()
    with pytest.raises(SceneRefused, match="scene_not_locked"):
        shipped_scenes(directory, lock=lock)


def _place(index, **place):
    def change(document):
        document["things"][index]["place"] = {
            "right_mm": 0,
            "forward_mm": 0,
            "turn_microradians": 0,
            **place,
        }

    return change


def _first_mind_model(model_id):
    def change(document):
        document["minds"][0]["decider"]["model_id"] = model_id

    return change


def _object_minded(document):
    document["minds"].append(
        {"thing_id": document["things"][0]["thing_id"], "decider": {"kind": "routine"}}
    )


#: Each rule broken alone: the change, the code and words the refusal names.
MUTATIONS = [
    pytest.param(
        lambda d: d.update(profile="exulanica.demo-scene/v1"),
        "invalid_scene",
        "profile",
        id="another profile",
    ),
    pytest.param(lambda d: d.update(colour="red"), "invalid_scene", "exactly", id="a stray field"),
    pytest.param(
        lambda d: d["things"].append(copy.deepcopy(d["things"][0])),
        "invalid_scene",
        "once",
        id="a thing twice",
    ),
    pytest.param(
        lambda d: d["things"][0].update(kind={"kind": "well", "version": 999}),
        "scene_kind_unshipped",
        "well 999",
        id="an unshipped kind",
    ),
    pytest.param(_place(0, right_mm=1_000_001), "invalid_scene", "right_mm", id="too far"),
    pytest.param(
        _place(0, turn_microradians=6_283_186),
        "invalid_scene",
        "turn_microradians",
        id="past a full turn",
    ),
    pytest.param(
        lambda d: d["minds"].append({"thing_id": "nobody", "decider": {"kind": "routine"}}),
        "invalid_scene",
        "minds",
        id="a mind for a stranger",
    ),
    pytest.param(_object_minded, "invalid_scene", "decided for", id="a mind for an object"),
    pytest.param(
        _first_mind_model("no/such-model"), "invalid_scene", "declares", id="an undeclared model"
    ),
    pytest.param(
        lambda d: d["travellers"].update(gate=d["things"][0]["thing_id"]),
        "invalid_scene",
        "arrival",
        id="a gate with no arrival",
    ),
    pytest.param(
        lambda d: d.update(engine="exulanica-society/v99"),
        "invalid_scene",
        "engine",
        id="an unknown engine",
    ),
    pytest.param(lambda d: d.update(origin={}), "invalid_scene", "origin", id="no origin"),
    pytest.param(
        lambda d: d["things"][0].update(thing_id="Knight"),
        "invalid_scene",
        "placed thing's id",
        id="an id placement refuses",
    ),
    pytest.param(
        lambda d: d["things"][0].update(kind={"kind": "visitor", "version": 1}),
        "scene_kind_not_placeable",
        "visitor",
        id="a kind decided only from outside",
    ),
    pytest.param(
        lambda d: d["things"][0].update(kind={"kind": ["well"], "version": 2}),
        "invalid_scene",
        "key and version",
        id="a list where a key belongs",
    ),
    pytest.param(
        lambda d: d.update(engine="exulanica-society/v2"),
        "invalid_scene",
        "society of things",
        id="minds on an engine that seats no placed being",
    ),
    pytest.param(
        lambda d: d.update(engine="exulanica-society/v3"),
        "invalid_scene",
        "still makes",
        id="a retired engine",
    ),
    pytest.param(
        _place(0, forward_mm=-1_000_001), "invalid_scene", "forward_mm", id="too far back"
    ),
    pytest.param(
        lambda d: d["travellers"].update(
            model={"provider": "nebius_token_factory", "model_id": "no/such"}
        ),
        "invalid_scene",
        "declares",
        id="travellers given an undeclared model",
    ),
]


@pytest.mark.parametrize(("change", "code", "words"), MUTATIONS)
def test_a_scene_is_refused_by_name(change, code, words):
    document = _shipped_document()
    read_scene(document)  # the positive control: the shipped scene reads
    broken = copy.deepcopy(document)
    change(broken)
    with pytest.raises(SceneRefused) as refused:
        read_scene(broken)
    assert refused.value.code == code
    assert words in refused.value.detail, refused.value.detail


def test_a_place_becomes_the_same_pose_as_the_demo_builder_computes():
    builder = _builder()
    arrivals = [
        (
            SceneArrival("starter", "region:starter", (0, 0, 4000), (0.0, -1.0)),
            builder.arrival_of(
                {
                    "authored_scene": {
                        "region": {
                            "region_id": "region:starter",
                            "spawn": {"x_mm": 0, "y_mm": 0, "z_mm": 4000, "yaw_microradians": 0},
                        }
                    }
                }
            ),
        ),
        (
            SceneArrival("generated", "region:town", (10_000, 500, 20_000), (700, 0)),
            builder.arrival_of(
                {
                    "generated_ground": {
                        "region_id": "region:town",
                        "arrival_mm": [10_000, 500, 20_000],
                        "arrival_facing_mm": [700, 0],
                    }
                }
            ),
        ),
    ]
    compared = 0
    for scene in shipped_scenes().values():
        for thing in scene.document["things"]:
            for ours, theirs in arrivals:
                pose = ours.pose(thing["place"])
                assert {
                    "x_mm": pose.x_mm,
                    "y_mm": pose.y_mm,
                    "z_mm": pose.z_mm,
                    "yaw_microradians": pose.yaw_microradians,
                } == theirs.pose(thing["place"]), thing["thing_id"]
                compared += 1
    assert compared > 0


def test_a_starter_spawn_turned_a_quarter_faces_west_and_a_turn_of_0_faces_back_east():
    candidate = authored_starter_candidate("world:authored:00000000-0000-0000-0000-000000000000")
    starter = authored_starter_scene(
        composer_key=AUTHORED_STARTER_COMPOSER,
        composer_version=AUTHORED_STARTER_COMPOSER_VERSION,
        topology=candidate.topology,
        placement=candidate.placement,
    )
    spawn = starter.region.spawn
    turned = dataclasses.replace(
        starter,
        region=dataclasses.replace(
            starter.region,
            spawn=dataclasses.replace(spawn, yaw_microradians=1_570_796),
        ),
    )

    class Entry:
        generated_ground = None
        generated_site = None
        authored_scene = turned

    arrival = scene_arrival(Entry())
    # A spawn turned a quarter counterclockwise from north faces west: a metre ahead is a metre
    # west, and a thing at a turn of 0 faces back east, toward the person (yaw a quarter turn).
    pose = arrival.pose({"right_mm": 0, "forward_mm": 1000, "turn_microradians": 0})
    assert pose == Transform(spawn.x_mm - 1000, spawn.y_mm, spawn.z_mm, 1_570_796, UNSCALED_MILLI)
    # Two metres to the right of a person facing west is two metres north.
    right = arrival.pose({"right_mm": 2000, "forward_mm": 0, "turn_microradians": 0})
    assert (right.x_mm, right.z_mm) == (spawn.x_mm, spawn.z_mm - 2000)


def test_a_world_s_arrival_is_read_from_its_entry_and_a_scene_fits_only_its_ground():
    class Entry:
        authored_scene = None
        generated_site = None
        generated_ground = GeneratedGround(
            recipe_key="small_town",
            recipe_label="A small town",
            region_id="region:town",
            arrival_mm=(10_000, 500, 20_000),
            arrival_facing_mm=(0, -700),
            tiles=(),
        )

    town = scene_arrival(Entry())
    assert (town.ground, town.region_id, town.at_mm) == (
        "generated",
        "region:town",
        (10_000, 500, 20_000),
    )
    # Facing north from (10 m, 20 m): a metre ahead is a metre north; a turn of 0 faces back.
    assert town.pose({"right_mm": 0, "forward_mm": 1000, "turn_microradians": 0}) == Transform(
        10_000, 500, 19_000, 0, UNSCALED_MILLI
    )

    class Site(Entry):
        generated_ground = None
        generated_site = GeneratedSite(
            kind="harbour",
            kind_version=1,
            kind_label="Harbour",
            region_id="region:site",
            arrival_mm=(0, 0, 0),
            arrival_facing_mm=(1, 0),
        )

    assert scene_arrival(Site()).ground == "site"

    class Nowhere(Entry):
        generated_ground = None

    with pytest.raises(SceneRefused, match="scene_world_has_no_arrival"):
        scene_arrival(Nowhere())
    scene = next(iter(shipped_scenes().values()))
    assert scene.ground == "starter"
    with pytest.raises(SceneRefused, match="scene_ground_mismatch"):
        places(scene, town)
