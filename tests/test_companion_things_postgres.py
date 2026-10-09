"""The Companion's things through the application and PostgreSQL: a plan's step is the request.

In a saved world on a host that offers societies of things, as its owner, with the model scripted:

*   "add a knight by the well" is one step, the add_thing request beside the well, planned
    without writing anything; sent, it is the route's own edit, which the outcome read credits;
*   "send the knight to the well" is one step, the actions route's request at this minute; sent, it
    waits for its minute, and once the minute takes it the outcome read says what the minute did;
*   a plan that places a lantern beside the knight and then sends the knight to the well prepares
    its second step only once the society has taken the lantern in, and says so by code until then.

The drafter's option labels are read from the request the scripted model was sent, the way the
model reads them.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
import uuid

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.action_plan import ACTION_PROMPT_VERSION, DIRECT, MAX_STEPS, THING_PLACE
from exulanica.world.society_actions import ACTION_REFUSALS
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_world_api
from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, chat_body
from society_seed_support import choose_society_seed
from test_society_saved_world_api import OWNER, routes

saved_world = helpers.saved_world
saved_world_app = saved_world_api.world_app
pytestmark = pytest.mark.postgres
V7 = "exulanica-society/v7"
EXTRACTOR = load_manifest()[Role.STRUCTURED_EXTRACTION].primary.model_id
SEED = "c" * 64
#: Every table a plan or a prepared step must leave as it found it.
WATCHED = (
    "world_alternate_version_edit",
    "world_alternate_thing",
    "world_society_action_request",
    "world_society_event",
)
#: Where the person stands and looks, region-local, and the spot 3.5 m ahead they point at.
VIEWER = {"x_mm": 0, "z_mm": 4_000, "yaw_microradians": 0}
SPOT = {"x_mm": 0, "y_mm": 0, "z_mm": 500, "yaw_microradians": 0, "scale_milli": 1_000}


@pytest.fixture
def companion(saved_world_app):
    world, make_app, _runtime, _database = saved_world_app
    transport = FakeTransport()
    app = make_app()
    app.state.services = dataclasses.replace(
        app.state.services,
        societies_of_things=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
    )
    # The routine decides what the knight and the villagers do between requests: one seed for
    # every run, as the hands tests pin theirs.
    choose_society_seed(app, SEED)
    with TestClient(app) as client:
        yield world, client, transport


def _reply(payload: dict) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(payload), model=EXTRACTOR))
    )


def _place(client, world, thing_id, kind, version, x_mm, z_mm):
    scope, root, _ = routes(world)
    base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]
    placed = client.post(
        root + "/things",
        headers=OWNER,
        params=scope,
        json={
            "base_state_sha256": base,
            "thing_id": thing_id,
            "kind": {"kind": kind, "version": version},
            "region_id": world["binding"].region_id,
            "pose": {"x_mm": x_mm, "y_mm": 0, "z_mm": z_mm, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


def _society(client, world):
    scope, _, society_route = routes(world)
    made = client.post(
        society_route,
        headers=OWNER,
        params=scope,
        json={"region_id": world["binding"].region_id, "profile": V7},
    )
    assert made.status_code in (200, 201), made.text
    return made.json()


def _now(client, world):
    scope, _, society_route = routes(world)
    read = client.get(society_route, headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()


def _minute(client, world):
    scope, _, society_route = routes(world)
    society = _now(client, world)
    stepped = client.post(
        society_route + "/steps",
        headers=OWNER,
        params=scope,
        json={"base_tick": society["current_tick"], "base_state_sha256": society["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _version(client, world):
    scope, root, _ = routes(world)
    return client.get(root, headers=OWNER, params=scope).json()


def _counts(world) -> dict[str, int]:
    connection = world["connection"]
    return {
        table: connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
        for table in WATCHED
    }


def _base_body(client, world, **extra) -> dict:
    version = _version(client, world)
    return {
        "version_id": str(world["binding"].version_id),
        "base_state_sha256": version["state_sha256"],
        "origin_role": "fictional",
        "context": {
            "placement": {"region_id": world["binding"].region_id, "transform": SPOT},
            "viewer": {**VIEWER, "region_id": world["binding"].region_id},
        },
        **extra,
    }


def _ask(client, world, utterance: str):
    scope, _, _ = routes(world)
    asked = client.post(
        "/selection/actions",
        headers=OWNER,
        params=scope,
        json={**_base_body(client, world), "utterance": utterance},
    )
    assert asked.status_code == 200, asked.text
    return asked.json()


def _prepare(client, world, actions):
    scope, _, _ = routes(world)
    prepared = client.post(
        "/selection/actions/prepare",
        headers=OWNER,
        params=scope,
        json={**_base_body(client, world), "actions": actions},
    )
    assert prepared.status_code == 200, prepared.text
    return prepared.json()


def _send(client, step):
    method, template = step["operation"].split(" ", 1)
    assert method == "POST"
    return client.post(
        template.format(**step["bind"]), headers=OWNER, params=step["query"], json=step["body"]
    )


def _outcome(client, world, plan, steps):
    scope, _, _ = routes(world)
    read = client.post(
        "/selection/actions/outcome",
        headers=OWNER,
        params=scope,
        json={"version_id": plan["version_id"], "plan_sha256": plan["plan_sha256"], "steps": steps},
    )
    assert read.status_code == 200, read.text
    return read.json()


def _why(plan: dict) -> tuple:
    """What a plan that is not one says about itself: its refusal, its question, its steps."""
    return (
        plan["refusal"],
        plan["clarification"],
        [(step["state"], step["code"]) for step in plan["steps"]],
    )


def _labels(transport) -> dict[str, str]:
    """The drafter's labels by the words they stand for, from the last request it was sent."""
    message = transport.requests[-1]["payload"]["messages"][-1]["content"]
    return {
        words.strip(): label
        for label, words in re.findall(r"^  ([a-z0-9_.-]+): (.+)$", message, flags=re.M)
    }


