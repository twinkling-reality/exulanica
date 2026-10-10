"""A creature its workspace keeps lives in a saved world's society of things, through the
application and against PostgreSQL, and is erased whole.

What is shown, as the world's owner through the real routes:

*   a creature kept in the workspace's store and placed by its kind's digest makes the world one
    of things, and the society made over it takes the creature in as a being, named by its body;
    its input states the creature's run form once and binds its kind by digest;
*   it walks with everybody else, minute by minute, and the society replays;
*   its card names it as its maker did, from the workspace's store, with the open model that
    drafted it and who decides for it now, and says a model may be chosen for it;
*   erasing the creature tells the society: its next input leaves the thing out and names it among
    those gone, the being leaves that minute for that reason, the society still replays,
    and afterwards no row of any table of the database holds a word the creature was made with;
*   a society that could not be told still loses the being at its next input.

The creature is assembled under nonsense words (``tests/test_society_made_kinds.py``), so a search
of the stored rows for them is a search for anything a person's words reached.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.bodies import read_body_recipe
from exulanica.things.run_forms import run_form
from exulanica.world.thing_store import ThingStore
from fastapi.testclient import TestClient

import test_companion_things_postgres as companion_things
import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_world_api
import test_society_things_postgres as things_api
from conftest import scratch_role_database
from test_society_made_kinds import CANARIES, canary_creature
from test_society_saved_world_api import OWNER, routes

saved_world = helpers.saved_world
saved_world_app = saved_world_api.world_app
world_app = things_api.world_app
companion = companion_things.companion
pytestmark = pytest.mark.postgres
V7 = "exulanica-society/v7"
#: A placed creature's id, opaque as the page makes it: never made from its label.
CREATURE = "creature:5d1e9a07"


@pytest.fixture
def kept(world_app, spine_schema, tmp_path):
    """A crocodile fixture kept in the world's workspace by the deployed writer, drafted by the
    actor the owner's token names, so that actor may erase it."""
    world, _, _, _ = world_app
    return _keep(world, spine_schema, tmp_path)


def _keep(world, spine_schema, tmp_path):
    connection = world["connection"]
    provision_runtime_role(connection)
    connection.commit()
    writer = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    creature = canary_creature("crocodile", hands=True)
    with writer.session(world["workspace"]) as session:
        ThingStore(
            session, world["workspace"], LocalContentAddressedStore(tmp_path / "looks")
        ).keep_creature(creature, created_by=world["session"].actor)
    # As the deployed runtime role, under the workspace's row security: the store builds the run
    # form the pure builder builds from the same three documents, and none for a digest it does
    # not hold or for another workspace.
    expected = run_form(creature.kind, creature.plan, read_body_recipe(dict(creature.recipe)))
    with writer.session(world["workspace"]) as session:
        store = ThingStore(session, world["workspace"], None)
        assert store.run_form(creature.kind.sha256) == expected
        assert store.run_form("0" * 64) is None
    with writer.session(uuid.uuid4()) as session:
        assert ThingStore(session, world["workspace"], None).run_form(creature.kind.sha256) is None
    return creature


