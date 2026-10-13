"""A world made from a world kind lives as a society of things, as a deployment stores it.

A farm with a creature placed on it: the farm's own people are villagers with homes and jobs made
from the site's own place, the creature is a being among them and acts, a being placed inside a
barn is refused a place to stand, the creature leaves the minute after its kind is erased, and the
stored minutes replay. Each world is made under a fixed identity, so it is the same site on every
run, and where a thing is placed is read from that site's own records.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.api import society_runtime as runtime_module
from exulanica.api.routes import thing_store as thing_store_route
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.grammar.grammars.site.records import SiteStructureRecord
from exulanica.selection.validation import Session
from exulanica.world import saved_entries
from exulanica.world.composers import composer_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.worker import JobOutcome, Kept, kind_worker
from exulanica.world.society_engines import CREATES, CREATES_HOLDING_THINGS
from exulanica.world.thing_store import ThingStore

from personal_world_support import OWNER_TOKEN
from test_society_made_kinds import canary_creature
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SITE = composer_module("site-plan", 1)
V7 = "exulanica-society/v7"
V3 = "exulanica.society-input/walking-surfaces-v3"
#: The identity each site here is made under.
FARM = "world:generated:00000000-0000-4000-8000-00000000f001"
CREATURE = "creature:7c0e51aa"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_site_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)


def _uploaded(name: str) -> dict[str, Any]:
    document = json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))
    document["origin"] = "uploaded"
    document["provenance"] = {"by": "a test creator"}
    return document


def _site(api, name: str, kind: str, preset: str) -> tuple[dict[str, Any], str, tuple[object, ...]]:
    """A site world made from a fixture kind under the fixed identity: its entry, its society
    route, and the records the same kind composes for that identity, read here from the kind."""
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    kept = api.post("/worlds/kinds", {"document": _uploaded(name)})
    assert kept.status_code == 201, kept.text
    made_world = api.post(f"/worlds/kinds/{kind}/worlds", {"preset": preset, "title": "A site"})
    assert made_world.status_code == 201, made_world.text
    entry = made_world.json()
    assert entry["world_id"] == FARM
    read = read_kind(_uploaded(name))
    records = SITE.compose_kind(read, read.values(preset), FARM).records
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    return entry, society, records


def _keep_creature(api, tmp_path):
    creature = canary_creature("crocodile", hands=True)
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )
    return creature


def _place(api, entry: dict, thing_id: str, kind: dict, x_mm: int, z_mm: int) -> None:
    root = f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    base = api.get(root).json()["state_sha256"]
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/things?world_id={entry['world_id']}",
        {
            "base_state_sha256": base,
            "thing_id": thing_id,
            "kind": kind,
            "region_id": "region:generated",
            "pose": {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _input(api, entry: dict, seq: int) -> dict:
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=%s",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"], seq),
        ).fetchone()["document"]


def _step(api, entry: dict, body: dict) -> dict:
    stepped = api.post(
        f"/world/versions/{entry['authored_version_id']}/society/steps?world_id={entry['world_id']}",
        {"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _replayed(api, entry: dict) -> bool:
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    return replayed.json()["replay_verified"]


def test_a_made_creature_placed_on_a_farm_acts_among_the_farm_s_own_people(made, tmp_path):
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    # With nothing placed the farm is the living town's, as it was.
    assert entry["society_engine"] == CREATES["town"]
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    # A version holding a thing its author placed is a society of things on a site too, and both
    # reads a page creates from say so once the thing is placed.
    assert CREATES_HOLDING_THINGS is not None and CREATES_HOLDING_THINGS.engine == V7
    assert api.entry(entry["entry_id"])["society_engine"] == V7
    stated = api.get(
        f"/world/versions/{entry['authored_version_id']}/capabilities?world_id={entry['world_id']}"
    )
    assert stated.status_code == 200, stated.text
    assert stated.json()["society"] == {"held": False, "engine": V7}
    refused = api.post(society, {"region_id": "region:generated", "profile": CREATES["town"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "society_engine_differs"
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    state = body["state"]
    first = _input(api, entry, 1)
    assert first["profile"] == V3
    assert first["navigation"]["profile"] == "site-walking-surfaces/v1"
    assert {ref["kind"] for ref in first["dependency_refs"]} >= {"site_place", "made_thing_kind"}
    # The farm's own people: villagers made from the site's place, with homes and jobs, and a
    # farmer's job is at a field, which is an area of the site and no building.
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    frame = first["people"]
    assert frame["population"] == first["population"]["size"] == len(villagers) > 0
    premises = state["people"]["premises"]
    working = [v["resident"]["job"] for v in villagers if v["resident"]["job"] is not None]
    assert working and len(working) <= sum(len(row["positions"]) for row in frame["premises"])
    assert {premises[job["premises"]]["subject_id"].split(":")[0] for job in working} <= {
        "site.area",
        "site.structure",
    }
    assert any(row["subject_id"].startswith("site.area:") for row in frame["premises"])
    # The creature is a being among them, of the kind its maker made, and it acts: within twenty
    # minutes it has chosen something to do and moved or stayed by the routine.
    [being] = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
    assert being["kind"] == {"source": "workspace", "sha256": creature.kind.sha256}
    assert list(state["kinds"]) == [creature.kind.sha256]
    doing = set()
    for _ in range(20):
        body = _step(api, entry, body)
        [now] = [p for p in body["state"]["inhabitants"] if p["id"] == being["id"]]
        doing.add(now["action"]["kind"])
    assert doing - {"idle"}, doing
    assert _replayed(api, entry) is True


def test_a_well_inside_a_barn_offers_nobody_a_place_and_one_in_the_open_does(made):
    """What is built on a site is kept clear of: the places people would stand at to use a thing
    are held to the site's own blocked ground, which only its records state. A well placed in the
    middle of a barn has no place a person can stand at, so nobody is sent to it; the same well
    in the open is somewhere to go."""
    api = made
    entry, society, records = _site(api, "farm", "fixture_farm", "small_farm")
    # A barn's centre, read from the site's own records (east and north from its south-west
    # corner) and stated in the region's frame, whose third figure runs south.
    barn = next(r for r in records if isinstance(r, SiteStructureRecord))
    inside = ((barn.min_x_mm + barn.max_x_mm) // 2, -((barn.min_y_mm + barn.max_y_mm) // 2))
    east, _height, south = entry["generated_site"]["arrival_mm"]
    well = {"kind": "well", "version": 2}
    _place(api, entry, "well-indoors", well, *inside)
    _place(api, entry, "well-outdoors", well, east + 3_000, south)
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    first = _input(api, entry, 1)
    reached = {target["subject_id"] for target in first["targets"]}
    refused = {row["subject_id"]: row["reason"] for row in first["unavailable_affordances"]}
    assert "thing:well-outdoors" in reached, (sorted(reached), refused)
    assert "thing:well-indoors" not in reached, sorted(reached)
    assert refused.get("thing:well-indoors") == "authored_affordance_unreachable", refused
    assert "thing:well-outdoors" not in refused


def test_the_creature_leaves_the_minute_after_its_kind_is_erased(made, tmp_path):
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    [being] = [p for p in body["state"]["inhabitants"] if p["came_by"] == "placed"]
    for _ in range(3):
        body = _step(api, entry, body)
    erased = api.client.delete(
        f"/things/kinds/{creature.kind.sha256}",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )
    assert erased.status_code == 204, erased.text
    body = _step(api, entry, body)
    assert all(p["id"] != being["id"] for p in body["state"]["inhabitants"])
    assert "kinds" not in body["state"]
    for _ in range(2):
        body = _step(api, entry, body)
    assert _replayed(api, entry) is True
    assert uuid.UUID(body["society_id"])


def _the_worker_keeps_nothing(monkeypatch) -> None:
    """As after the server started again, or once other sites' places pushed this one out: the kind
    worker keeps no place. And a place takes time to make: an ask that will not wait finds it no
    nearer made, however often it asks, so only an ask that waits gets one. Without that a test
    here would pass on a worker that happened to finish between two asks."""
    worker = kind_worker()
    monkeypatch.setattr(worker, "places", Kept(16, copies=True))
    run = worker.run

    def only_when_waited_for(key: str, seconds: float, *args: Any, **kwargs: Any) -> JobOutcome:
        if key.startswith("place:") and seconds == 0:
            return JobOutcome("overran")
        return run(key, seconds, *args, **kwargs)

    monkeypatch.setattr(worker, "run", only_when_waited_for)


def test_an_edit_of_a_farm_of_things_is_made_in_one_ask_after_the_worker_lost_its_place(
    made, tmp_path, monkeypatch
):
    """A society of things' input carries no place, so an edit composes its people's next input
    over the place the kind worker keeps. Where the worker keeps it no longer, the place is made
    and waited for before the edit's transaction, and the edit is made in the one ask."""
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    _the_worker_keeps_nothing(monkeypatch)
    # ``_place`` holds the answer to 201: a 503 asking to come back later would fail here.
    _place(api, entry, "well-later", {"kind": "well", "version": 2}, east + 3_000, south)
    second = _input(api, entry, 2)
    assert "thing:well-later" in {target["subject_id"] for target in second["targets"]}


