"""The demo's scenes: data the product's own routes can build, and a builder that names no scene.

What is shown here, with no database and no server:

*   every scene document under ``scripts/demo/scenes`` names only shipped thing kinds at shipped
    versions, places each thing once, and chooses minds only for its own beings and only open
    models the model manifest serves;
*   a place stated from where a person arrives becomes the same pose in any world's frame: on a
    starter (the spawn faces north) and for an arrival facing east, checked against arithmetic done
    here rather than the builder's;
*   against a server played here, the builder places every thing bound to the saved world, a
    second run places nothing, and a thing already placed as something else is refused by name;
*   it then starts the scene's society and chooses each being's mind under keys a second run asks
    with again, and refuses a society on another engine or a mind that reads back as another.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from exulanica.things.kinds import shipped_thing_kinds

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "scripts/demo/scenes"
MANIFEST = ROOT / "exulanica/models/models.manifest.json"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_scene", ROOT / "scripts/demo/build_scene.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scene"] = module
    spec.loader.exec_module(module)
    return module


def _scenes() -> list[Path]:
    return sorted(SCENES.glob("*.json"))


def test_scenes_ship():
    assert _scenes()


@pytest.mark.parametrize("path", _scenes(), ids=lambda path: path.name)
def test_a_scene_names_shipped_kinds_and_served_models(path):
    scene = _builder().read_scene(path)
    shipped = shipped_thing_kinds()
    for thing in scene["things"]:
        assert (thing["kind"]["kind"], thing["kind"]["version"]) in shipped, thing["thing_id"]
    beings = {
        thing["thing_id"]
        for thing in scene["things"]
        if shipped[(thing["kind"]["kind"], thing["kind"]["version"])].document["class"] == "being"
    }
    served = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["models"])
    for mind in scene["minds"]:
        assert mind["thing_id"] in beings
        assert mind["decider"]["model_id"] in served


def test_a_scene_places_each_thing_once_and_minds_only_its_own(tmp_path):
    builder = _builder()
    scene = json.loads(_scenes()[0].read_text(encoding="utf-8"))
    builder.read_scene(_scenes()[0])  # the positive control: the scene as shipped reads
    twice = copy.deepcopy(scene)
    twice["things"].append(copy.deepcopy(twice["things"][0]))
    stray = copy.deepcopy(scene)
    stray["minds"].append({"thing_id": "nobody", "decider": stray["minds"][0]["decider"]})
    for faulty, words in ((twice, "once"), (stray, "lacks")):
        path = tmp_path / "scene.json"
        path.write_text(json.dumps(faulty), encoding="utf-8")
        with pytest.raises(builder.SceneRefused, match=words):
            builder.read_scene(path)


def test_a_place_becomes_the_same_pose_from_any_arrival():
    builder = _builder()
    place = {"right_mm": 1300, "forward_mm": 4600, "turn_microradians": 0}
    starter = builder.arrival_of(
        {
            "authored_scene": {
                "region": {
                    "region_id": "region:starter",
                    "spawn": {"x_mm": 0, "y_mm": 0, "z_mm": 4000, "yaw_microradians": 0},
                }
            }
        }
    )
    # Facing north from (0, 4000): to the right is east, ahead is north (smaller z).
    assert starter.pose(place) == {"x_mm": 1300, "y_mm": 0, "z_mm": -600, "yaw_microradians": 0}
    town = builder.arrival_of(
        {
            "generated_ground": {
                "region_id": "region:town",
                "arrival_mm": [10_000, 500, 20_000],
                "arrival_facing_mm": [700, 0],
            }
        }
    )
    # Facing east: ahead is east, to the right is south. Facing east is a quarter turn clockwise
    # from north, -1,570,796 microradians, which is 4,712,390 within a full turn of 6,283,186.
    assert town.pose(place) == {
        "x_mm": 14_600,
        "y_mm": 500,
        "z_mm": 21_300,
        "yaw_microradians": 4_712_390,
    }
    facing_them = dict(place, turn_microradians=3_141_593)
    assert town.pose(facing_them)["yaw_microradians"] == 1_570_797


class _Server:
    """The routes the builder calls, played here: one starter world whose version holds things."""

    def __init__(self) -> None:
        self.entry = {
            "entry_id": "entry-1",
            "world_id": "world:authored:1",
            "authored_version_id": "version-1",
            "authored_state_sha256": "0" * 64,
            "authored_edit_seq": 0,
            "revision": 1,
            "authored_scene": {
                "region": {
                    "region_id": "region:starter",
                    "spawn": {"x_mm": 0, "y_mm": 0, "z_mm": 4000, "yaw_microradians": 0},
                }
            },
        }
        self.things: list[dict[str, Any]] = []
        self.edits = 0
        self.bound: list[dict[str, Any]] = []
        self.beings = {
            key
            for (key, _), kind in shipped_thing_kinds().items()
            if kind.document["class"] == "being"
        }
        self.engine: str | None = None
        self.asked: dict[str, dict[str, Any]] = {}
        self.chosen: dict[str, dict[str, str] | None] = {}
        self.read_back: dict[str, dict[str, str] | None] = {}

    def _version(self) -> dict[str, Any]:
        return {
            "state_sha256": f"{self.edits:064d}",
            "edit_seq": self.edits,
            "things": copy.deepcopy(self.things),
        }

    def call(self, method: str, path: str, body: Any = None, **query: str) -> Any:
        if (method, path) == ("POST", "/world-entries/starter"):
            return copy.deepcopy(self.entry)
        if (method, path) == ("GET", "/world-entries/entry-1"):
            return copy.deepcopy(self.entry)
        if (method, path) == ("GET", "/world/versions/version-1"):
            assert query == {"world_id": "world:authored:1"}
            return self._version()
        if (method, path) == ("POST", "/world/versions/version-1/things"):
            assert body["base_state_sha256"] == f"{self.edits:064d}"
            assert body["saved_entry"]["authored_edit_seq"] == self.entry["authored_edit_seq"]
            self.bound.append(body["saved_entry"])
            self.things.append(
                {
                    "thing_id": body["thing_id"],
                    "kind": {**body["kind"], "sha256": "f" * 64},
                    "region_id": body["region_id"],
                    "transform": body["pose"],
                    "removed": False,
                }
            )
            self.edits += 1
            self.entry.update(
                authored_state_sha256=f"{self.edits:064d}",
                authored_edit_seq=self.edits,
                revision=self.entry["revision"] + 1,
            )
            return self._version()
        if (method, path) == ("POST", "/world/versions/version-1/society"):
            assert body["region_id"] == "region:starter"
            self.engine = self.engine or body["profile"]
            people = [
                {
                    "id": f"person:{thing['thing_id']}",
                    "placed_id": thing["thing_id"],
                    "came_by": "placed",
                }
                for thing in self.things
                if thing["kind"]["kind"] in self.beings
            ]
            villager = {"id": "person:villager", "placed_id": None, "came_by": "populated"}
            return {
                "profile": self.engine,
                "society_id": "society-1",
                "state_sha256": "a" * 64,
                "state": {"inhabitants": [villager, *people]},
            }
        if (method, path) == ("POST", "/world/versions/version-1/society/models"):
            # A key asked again must ask for the same choice, and is answered with the one recorded.
            assert self.asked.setdefault(body["idempotency_key"], body) == body
            for person in body["people"]:
                self.chosen[person] = body["model"]
            return {"recorded": True}
        if (method, path) == ("GET", "/world/versions/version-1/society/models"):
            stored = {**self.chosen, **self.read_back}
            return {
                "choices": [{"subject_id": s, "model": m} for s, m in stored.items()],
                "host_refusal": None,
            }
        raise AssertionError(f"the builder called {method} {path}")


def test_the_builder_places_every_thing_bound_to_the_saved_world_and_a_second_run_places_none():
    builder = _builder()
    scene = builder.read_scene(_scenes()[0])
    server = _Server()
    record = builder.build(server, scene)
    assert [t["thing_id"] for t in server.things] == [t["thing_id"] for t in scene["things"]]
    assert len(server.bound) == len(scene["things"])
    assert record["things_added"] == len(scene["things"])
    assert record["edit_seq"] == len(scene["things"])
    again = builder.build(server, scene)
    assert again["things_added"] == 0 and server.edits == len(scene["things"])


def test_the_builder_refuses_a_thing_already_placed_as_something_else():
    builder = _builder()
    scene = builder.read_scene(_scenes()[0])
    server = _Server()
    builder.build(server, scene)
    server.things[0]["transform"] = dict(server.things[0]["transform"], x_mm=999_999)
    with pytest.raises(builder.SceneRefused, match="as something else"):
        builder.build(server, scene)


def test_the_builder_chooses_each_being_s_mind_and_a_second_run_asks_for_the_same():
    builder = _builder()
    scene = builder.read_scene(_scenes()[0])
    server = _Server()
    record = builder.build(server, scene)
    society = builder.bring_to_life(server, scene, record)
    assert society["engine"] == scene["engine"] and society["society_id"] == "society-1"
    wanted = {
        mind["thing_id"]: {k: mind["decider"][k] for k in ("provider", "model_id")}
        for mind in scene["minds"]
    }
    assert {f"person:{thing}": model for thing, model in wanted.items()} == server.chosen
    assert {m["thing_id"]: m["model"] for m in society["minds"]} == wanted
    keys = set(server.asked)
    assert len(keys) == len(scene["minds"])
    assert builder.bring_to_life(server, scene, record) == society
    assert set(server.asked) == keys  # the same choices, under the same keys


def test_the_builder_refuses_another_engine_and_a_mind_that_reads_back_as_another():
    builder = _builder()
    scene = builder.read_scene(_scenes()[0])
    server = _Server()
    record = builder.build(server, scene)
    builder.bring_to_life(server, scene, record)  # the positive control
    knight = next(m for m in scene["minds"] if m["thing_id"] == "knight")
    server.read_back[f"person:{knight['thing_id']}"] = None
    with pytest.raises(builder.SceneRefused, match="knight's mind reads back as another"):
        builder.bring_to_life(server, scene, record)
    elsewhere = _Server()
    elsewhere.engine = "exulanica-society/v2"
    with pytest.raises(builder.SceneRefused, match="runs exulanica-society/v2"):
        builder.bring_to_life(elsewhere, scene, builder.build(elsewhere, scene))
