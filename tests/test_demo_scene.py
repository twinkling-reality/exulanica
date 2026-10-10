"""The demo's scenes: data the product's own routes can build, and a builder that names no scene.

What is shown here, with no database and no server:

*   every scene document under ``scripts/demo/scenes`` and in the scene catalog
    (``assets/catalogs/scenes``) names only shipped thing kinds at shipped versions, places
    each thing once, and chooses minds only for its own beings and only open models the model
    manifest serves; a scene's travellers reach the build record, and a gate it lacks is refused;
*   the newest version of each scene, the one a rehearsal builds, chooses only a decider each
    being's kind allows and only models its engine offers to a being's decisions, as the society's
    model choice route requires, and so does the mind it gives the travellers its gate lets in;
    older versions stay as published for the records naming them;
*   a place stated from where a person arrives becomes the same pose in any world's frame: on a
    starter (the spawn faces north) and for an arrival facing east, checked against arithmetic done
    here rather than the builder's;
*   against a server played here, the builder places every thing bound to the saved world, a
    second run places nothing, and a thing already placed as something else is refused by name;
*   it then starts the scene's society and chooses each being's mind under keys a second run asks
    with again, and refuses a society on another engine or a mind that reads back as another;
*   on a world whose things a person placed (the Companion's own ids), the society starter places
    nothing, starts the scene's society, records the travellers coming through the world's own
    gate and each placed being with the mind read back for it, and refuses a world with two gates.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.decision_roles import decision_roles

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "scripts/demo/scenes"
#: The scene catalog the product ships (exulanica.scene/v1), which the builder reads too.
CATALOG = ROOT / "assets/catalogs/scenes"
MANIFEST = ROOT / "exulanica/models/models.manifest.json"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_scene", ROOT / "scripts/demo/build_scene.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scene"] = module
    spec.loader.exec_module(module)
    return module


def _starter():
    """The society starter, bound to the builder ``_builder`` loaded last."""
    spec = importlib.util.spec_from_file_location(
        "start_society", ROOT / "scripts/demo/start_society.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scenes() -> list[Path]:
    return sorted(SCENES.glob("*.json"))


def _all_scenes() -> list[Path]:
    """The demo's scenes and the catalog's, every one the builder may be given."""
    return _scenes() + sorted(CATALOG.glob("*.v*.json"))


def test_scenes_ship():
    assert _scenes()


@pytest.mark.parametrize("path", _all_scenes(), ids=lambda path: path.name)
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


def _newest_scenes() -> list[Path]:
    """The newest version of each scene, by the version its document states."""
    newest: dict[str, tuple[int, Path]] = {}
    for path in _all_scenes():
        scene = json.loads(path.read_text(encoding="utf-8"))
        held = newest.get(scene["scene"])
        if held is None or scene["version"] > held[0]:
            newest[scene["scene"]] = (scene["version"], path)
    return sorted(path for _, path in newest.values())


@pytest.mark.parametrize("path", _newest_scenes(), ids=lambda path: path.name)
def test_a_scene_s_newest_version_chooses_minds_its_engine_offers(path):
    scene = _builder().read_scene(path)
    hosted = [role for role in decision_roles() if role.chosen and role.hosted_by(scene["engine"])]
    assert len(hosted) == 1, "the engine hosts one role a chosen model decides for, its people's"
    offered = {spec.model_id for spec in load_manifest().offered_models(hosted[0].chosen)}
    kinds = {thing["thing_id"]: thing["kind"] for thing in scene["things"]}
    shipped = shipped_thing_kinds()
    for mind in scene["minds"]:
        kind = shipped[(kinds[mind["thing_id"]]["kind"], kinds[mind["thing_id"]]["version"])]
        assert mind["decider"]["kind"] in kind.document["deciders"]["allowed"], mind["thing_id"]
        if mind["decider"]["kind"] == "model":
            assert mind["decider"]["model_id"] in offered, mind["thing_id"]
    # A gate's travellers are decided as the world's own beings are: the grant names this mind.
    model = (scene.get("travellers") or {}).get("model")
    if model is not None:
        assert model["model_id"] in offered, "the travellers' mind"


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
    # A turn of 0 faces the person arriving; a turn of pi faces the way they face.
    facing_their_way = dict(place, turn_microradians=3_141_593)
    assert town.pose(facing_their_way)["yaw_microradians"] == 1_570_797


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
        if (method, path) == ("GET", "/world-entries"):
            return [copy.deepcopy(self.entry)]
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
                # A shipped being, or a creature its workspace keeps (always a being).
                if thing["kind"].get("kind") in self.beings
                or thing["kind"].get("source") == "workspace"
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


def test_the_builder_records_the_travellers_a_scene_names_and_refuses_a_gate_it_lacks(tmp_path):
    builder = _builder()
    catalogued = next(
        path
        for path in _all_scenes()
        if path.parent == CATALOG
        and json.loads(path.read_text(encoding="utf-8"))["ground"]["kind"] == "starter"
    )
    scene = builder.read_scene(catalogued)
    assert "travellers" in scene, "the positive control: the catalog's scene names its travellers"
    # Whoever opens the gate reads them from the record; the builder opens none.
    assert builder.build(_Server(), scene)["travellers"] == scene["travellers"]
    assert "travellers" not in builder.build(_Server(), builder.read_scene(_scenes()[0]))
    stray = dict(scene, travellers=dict(scene["travellers"], gate="nowhere"))
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(stray), encoding="utf-8")
    with pytest.raises(builder.SceneRefused, match="lacks"):
        builder.read_scene(path)


def test_a_society_started_on_a_world_a_person_placed_places_nothing_and_takes_its_own_gate():
    builder = _builder()
    starter = _starter()
    scene = builder.read_scene(
        next(
            path
            for path in reversed(_newest_scenes())
            if path.parent == CATALOG
            and json.loads(path.read_text(encoding="utf-8"))["ground"]["kind"] == "starter"
        )
    )
    assert scene["travellers"]["gate"], "the positive control: the scene lets travellers in"
    server = _Server()
    # The person placed the scene's kinds through the Companion: its own ids, its own layout.
    for index, thing in enumerate(scene["things"]):
        server.things.append(
            {
                "thing_id": f"companion:{thing['kind']['kind']}:{index:012x}",
                "kind": {**thing["kind"], "sha256": "f" * 64},
                "region_id": "region:starter",
                "transform": {"x_mm": 1_000 * index, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0},
                "removed": False,
            }
        )
    record = starter.start(server, scene)
    assert server.bound == [] and server.edits == 0, "nothing is placed"
    assert record["placed_by"] == "person" and record["society"]["engine"] == scene["engine"]
    assert [t["thing_id"] for t in record["things"]] == [t["thing_id"] for t in server.things]
    gate_kind = next(
        t["kind"]["kind"] for t in scene["things"] if t["thing_id"] == scene["travellers"]["gate"]
    )
    world_gate = next(t["thing_id"] for t in server.things if t["kind"]["kind"] == gate_kind)
    assert record["travellers"] == {**scene["travellers"], "gate": world_gate}
    beings = sorted(t["thing_id"] for t in server.things if t["kind"]["kind"] in server.beings)
    assert beings, "the positive control: the person placed beings"
    assert {m["thing_id"]: m["model"] for m in record["society"]["minds"]} == dict.fromkeys(beings)
    # A mind the person chose in Who decides is in the record made after it.
    chosen = {"provider": "nebius_token_factory", "model_id": "a-model"}
    server.chosen[f"person:{beings[0]}"] = chosen
    again = starter.start(server, scene)
    assert {m["thing_id"]: m["model"] for m in again["society"]["minds"]}[beings[0]] == chosen
    second_gate = {**server.things[0], "thing_id": "companion:another"}
    second_gate["kind"] = {**second_gate["kind"], "kind": gate_kind}
    server.things.append(second_gate)
    with pytest.raises(starter.SceneRefused, match=f"a {gate_kind}, and the world holds 2"):
        starter.start(server, scene)


def test_a_world_that_holds_a_creature_made_from_words_is_dressed_and_started_as_any_other():
    """A thing of a kind its workspace keeps is named by its digest alone
    (``{source: workspace, sha256}``), with no kind key. The builder leaves it be, the society is
    started over it, it is nobody's gate, and the record lists it as the version stores it."""
    builder = _builder()
    starter = _starter()
    scene = builder.read_scene(
        next(
            path
            for path in reversed(_newest_scenes())
            if path.parent == CATALOG
            and json.loads(path.read_text(encoding="utf-8"))["ground"]["kind"] == "starter"
        )
    )
    assert scene["travellers"]["gate"], "the positive control: the scene lets travellers in"
    creature = {
        "thing_id": "creature:0123abcd",
        "kind": {"source": "workspace", "sha256": "c" * 64},
        "region_id": "region:starter",
        "transform": {"x_mm": 7_000, "y_mm": 0, "z_mm": 9_000, "yaw_microradians": 0},
        "removed": False,
    }
    server = _Server()
    server.things.append(copy.deepcopy(creature))
    built = builder.build(server, scene)
    assert built["things_added"] == len(scene["things"])
    record = starter.start(server, scene)
    assert [t["kind"] for t in record["things"] if t["thing_id"] == creature["thing_id"]] == [
        creature["kind"]
    ]
    # The society's record names it among the beings, as the server lists it among the people.
    assert creature["thing_id"] in [mind["thing_id"] for mind in record["society"]["minds"]]
    assert record["travellers"]["gate"] == scene["travellers"]["gate"]
    # A scene thing's own id already taken by a made creature is something else, said so.
    taken = _Server()
    taken.things.append({**copy.deepcopy(creature), "thing_id": scene["things"][0]["thing_id"]})
    with pytest.raises(builder.SceneRefused, match="is placed already, as something else"):
        builder.build(taken, scene)


def test_a_refusal_names_its_code_or_what_the_request_check_refused():
    refusal = _builder().refusal
    assert refusal("POST", "/x", 409, {"code": "thing_kind_unshipped"}) == (
        "POST /x: 409 thing_kind_unshipped"
    )
    conflict = {"code": "saved_world_conflict", "detail": "the starter has another title"}
    assert refusal("POST", "/x", 409, conflict) == (
        "POST /x: 409 saved_world_conflict (the starter has another title)"
    )
    detail = {"detail": [{"loc": ["body", "profile"], "msg": "Input should be 'v1'", "type": "e"}]}
    assert refusal("POST", "/x", 422, detail) == "POST /x: 422 body.profile: Input should be 'v1'"
    assert refusal("GET", "/x", 500, "not json") == "GET /x: 500"