def test_the_creature_leaves_after_its_kind_is_erased_though_the_worker_lost_the_place(
    made, tmp_path, monkeypatch
):
    """The erasure tells each society that runs a being of the kind by composing its next input.
    On a farm whose place the worker keeps no longer, the place is made before the telling, so the
    society is told then and there and the being leaves with its next minute."""
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    [being] = [p for p in body["state"]["inhabitants"] if p["came_by"] == "placed"]
    body = _step(api, entry, body)
    _the_worker_keeps_nothing(monkeypatch)
    # The wait for the place is bounded by the telling's budget, a couple of seconds as shipped.
    # This test is about the place, so it gives the telling the longest budget its reader admits
    # and does not depend on how fast a busy machine makes a place.
    monkeypatch.setattr(thing_store_route, "TELLING_SECONDS", 30)
    erased = api.client.delete(
        f"/things/kinds/{creature.kind.sha256}",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )
    assert erased.status_code == 204, erased.text
    # Told by the erasure itself: the input that leaves the creature out is recorded already.
    told = _input(api, entry, 2)
    assert "made_thing_kind" not in {ref["kind"] for ref in told["dependency_refs"]}
    body = _step(api, entry, body)
    assert all(p["id"] != being["id"] for p in body["state"]["inhabitants"])
    assert _replayed(api, entry) is True