def _label(labels: dict[str, str], words: str, *, starts: bool = False) -> str:
    """The one label shown for exactly ``words``, or for words starting with them."""
    [label] = [
        label
        for shown, label in labels.items()
        if (shown.startswith(words) if starts else shown == words)
    ]
    return label


def _look(client, world, transport, utterance: str) -> dict[str, str]:
    """The labels the drafter is shown for ``utterance``: a draft the form refuses (``other``)
    after the classifier's answer, so nothing is prepared and nothing written."""
    transport.responses[:] = [
        _reply({"kind": "world_edit"}),
        _reply({"steps": [{"operation": "other", "options": []}]}),
    ]
    refused = _ask(client, world, utterance)
    assert refused["outcome"] == "refused"
    return _labels(transport)


def test_add_a_knight_by_the_well_is_the_add_thing_request_beside_the_well(companion):
    world, client, transport = companion
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    labels = _look(client, world, transport, "add a knight by the well")
    well = _label(labels, "well")
    before = _counts(world)
    transport.responses[:] = [
        _reply({"kind": "world_edit"}),
        _reply({"steps": [{"operation": "place_thing", "options": ["knight", well]}]}),
    ]
    plan = _ask(client, world, "add a knight by the well")

    assert plan["outcome"] == "plan", _why(plan)
    assert plan["kind"] == "world_edit" and plan["spends"] is False
    assert plan["execution"]["prompt_version"] == ACTION_PROMPT_VERSION
    assert _counts(world) == before, "planning wrote something"
    [step] = plan["steps"]
    assert (step["operation"], step["state"], step["preview"]) == (THING_PLACE, "prepared", None)
    assert step["action"]["near"] == "thing:well"
    body = step["body"]
    assert body["thing_id"].startswith("companion:knight:")
    assert body["kind"]["kind"] == "knight" and body["origin_role"] == "fictional"
    # Beside the well, on its side toward the person: 1,858 mm from its centre (its circle, a
    # being's, the clearance and a millimetre), nearer the person than the well is.
    x_mm, z_mm = body["pose"]["x_mm"], body["pose"]["z_mm"]
    assert abs(math.hypot(x_mm + 4_000, z_mm - 2_000) - 1_858) <= 1
    assert math.hypot(x_mm, z_mm - 4_000) < math.hypot(-4_000, 2_000 - 4_000)

    sent = _send(client, step)
    assert sent.status_code == 201, sent.text
    version = sent.json()
    [knight] = [t for t in version["things"] if t["thing_id"] == body["thing_id"]]
    assert (knight["transform"]["x_mm"], knight["transform"]["z_mm"]) == (x_mm, z_mm)
    read = _outcome(
        client,
        world,
        plan,
        [
            {
                **step,
                "answer": {
                    "status": 201,
                    "edit_seq": version["edit_seq"],
                    "state_sha256": version["state_sha256"],
                },
            }
        ],
    )
    assert read["state"] == "applied"
    [receipt] = read["steps"][0]["receipts"]
    assert (receipt["kind"], receipt["thing_id"]) == ("add_thing", body["thing_id"])
    assert read["steps"][0]["matches_preview"] is None