def _place_made(client, world, thing_id, sha256, x_mm, z_mm):
    scope, root, _ = routes(world)
    base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]
    placed = client.post(
        root + "/things",
        headers=OWNER,
        params=scope,
        json={
            "base_state_sha256": base,
            "thing_id": thing_id,
            "kind": {"source": "workspace", "sha256": sha256},
            "region_id": world["binding"].region_id,
            "pose": {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _inputs(database, world):
    with database.session(world["workspace"]) as connection:
        rows = connection.execute(
            "select i.input_seq, i.document from world_society_input i join world_society s "
            "on s.workspace_id=i.workspace_id and s.society_id=i.society_id "
            "where s.workspace_id=%s and s.version_id=%s order by i.input_seq",
            (world["workspace"], world["binding"].version_id),
        ).fetchall()
    return [row["document"] for row in rows]


def _rows_holding(database, world, words) -> dict[str, list[str]]:
    """Every table of the schema with a row whose text holds one of ``words``, by table."""
    found: dict[str, list[str]] = {}
    with database.session(world["workspace"]) as connection:
        tables = [
            row["tablename"]
            for row in connection.execute(
                "select tablename from pg_tables where schemaname=current_schema() "
                "order by tablename"
            ).fetchall()
        ]
        for table in tables:
            rows = connection.execute(f'select lower(t::text) as row from "{table}" t').fetchall()
            held = sorted({word for row in rows for word in words if word in row["row"]})
            if held:
                found[table] = held
    return found


def _society(client, world, kept):
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "sword", "sword", 3, 5_000, 1_000)
    _place_made(client, world, CREATURE, kept.kind.sha256, 3_000, 3_000)
    return things_api._make_society(client, world)


def test_a_creature_alone_makes_the_world_one_of_things_and_lives_in_its_society(world_app, kept):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        client.app.state.services = dataclasses.replace(
            client.app.state.services, societies_of_things=True
        )
        # No shipped thing is placed, only a reviewed object for people to walk to (a society
        # needs somewhere to go): the creature alone decides the engine, as a knight would.
        saved_world_api.place(client, world, "plate-1", -3_000, 2_000)
        _place_made(client, world, CREATURE, kept.kind.sha256, 3_000, 3_000)
        scope, _, society_route = routes(world)
        asked = client.post(
            society_route,
            headers=OWNER,
            params=scope,
            json={"region_id": world["binding"].region_id, "profile": "exulanica-society/v2"},
        )
        # The world holds a thing its author placed, so its society is one of things.
        assert asked.status_code == 409, asked.text
        assert asked.json()["code"] == "society_engine_differs" and V7 in asked.json()["detail"]
        society = things_api._make_society(client, world)
        assert society["profile"] == V7
        being = next(p for p in society["state"]["inhabitants"] if p["came_by"] == "placed")
        made_kind = {"source": "workspace", "sha256": kept.kind.sha256}
        # Named by hand from the crocodile fixture: four legs, one head, no wings.
        assert (being["kind"], being["display_name"]) == (made_kind, "Four legged creature")
        assert list(society["state"]["kinds"]) == [kept.kind.sha256]
        [first] = _inputs(database, world)
        assert list(first["kinds"]) == [kept.kind.sha256] and "things_gone" not in first
        assert {
            "kind": "made_thing_kind",
            "identity": kept.kind.sha256,
            "sha256": kept.kind.sha256,
        } in first["dependency_refs"]
        for _ in range(5):
            society = things_api._step(client, world, society)
        assert things_api._replayed(client, world) is True


def test_its_card_names_it_as_its_maker_did_with_who_drafted_it_and_who_decides(world_app, kept):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        society = _society(client, world, kept)
        being = next(p for p in society["state"]["inhabitants"] if p["came_by"] == "placed")
        scope, _, society_route = routes(world)
        read = client.get(f"{society_route}/things/{being['id']}", headers=OWNER, params=scope)
        assert read.status_code == 200, read.text
        card = read.json()
        assert (card["thing_id"], card["subject_id"], card["came_by"]) == (
            being["id"],
            being["id"],
            "placed",
        )
        # The society's name for it is its body's; the kind's is its maker's, from the store.
        assert card["label"] == "Four legged creature"
        assert card["kind"] == {
            "source": "workspace",
            "sha256": kept.kind.sha256,
            "held": True,
            "label": "quorzle wibbet",
            "summary": "Zanthrefol mipwick.",
            "class": "being",
            "body": {
                "plan": None,
                "name": "four legged creature",
                "summary": "A creature about 4.5 m long and 0.5 m high with one head, four legs "
                "and a tail. It moves over the ground. It carries a thing in its jaws.",
            },
            # The provenance the fixture's drafting states; its name is its id, since no
            # manifest declares it.
            "drafted_by": {
                "provider": "frobnitz_provider",
                "model_id": "frobnitz/model",
                "name": "frobnitz/model",
            },
        }
        assert card["kind_origin"] == {"class": "drafted", "by": card["kind"]["drafted_by"]}
        assert "ab" * 32 not in json.dumps(card)
        # Its routine decides until somebody chooses otherwise, and a model may be chosen.
        assert (card["decider"]["kind"], card["decider"]["may_change"]) == ("routine", True)
        assert card["look"]["source"] == "workspace"
        assert card["look"]["sha256"] == kept.sketch.sha256
        # Every ability its kind lists that a module this society runs serves, in the kind's order.
        assert [a["key"] for a in card["abilities"]] == [
            "wait",
            "stand",
            "talk",
            "rest",
            "visit",
            "pick_up",
            "put_down",
            "follow",
            "say",
        ]
        # Another look is refused by name: it wears its sketch.
        swap = client.post(
            f"{society_route}/things/{being['id']}/look",
            headers=OWNER,
            params=scope,
            json={"look": {"source": "workspace", "sha256": kept.sketch.sha256}},
        )
        assert swap.status_code in (409, 422), swap.text
        assert swap.json()["code"] == "look_unfit"


def test_erasing_the_creature_sends_its_being_away_and_leaves_no_word_of_it_anywhere(
    world_app, kept
):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = _society(client, world, kept)
        being = next(p for p in society["state"]["inhabitants"] if p["came_by"] == "placed")
        for _ in range(6):
            society = things_api._step(client, world, society)
        assert any(p["id"] == being["id"] for p in society["state"]["inhabitants"])
        # The positive control: while the creature is kept, the search finds its words, and only
        # in the workspace's own store.
        before = _rows_holding(database, world, CANARIES)
        assert before and set(before) <= {
            "thing_kind_version",
            "body_plan_version",
            "body_recipe_version",
            "look_version",
        }, before
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        # The society was told: its next input leaves the thing out and names the kind as gone.
        inputs = _inputs(database, world)
        assert len(inputs) == 2
        assert CREATURE not in [entry["placed_id"] for entry in inputs[1]["things"]]
        assert "kinds" not in inputs[1] and inputs[1]["things_gone"] == [CREATURE]
        scope, _, society_route = routes(world)
        # Until the next minute the being is still in the state, and its card names nothing.
        card = client.get(f"{society_route}/things/{being['id']}", headers=OWNER, params=scope)
        assert card.status_code == 200, card.text
        assert card.json()["kind"]["held"] is False
        assert card.json()["kind"]["label"] == "four legged creature"
        assert card.json()["kind"]["drafted_by"] is None and card.json()["look"] is None
        society = things_api._step(client, world, society)
        assert all(p["id"] != being["id"] for p in society["state"]["inhabitants"])
        assert "kinds" not in society["state"]
        left = [e for e in things_api._events(client, world) if e["event_kind"] == "thing_departed"]
        assert [(e["document"]["subject_id"], e["document"]["reason"]) for e in left] == [
            (being["id"], "kind_erased")
        ]
        assert left[0]["document"]["thing"]["kind"] == {
            "source": "workspace",
            "sha256": kept.kind.sha256,
        }
        gone = client.get(f"{society_route}/things/{being['id']}", headers=OWNER, params=scope)
        assert gone.status_code == 404, gone.text
        for _ in range(3):
            society = things_api._step(client, world, society)
        assert things_api._replayed(client, world) is True
        # Nothing a person's words reached is left in any table: not in the store, which the
        # erasure emptied, and not in the society, which never held it.
        assert _rows_holding(database, world, CANARIES) == {}
        # The search is not blind to the society's rows: it finds the body's own name there.
        assert "world_society_event" in _rows_holding(database, world, ("four legged creature",))


def test_asking_for_the_erasure_again_tells_a_society_that_could_not_be_told(world_app, kept):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = _society(client, world, kept)
        being = next(p for p in society["state"]["inhabitants"] if p["came_by"] == "placed")
        hook = client.app.state.society_authored_edit

        def failing(*_args, **_kwargs):
            raise RuntimeError("the society could not be told")

        client.app.state.society_authored_edit = failing
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        assert len(_inputs(database, world)) == 1
        client.app.state.society_authored_edit = hook
        # The creature is gone from the store, so the route answers as for any kind the workspace
        # does not hold; an erasure is recorded for it, so the society is told now.
        again = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert again.status_code == 404, again.text
        inputs = _inputs(database, world)
        assert len(inputs) == 2 and inputs[1]["things_gone"] == [CREATURE]
        # Telling is idempotent: asked a third time, nothing more is appended.
        third = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert third.status_code == 404 and len(_inputs(database, world)) == 2
        # A digest nobody erased tells nobody and writes nothing.
        never = client.delete(f"/things/kinds/{'0' * 64}", headers=OWNER)
        assert never.status_code == 404 and len(_inputs(database, world)) == 2
        society = things_api._step(client, world, society)
        assert all(p["id"] != being["id"] for p in society["state"]["inhabitants"])
        assert things_api._replayed(client, world) is True


def test_a_society_that_was_not_told_still_loses_the_being_at_its_next_input(world_app, kept):
    world, make_app, _, database = world_app
    with TestClient(make_app()) as client:
        society = _society(client, world, kept)
        being = next(p for p in society["state"]["inhabitants"] if p["came_by"] == "placed")
        # The application's hook fails for this erasure: the erasure stands all the same.
        hook = client.app.state.society_authored_edit

        def failing(*_args, **_kwargs):
            raise RuntimeError("the society could not be told")

        client.app.state.society_authored_edit = failing
        erased = client.delete(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert erased.status_code == 204, erased.text
        client.app.state.society_authored_edit = hook
        assert len(_inputs(database, world)) == 1
        absent = client.get(f"/things/kinds/{kept.kind.sha256}", headers=OWNER)
        assert absent.status_code == 404
        # The next edit of the version composes an input, and that input leaves the thing out.
        things_api._place(client, world, "knight", "knight", 1, -3_000, 3_000)
        inputs = _inputs(database, world)
        assert len(inputs) == 2 and inputs[1]["things_gone"] == [CREATURE]
        society = things_api._step(client, world, society)
        assert all(p["id"] != being["id"] for p in society["state"]["inhabitants"])
        reasons = {
            e["document"]["reason"]
            for e in things_api._events(client, world)
            if e["event_kind"] == "thing_departed"
        }
        assert reasons == {"kind_erased"}
        assert things_api._replayed(client, world) is True


def test_the_companion_plans_in_a_world_whose_society_holds_a_made_being(
    companion, spine_schema, tmp_path
):
    """The actions route reads every being of the society before it drafts anything: a being of a
    kind its workspace keeps is read as a being of no shipped kind, by the society's name for it,
    and the plan for another being is prepared as in any world. Nothing the drafting model is
    sent holds a word the creature was made with."""
    world, client, transport = companion
    creature = _keep(world, spine_schema, tmp_path)
    companion_things._place(client, world, "well", "well", 2, -4_000, 2_000)
    companion_things._place(client, world, "knight", "knight", 2, 3_000, 3_000)
    _place_made(client, world, CREATURE, creature.kind.sha256, 1_000, 5_000)
    society = companion_things._society(client, world)
    assert any(
        p["kind"] == {"source": "workspace", "sha256": creature.kind.sha256}
        for p in society["state"]["inhabitants"]
    )
    labels = companion_things._look(client, world, transport, "send the knight to the well")
    # The being is offered by the society's name for it, its body's.
    assert any(shown.startswith("Four legged creature") for shown in labels), sorted(labels)
    knight = companion_things._label(labels, "Knight (kind: knight", starts=True)
    well = companion_things._label(labels, "the well, to visit")
    transport.responses[:] = [
        companion_things._reply({"kind": "world_edit"}),
        companion_things._reply({"steps": [{"operation": "send_to", "options": [knight, well]}]}),
    ]
    plan = companion_things._ask(client, world, "send the knight to the well")
    assert plan["outcome"] == "plan", companion_things._why(plan)
    [step] = plan["steps"]
    assert step["state"] == "prepared"
    # A typed request for the same step prepares too.
    [again] = companion_things._prepare(client, world, [step["action"]])["steps"]
    assert again["state"] == "prepared"
    sent = json.dumps([request["payload"] for request in transport.requests]).lower()
    for canary in CANARIES:
        assert canary not in sent, canary