def test_a_version_named_under_another_world_prepares_nothing(made, tmp_path, monkeypatch):
    """What is made ahead of an edit is found by the workspace, the world and the version together:
    a version another world holds is no society in the world named, so nothing is asked of the
    kind worker for it; named under its own world, the farm's place is asked for."""
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    worker = kind_worker()
    monkeypatch.setattr(worker, "places", Kept(16, copies=True))
    asked: list[str] = []
    run = worker.run

    def watched(key: str, seconds: float, *args: Any, **kwargs: Any) -> JobOutcome:
        asked.append(key.split(":")[0])
        return run(key, seconds, *args, **kwargs)

    monkeypatch.setattr(worker, "run", watched)
    runtime = api.client.app.state.services.society_runtime
    version = uuid.UUID(entry["authored_version_id"])
    workspace = api.repository.workspace_id
    session = Session(workspace_id=workspace, actor=api.actor)
    elsewhere = "world:generated:00000000-0000-4000-8000-00000000f002"
    assert elsewhere != entry["world_id"]
    with api.database.session(workspace) as connection:
        runtime.prepare_authored_edit(connection, session, elsewhere, version)
        assert asked == []
        runtime.prepare_authored_edit(connection, session, entry["world_id"], version)
        assert asked == ["place"]


def _erase_telling_nobody(api, sha256: str) -> None:
    """Erase the creature through the store alone, as the deployed role: the erasure's row and
    what its trigger deletes, and no society told, as an erasure whose telling reached nobody
    leaves it and as a restore's replay of one writes it."""
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, None).erase_creature(
            sha256, erased_by=api.actor
        )


def _a_farm_with_a_creature_nobody_told_is_erased(api, tmp_path, monkeypatch):
    """A farm of things with a made creature, one minute in; then the creature's kind erased with
    no society told and the kind worker keeping no place: the entry, the society's route, the
    society as read last, and the being."""
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    body = _step(api, entry, created.json())
    [being] = [p for p in body["state"]["inhabitants"] if p["came_by"] == "placed"]
    _erase_telling_nobody(api, creature.kind.sha256)
    _the_worker_keeps_nothing(monkeypatch)
    return entry, society, body, being


def _control_route(entry: dict) -> str:
    return f"/world/versions/{entry['authored_version_id']}/society/control"


def test_a_step_that_must_tell_a_farm_of_an_erasure_answers_the_first_time(
    made, tmp_path, monkeypatch
):
    """A society nobody told of an erasure composes its next input before its minute. On a farm
    whose place the worker keeps no longer the place is made in between and the minute asked once
    more, so the person's one step is answered and the being is gone with it."""
    api = made
    entry, _society, body, being = _a_farm_with_a_creature_nobody_told_is_erased(
        api, tmp_path, monkeypatch
    )
    # ``_step`` holds the answer to 200: a 503 asking to come back later would fail here.
    body = _step(api, entry, body)
    assert all(p["id"] != being["id"] for p in body["state"]["inhabitants"])
    assert _input(api, entry, 2)["things_gone"] == [CREATURE]
    assert _replayed(api, entry) is True


