"""A scene laid into a saved world by a server's scene dressing, against PostgreSQL.

What is shown, with the application a deployment runs and as the world's owner:

*   a starter dressed with the shipped scene holds each of its things where the demo builder, from
    outside, would place them, in the arrival's region, authored as fictional and placed by the
    owner, bound to the saved entry so the world reopens there; the society is made on the scene's
    engine and each being's mind is the scene's, read back through the models route and chosen
    under the key the builder chooses it under; dressing again places nothing and records no new
    choice;
*   a generated town is dressed from its own arrival, in its own region, and a scene laid out for a
    starter is refused there by name;
*   the owner's own edits stand when the world is dressed again: a thing moved stays where the owner
    put it, a thing removed stays removed and a placing undone stays out, each listed, and a thing
    placed again after an undo and then removed is listed as removed; only a thing of another kind
    under the scene's id is refused, by name, and nothing more is placed; a saved
    world that does not reopen at its version, after an edit not bound to it, is refused by name;
*   an edit refused part way comes back by the code the authored-edit routes answer with, and the
    world reopens with what was placed before it;
*   a society refusal keeps the things and comes back by its code: a host that does not offer the
    engine, and one with no adapter for a society's first input;
*   a model the people role does not take is refused for that being alone, and so is one the
    manifest does not offer for a choice that takes a line, as a society of things asks its people;
    the others are chosen;
*   another workspace's session cannot reach the owner's world, and a connection already inside a
    transaction is refused before anything is read.
"""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.api.scene_dressing import dress_saved_world
from exulanica.api.society_making import SocietyHooks
from exulanica.models.manifest import load_manifest
from exulanica.selection.validation import Session
from exulanica.world import object_repository
from exulanica.world.scenes import SceneRefused, read_scene, shipped_scenes

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_scene", ROOT / "scripts/demo/build_scene.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scene"] = module
    spec.loader.exec_module(module)
    return module


def _offer(api, offered: bool = True) -> None:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=offered
    )


def _scene():
    """The newest shipped scene laid out for a starter, the one a starter is dressed with now."""
    starters = {key: scene for key, scene in shipped_scenes().items() if scene.ground == "starter"}
    return starters[max(starters)]


def _starter(api) -> dict:
    made = api.post("/world-entries/starter", {"title": "Three strangers"})
    assert made.status_code == 200, made.text
    return made.json()


def _dress(api, entry: dict, scene, *, session=None, workspace=None):
    """The dressing as a server runs it: the application's own hooks, the workspace's idle
    connection and the owner's session."""
    workspace = workspace or api.repository.workspace_id
    session = session or Session(workspace_id=workspace, actor=api.actor)
    with api.database.session(workspace) as connection:
        return dress_saved_world(
            SocietyHooks.of_app(api.client.app),
            connection,
            session,
            uuid.UUID(entry["entry_id"]),
            scene,
        )


def _choices(api) -> int:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select count(*) n from world_society_model_choice where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchone()["n"]


def _keys(api) -> set[uuid.UUID]:
    with api.database.session(api.repository.workspace_id) as connection:
        rows = connection.execute(
            "select request_id from world_society_model_choice where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchall()
    return {row["request_id"] for row in rows}


def _models(api, entry: dict) -> dict:
    read = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/models"
        f"?world_id={entry['world_id']}"
    )
    assert read.status_code == 200, read.text
    return {choice["subject_id"]: choice["model"] for choice in read.json()["choices"]}


def _edit(api, entry: dict, path: str, *, bound: bool = True, **body):
    """An authored edit through the things routes, bound to the saved entry as the app binds it
    unless ``bound`` is false."""
    reopened = api.entry(entry["entry_id"])
    binding = {
        "saved_entry": {
            "entry_id": entry["entry_id"],
            "base_revision": reopened["revision"],
            "authored_state_sha256": reopened["authored_state_sha256"],
            "authored_edit_seq": reopened["authored_edit_seq"],
        }
    }
    answer = api.post(
        f"/world/versions/{entry['authored_version_id']}/things{path}?world_id={entry['world_id']}",
        {
            "base_state_sha256": api.version(entry)["state_sha256"],
            **(binding if bound else {}),
            **body,
        },
    )
    assert answer.status_code in (200, 201), answer.text
    return answer.json()