def test_the_film_s_six_things_are_placed_once_their_origin_is_answered(companion):
    """SCENE's opening sentence is six steps that place things. A plan that places asks first
    where its things come from; the page sends the six typed actions back with the answer, and
    then, as each step's receipt comes, the actions still to do: every list is prepared, its first
    step ready and the rest pending, until all six things stand. A list longer than one request
    may ask for is refused."""
    world, client, transport = companion
    sentence = (
        "Add a stone well, a gate for travellers, a knight on guard by the well, a lantern "
        "spirit, and a sword and a lantern by the well."
    )
    kinds = ["well", "gate", "knight", "lantern_spirit", "sword", "lantern"]
    beside_the_well = (False, False, True, False, True, True)
    transport.responses[:] = [
        _reply({"kind": "world_edit"}),
        _reply(
            {
                "steps": [
                    {"operation": "place_thing", "options": [kind, "well"] if beside else [kind]}
                    for kind, beside in zip(kinds, beside_the_well, strict=True)
                ]
            }
        ),
    ]
    scope, _, _ = routes(world)
    unanswered = {**_base_body(client, world), "utterance": sentence}
    del unanswered["origin_role"]
    asked = client.post("/selection/actions", headers=OWNER, params=scope, json=unanswered)
    assert asked.status_code == 200, asked.text
    question = asked.json()
    assert question["outcome"] == "clarify", _why(question)
    assert question["clarification"]["code"] == "origin_role_required"
    actions = question["clarification"]["actions"]
    assert [action["kind"] for action in actions] == kinds
    well = actions[0]["thing_id"]
    assert [action["near"] for action in actions] == [
        f"thing:{well}" if beside else None for beside in beside_the_well
    ]

    placed = []
    while actions:
        plan = _prepare(client, world, actions)
        assert plan["outcome"] == "plan", _why(plan)
        assert [step["state"] for step in plan["steps"]] == ["prepared"] + ["pending"] * (
            len(actions) - 1
        )
        sent = _send(client, plan["steps"][0])
        assert sent.status_code == 201, sent.text
        placed.append(actions[0]["thing_id"])
        actions = actions[1:]

    things = {thing["thing_id"]: thing for thing in _version(client, world)["things"]}
    assert [things[thing_id]["kind"]["kind"] for thing_id in placed] == kinds
    too_many = client.post(
        "/selection/actions/prepare",
        headers=OWNER,
        params=scope,
        json={
            **_base_body(client, world),
            "actions": [question["clarification"]["actions"][0]] * (MAX_STEPS + 1),
        },
    )
    assert too_many.status_code == 422, too_many.text