def test_a_manual_step_on_such_a_farm_answers_the_first_time_and_says_when_to_ask_again(
    made, tmp_path, monkeypatch
):
    api = made
    entry, _society, body, being = _a_farm_with_a_creature_nobody_told_is_erased(
        api, tmp_path, monkeypatch
    )
    route = f"{_control_route(entry)}/steps?world_id={entry['world_id']}"
    asked = {
        "base_revision": 0,
        "base_tick": body["current_tick"],
        "base_state_sha256": body["state_sha256"],
    }

    class Busy:
        """A kind worker that can take no job now."""

        places = Kept(1, copies=True)

        def run(self, *args: Any, **kwargs: Any) -> JobOutcome:
            return JobOutcome("busy")

    # Where the place cannot be made now, the step is not run and the answer says when to ask
    # again, as the society's own routes answer it.
    with monkeypatch.context() as while_busy:
        while_busy.setattr(runtime_module, "kind_worker", Busy)
        waiting = api.post(route, asked)
        assert waiting.status_code == 503, waiting.text
        assert waiting.json()["code"] == "kind_work_busy"
        assert waiting.headers["retry-after"] == "2"
    stepped = api.post(route, asked)
    assert stepped.status_code == 200, stepped.text
    assert all(p["id"] != being["id"] for p in stepped.json()["society"]["state"]["inhabitants"])
    assert _replayed(api, entry) is True


def test_a_playback_round_on_such_a_farm_tells_it_and_is_not_paused(made, tmp_path, monkeypatch):
    """The round's telling meets the place the worker keeps no longer, makes it, tells the society
    once more and runs the minute: the society goes on playing and the being is gone."""
    api = made
    entry, _society, _body, being = _a_farm_with_a_creature_nobody_told_is_erased(
        api, tmp_path, monkeypatch
    )
    workspace = api.repository.workspace_id
    control = f"{_control_route(entry)}?world_id={entry['world_id']}"
    played = api.put(control, {"base_revision": 0, "mode": "playing", "speed": 1})
    assert played.status_code == 200, played.text
    with api.database.session(workspace) as connection:
        # The society's next minute is due, as the passing of its interval makes it.
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp() - interval '1 second' "
            "where workspace_id=%s",
            (workspace,),
        )
    worker = SocietyControlWorker(
        api.database,
        runtime=api.client.app.state.services.society_runtime,
        workspaces=[workspace],
    )
    ran = worker.run_once(workspace)
    assert ran is not None and ran["receipt"]["executed_ticks"] == 1
    read = api.get(control)
    assert read.status_code == 200, read.text
    assert read.json()["mode"] == "playing", read.json()
    society = api.get(
        f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    )
    assert society.status_code == 200, society.text
    assert all(p["id"] != being["id"] for p in society.json()["state"]["inhabitants"])
    assert _input(api, entry, 2)["things_gone"] == [CREATURE]


def test_a_farm_s_living_people_take_a_creature_in_and_are_the_same_people(made, tmp_path):
    """A farm peopled before anything was placed on it is a living society. A creature placed
    after is taken in as on a town: the living society ends and a society of things is made on the
    same version, the same people by their identities, with the creature among them."""
    api = made
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    living = CREATES["town"]
    created = api.post(society, {"region_id": "region:generated", "profile": living})
    assert created.status_code in (200, 201), created.text
    before = {p["id"] for p in created.json()["state"]["inhabitants"]}
    creature = _keep_creature(api, tmp_path)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    _place(
        api, entry, CREATURE, {"source": "workspace", "sha256": creature.kind.sha256}, east, south
    )
    root = f"/world/versions/{entry['authored_version_id']}/society"
    taken = api.post(f"{root}/take-in?world_id={entry['world_id']}", {})
    assert taken.status_code in (200, 201), taken.text
    state = taken.json()["state"]
    assert state["profile"] == V7
    villagers = {p["id"] for p in state["inhabitants"] if p["came_by"] == "populated"}
    assert villagers == before
    assert [p["kind"] for p in state["inhabitants"] if p["came_by"] == "placed"] == [
        {"source": "workspace", "sha256": creature.kind.sha256}
    ]
    assert _replayed(api, entry) is True