def test_a_starter_dressed_with_a_scene_holds_it_bound_to_its_entry_and_lives(made):
    api = made
    _offer(api)
    scene = _scene()
    entry = _starter(api)
    dressed = _dress(api, entry, scene)

    things = scene.document["things"]
    assert dressed.things_added == len(things)
    assert dressed.things_left_moved == dressed.things_left_removed == ()
    assert dressed.things_left_undone == ()
    reopened = api.entry(entry["entry_id"])
    assert (reopened["authored_state_sha256"], reopened["authored_edit_seq"]) == (
        dressed.state_sha256,
        dressed.edit_seq,
    )
    # Each thing where the demo builder, which shares no code with this, places it from outside,
    # in the arrival's region, authored as fictional and placed by the owner.
    arrival = _builder().arrival_of(reopened)
    version = api.version(entry)
    stored = {t["thing_id"]: t for t in version["things"] if not t["removed"]}
    assert set(stored) == {thing["thing_id"] for thing in things}
    for thing in things:
        held = stored[thing["thing_id"]]
        assert (held["kind"]["kind"], held["kind"]["version"]) == (
            thing["kind"]["kind"],
            thing["kind"]["version"],
        )
        assert held["region_id"] == arrival.region_id
        assert held["origin"] == {"kind": "authored", "role": "fictional"}
        pose = {key: held["transform"][key] for key in ("x_mm", "y_mm", "z_mm", "yaw_microradians")}
        assert pose == arrival.pose(thing["place"]), thing["thing_id"]
    placing = [edit for edit in version["edits"] if edit["kind"] == "add_thing"]
    assert len(placing) == len(things)
    assert {edit["actor"] for edit in placing} == {str(api.actor)}

    assert dressed.society["engine"] == scene.document["engine"]
    assert dressed.society["refused"] is None
    wanted = {
        mind["thing_id"]: {k: mind["decider"][k] for k in ("provider", "model_id")}
        for mind in scene.document["minds"]
    }
    assert {mind["thing_id"]: mind["model"] for mind in dressed.minds} == wanted
    assert [mind["refused"] for mind in dressed.minds] == [None] * len(wanted)
    held_models = _models(api, entry)
    for mind in dressed.minds:
        chosen = held_models[mind["person_id"]]
        assert {k: chosen[k] for k in ("provider", "model_id")} == mind["model"]
    with api.database.session(api.repository.workspace_id) as connection:
        chosen_by = connection.execute(
            "select distinct chosen_by from world_society_model_choice where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchall()
    assert [row["chosen_by"] for row in chosen_by] == [api.actor]
    # Each mind under the key the demo builder chooses it under, so a world either of them dressed
    # is answered with the choice already recorded.
    builder = _builder()
    society_id = dressed.society["society_id"]
    assert _keys(api) == {
        builder.mind_key(scene.sha256, society_id, mind["thing_id"])
        for mind in scene.document["minds"]
    }

    recorded = _choices(api)
    again = _dress(api, entry, scene)
    assert again.things_added == 0
    assert again.society["society_id"] == dressed.society["society_id"]
    assert again.minds == dressed.minds
    assert _choices(api) == recorded


def test_a_thing_of_another_kind_is_refused_by_name_and_nothing_more_is_placed(made):
    api = made
    _offer(api)
    scene = _scene()
    entry = _starter(api)
    first = scene.document["things"][0]
    other = next(t for t in scene.document["things"] if t["kind"]["kind"] != first["kind"]["kind"])
    version = api.version(entry)
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/things?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "thing_id": first["thing_id"],
            "kind": other["kind"],
            "region_id": "region:starter",
            "pose": {"x_mm": 123, "y_mm": 0, "z_mm": 456, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    with pytest.raises(SceneRefused) as refused:
        _dress(api, entry, scene)
    assert refused.value.code == "scene_thing_placed_otherwise"
    assert [t["thing_id"] for t in api.version(entry)["things"]] == [first["thing_id"]]


def test_the_owner_s_moves_removals_and_undos_stand_when_the_world_is_dressed_again(made):
    api = made
    _offer(api)
    scene = _scene()
    entry = _starter(api)
    _dress(api, entry, scene)
    things = scene.document["things"]
    moved, gone = things[0]["thing_id"], things[1]["thing_id"]
    # Undo is a stack: the first undo takes back the last thing's placing and the second the one
    # before it, which the owner then places again and removes. That one was removed, not undone.
    undone, again_placed = things[-1]["thing_id"], things[-2]
    _edit(api, entry, "/undo")
    _edit(api, entry, "/undo")
    _edit(
        api,
        entry,
        "",
        thing_id=again_placed["thing_id"],
        kind=again_placed["kind"],
        region_id=_builder().arrival_of(api.entry(entry["entry_id"])).region_id,
        pose={"x_mm": 3_000, "y_mm": 0, "z_mm": 3_000, "yaw_microradians": 0},
        origin_role="fictional",
    )
    _edit(api, entry, f"/{again_placed['thing_id']}/remove")
    _edit(
        api,
        entry,
        f"/{moved}/move",
        pose={"x_mm": 7_000, "y_mm": 0, "z_mm": 1_000, "yaw_microradians": 0},
    )
    _edit(api, entry, f"/{gone}/remove")
    again = _dress(api, entry, scene)
    assert again.things_added == 0
    assert again.things_left_moved == (moved,)
    assert again.things_left_removed == (gone, again_placed["thing_id"])
    assert again.things_left_undone == (undone,)
    held = {thing["thing_id"]: thing for thing in api.version(entry)["things"]}
    assert held[moved]["transform"]["x_mm"] == 7_000
    assert held[gone]["removed"] is True
    assert held[again_placed["thing_id"]]["removed"] is True
    assert undone not in held


def test_a_saved_world_that_does_not_reopen_at_its_version_is_refused_by_name(made):
    api = made
    _offer(api)
    scene = _scene()
    entry = _starter(api)
    _dress(api, entry, scene)
    moved = scene.document["things"][0]["thing_id"]
    # An edit not bound to the saved entry: the version moves on and the entry does not.
    _edit(
        api,
        entry,
        f"/{moved}/move",
        bound=False,
        pose={"x_mm": 7_000, "y_mm": 0, "z_mm": 1_000, "yaw_microradians": 0},
    )
    with pytest.raises(SceneRefused) as refused:
        _dress(api, entry, scene)
    assert refused.value.code == "scene_world_moved"


def test_an_edit_refused_part_way_comes_back_by_its_code_and_the_world_reopens_with_it(
    made, monkeypatch
):
    api = made
    _offer(api)
    monkeypatch.setattr(object_repository, "PLACED_THINGS_MAXIMUM", 3)
    scene = _scene()
    entry = _starter(api)
    with pytest.raises(SceneRefused) as refused:
        _dress(api, entry, scene)
    assert refused.value.code == "thing_limit_reached"
    version = api.version(entry)
    assert {t["thing_id"] for t in version["things"]} == {
        t["thing_id"] for t in scene.document["things"][:3]
    }
    assert api.entry(entry["entry_id"])["authored_state_sha256"] == version["state_sha256"]


def test_a_generated_town_is_dressed_from_its_own_arrival_in_its_own_region(made):
    api = made
    # The town's society is not the subject here: a host that does not offer the engine answers
    # before anything is read.
    _offer(api, offered=False)
    document = copy.deepcopy(dict(_scene().document))
    document["ground"]["kind"] = "generated"
    scene = read_scene(document)
    town = api.post("/worlds/generated", {"recipe": "small_town", "title": "A dressed town"})
    assert town.status_code == 201, town.text
    entry = town.json()
    dressed = _dress(api, entry, scene)
    assert dressed.things_added == len(document["things"])
    reopened = api.entry(entry["entry_id"])
    arrival = _builder().arrival_of(reopened)
    assert arrival.region_id == reopened["generated_ground"]["region_id"] != "region:starter"
    stored = {t["thing_id"]: t for t in api.version(entry)["things"] if not t["removed"]}
    for thing in document["things"]:
        held = stored[thing["thing_id"]]
        assert held["region_id"] == arrival.region_id
        pose = {key: held["transform"][key] for key in ("x_mm", "y_mm", "z_mm", "yaw_microradians")}
        assert pose == arrival.pose(thing["place"]), thing["thing_id"]
    with pytest.raises(SceneRefused) as refused:
        _dress(api, entry, _scene())
    assert refused.value.code == "scene_ground_mismatch"


def test_a_host_that_does_not_offer_the_engine_keeps_the_things_and_says_why(made):
    api = made
    _offer(api, offered=False)
    scene = _scene()
    entry = _starter(api)
    dressed = _dress(api, entry, scene)
    assert dressed.things_added == len(scene.document["things"])
    assert dressed.society == {
        "society_id": None,
        "engine": scene.document["engine"],
        "state_sha256": None,
        "refused": "society_engine_not_offered",
    }
    assert dressed.minds == ()


def test_a_society_with_no_first_input_is_refused_by_its_code_and_the_things_kept(
    made, monkeypatch
):
    api = made
    _offer(api)
    monkeypatch.setattr(api.client.app.state, "society_initial_input", None)
    scene = _scene()
    entry = _starter(api)
    dressed = _dress(api, entry, scene)
    assert dressed.things_added == len(scene.document["things"])
    assert dressed.society["refused"] == "unavailable_society_input"
    assert dressed.society["society_id"] is None
    assert dressed.minds == ()


def test_a_model_the_role_does_not_take_is_refused_for_that_being_alone(made):
    api = made
    _offer(api)
    document = copy.deepcopy(dict(_scene().document))
    # Declared by the manifest, so the scene reads, but not verified to answer a person's choice.
    unverified = [
        spec
        for _, spec in sorted(load_manifest().models.items())
        if spec.is_chat and not spec.answering
    ]
    assert unverified, "the positive control: the manifest declares a chat model nobody verified"
    document["minds"][0]["decider"].update(
        provider=unverified[0].provider, model_id=unverified[0].model_id
    )
    scene = read_scene(document)
    dressed = _dress(api, _starter(api), scene)
    by_thing = {mind["thing_id"]: mind for mind in dressed.minds}
    first = document["minds"][0]["thing_id"]
    assert by_thing[first]["refused"] == "model_not_offered"
    assert all(by_thing[m["thing_id"]]["refused"] is None for m in document["minds"][1:])


def test_a_model_not_offered_for_lines_is_refused_for_that_being_alone(made):
    api = made
    _offer(api)
    # Offered to people elsewhere, but not for a choice that takes a line, which a society of
    # things asks its people; the manifest says which models.
    unfit = [
        spec for _, spec in sorted(load_manifest().models.items()) if spec.not_offered_for_lines
    ]
    assert unfit, "the positive control: the manifest names a model not offered for lines"
    document = copy.deepcopy(dict(_scene().document))
    document["minds"][0]["decider"].update(provider=unfit[0].provider, model_id=unfit[0].model_id)
    scene = read_scene(document)
    dressed = _dress(api, _starter(api), scene)
    by_thing = {mind["thing_id"]: mind for mind in dressed.minds}
    first = document["minds"][0]["thing_id"]
    assert by_thing[first]["refused"] == "model_not_askable"
    assert all(by_thing[m["thing_id"]]["refused"] is None for m in document["minds"][1:])


def test_another_workspace_cannot_dress_the_owner_s_world_nor_a_busy_connection(made):
    api = made
    _offer(api)
    scene = _scene()
    entry = _starter(api)
    stranger = uuid.uuid4()
    with pytest.raises(SceneRefused) as refused:
        _dress(api, entry, scene, workspace=stranger)
    assert refused.value.code == "scene_world_unknown"
    workspace = api.repository.workspace_id
    session = Session(workspace_id=workspace, actor=api.actor)
    with (
        api.database.session(workspace) as connection,
        connection.transaction(),
        pytest.raises(RuntimeError, match="idle connection"),
    ):
        dress_saved_world(
            SocietyHooks.of_app(api.client.app),
            connection,
            session,
            uuid.UUID(entry["entry_id"]),
            scene,
        )
    assert [t for t in api.version(entry)["things"]] == []