def test_send_the_knight_to_the_well_is_the_actions_route_s_request_at_this_minute(companion):
    world, client, transport = companion
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "knight", "knight", 2, 3_000, 3_000)
    _society(client, world)
    labels = _look(client, world, transport, "send the knight to the well")
    knight = _label(labels, "Knight (kind: knight", starts=True)
    well = _label(labels, "the well, to visit")
    before = _counts(world)
    transport.responses[:] = [
        _reply({"kind": "world_edit"}),
        _reply({"steps": [{"operation": "send_to", "options": [knight, well]}]}),
    ]
    plan = _ask(client, world, "send the knight to the well")

    assert plan["outcome"] == "plan", _why(plan)
    assert _counts(world) == before, "planning wrote something"
    [step] = plan["steps"]
    assert (step["operation"], step["state"]) == (DIRECT, "prepared")
    society = _now(client, world)
    assert step["pins"] == {
        "tick": society["current_tick"],
        "society_state_sha256": society["state_sha256"],
    }
    assert step["body"]["intent"]["kind"] == "go_to"
    sent = _send(client, step)
    assert sent.status_code == 200, sent.text
    envelope = sent.json()
    # Asked once at this minute: asking the knight again waits for the minute that takes it.
    [again] = _prepare(client, world, [step["action"]])["steps"]
    assert (again["state"], again["code"]) == ("pending", "inhabitant_action_in_progress")
    answer = {
        "status": 200,
        "request_id": envelope["request"]["request_id"],
        "document_sha256": envelope["request"]["document_sha256"],
    }
    waiting = _outcome(client, world, plan, [{**step, "answer": answer}])
    assert waiting["steps"][0]["state"] == "pending"
    # A step sent back naming another being than the request recorded is credited with nothing.
    other = {**step, "body": {**step["body"], "subject_id": str(uuid.UUID(int=5))}}
    assert _outcome(client, world, plan, [{**other, "answer": answer}])["steps"][0]["state"] == (
        "not_applied"
    )
    _minute(client, world)
    taken = _outcome(client, world, plan, [{**step, "answer": answer}])
    assert taken["steps"][0]["state"] == "applied", taken
    assert taken["steps"][0]["receipts"][0]["disposition"] == "applied"


def test_a_plan_that_places_then_asks_waits_for_the_minute_that_takes_the_thing_in(companion):
    world, client, transport = companion
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "knight", "knight", 2, 3_000, 3_000)
    _society(client, world)
    labels = _look(client, world, transport, "put a lantern by the knight and send him to the well")
    knight = _label(labels, "Knight (kind: knight", starts=True)
    well = _label(labels, "the well, to visit")
    transport.responses[:] = [
        _reply({"kind": "world_edit"}),
        _reply(
            {
                "steps": [
                    {"operation": "place_thing", "options": ["lantern", knight]},
                    {"operation": "send_to", "options": [knight, well]},
                ]
            }
        ),
    ]
    plan = _ask(client, world, "put a lantern by the knight and send him to the well")
    assert plan["outcome"] == "plan", _why(plan)
    first, second = plan["steps"]
    assert (first["state"], second["state"]) == ("prepared", "pending")
    assert _send(client, first).status_code == 201

    # The society has not taken the lantern's input in: the second step says to wait.
    waiting = _prepare(client, world, [second["action"]])
    assert waiting["outcome"] == "plan"
    [held] = waiting["steps"]
    assert (held["state"], held["code"]) == ("pending", "society_input_queued")
    # As the page does: a minute at a time, while the step says to wait (the lantern's input, the
    # knight in the middle of what its routine began, or every place at the well taken by the
    # residents visiting it), at most twenty. Once the lantern is taken in, the step is the
    # route's to answer: prepared, refused by the route's own name, or still waiting for the
    # knight or a free place at the well, never for the lantern again.
    waits = ("society_input_queued", "inhabitant_action_in_progress", "destination_full")
    for _minutes in range(20):
        _minute(client, world)
        [prepared] = _prepare(client, world, [second["action"]])["steps"]
        if prepared["state"] != "pending":
            break
        assert prepared["code"] in waits, prepared
    assert prepared["code"] != "society_input_queued", prepared
    if prepared["state"] == "prepared":
        assert _send(client, prepared).status_code == 200
    elif prepared["state"] == "pending":
        assert prepared["code"] in waits, prepared
    else:
        assert prepared["state"] == "blocked" and prepared["code"] in ACTION_REFUSALS, prepared
