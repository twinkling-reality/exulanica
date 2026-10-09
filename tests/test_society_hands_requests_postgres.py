"""A person's hands request through the application and PostgreSQL.

In a saved world on a host that offers societies of things, as its owner, with one society seed:

*   ``POST .../society/actions`` takes a hands intent and records a v2 request; the next minute
    does the act, recorded as asked, and the society replays from what was stored;
*   a hands act the being is not offered is refused by the route's own name, and a body that
    names the other being for a pick-up, or none for a give, is refused at the boundary (422);
*   the binding refuses a v2 request by the one thing made wrong, with the trigger's own words
    (a thing the society does not hold, another being not here or the subject itself, a society
    not running hands, a society that is not one of things) or by the intent check (a target, a
    v1 profile over a hands act, another being on a pick-up or none on a give, a key beside the
    four), each against the same request bound as the positive control;
*   the request table's checks are the two this migration names, in place of 0060's four.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_world_api
from society_seed_support import choose_society_seed
from test_society_saved_world_api import OWNER, routes

saved_world = helpers.saved_world
saved_world_app = saved_world_api.world_app
pytestmark = pytest.mark.postgres
V7 = "exulanica-society/v7"
SEED = "d" * 64


@pytest.fixture
def world_app(saved_world_app):
    world, make_app, _runtime, _database = saved_world_app

    def offering():
        app = make_app()
        app.state.services = dataclasses.replace(app.state.services, societies_of_things=True)
        choose_society_seed(app, SEED)
        return app

    return world, offering


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


def _ask(client, world, society, subject, ability, thing_id, with_id=None):
    scope, _, society_route = routes(world)
    return client.post(
        society_route + "/actions",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": society["current_tick"],
            "base_state_sha256": society["state_sha256"],
            "subject_id": subject,
            "intent": {
                "kind": "hands",
                "ability": ability,
                "thing_id": thing_id,
                "with_id": with_id,
            },
        },
    )


def _step(client, world, society):
    scope, _, society_route = routes(world)
    stepped = client.post(
        society_route + "/steps",
        headers=OWNER,
        params=scope,
        json={"base_tick": society["current_tick"], "base_state_sha256": society["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _events(client, world):
    scope, _, society_route = routes(world)
    read = client.get(society_route + "/events", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()["events"]


def _replayed(client, world):
    scope, _, society_route = routes(world)
    replay = client.get(society_route + "/replay", headers=OWNER, params=scope)
    assert replay.status_code == 200, replay.text
    return replay.json()["replay_verified"]


def _scene(client, world):
    _place(client, world, "gate", "gate", 1, 0, 9_000)
    _place(client, world, "knight", "knight", 1, 3_000, 3_000)
    _place(client, world, "sword", "sword", 2, 2_400, 2_600)
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    society = _society(client, world)
    state = society["state"]
    knight = next(p for p in state["inhabitants"] if p["placed_id"] == "knight")
    things = {t["placed_id"]: t for t in state["things"]}
    return society, knight, things


def test_a_person_asks_the_knight_to_pick_the_sword_up(world_app):
    world, offering = world_app
    with TestClient(offering()) as client:
        society, knight, things = _scene(client, world)
        asked = _ask(client, world, society, knight["id"], "pick_up", things["sword"]["id"])
        assert asked.status_code == 200, asked.text
        envelope = asked.json()
        assert envelope["status"] == "pending"
        request = envelope["request"]
        assert request["profile"] == "exulanica.society-action-request/v2"
        assert "target" not in request
        stepped = _step(client, world, society)
        sword = next(t for t in stepped["state"]["things"] if t["placed_id"] == "sword")
        assert sword["held_by"] == knight["id"]
        events = _events(client, world)
        [requested] = [e for e in events if e["event_kind"] == "user_action_requested"]
        assert requested["document"]["disposition"] == "applied"
        assert requested["document"]["act"]["ability"] == "pick_up"
        [picked] = [e for e in events if e["event_kind"] == "picked_up"]
        assert picked["document"]["reason"] == "asked_to_pick_up"
        assert _replayed(client, world) is True


def test_an_act_the_being_is_not_offered_is_refused_by_the_route_s_name(world_app):
    world, offering = world_app
    with TestClient(offering()) as client:
        society, knight, things = _scene(client, world)
        refused = _ask(client, world, society, knight["id"], "pick_up", things["well"]["id"])
        assert refused.status_code == 409, refused.text
        assert refused.json() == {"code": "invalid_society_action", "detail": "act_not_offered"}


@pytest.mark.parametrize(
    ("ability", "with_id"),
    [("pick_up", str(uuid.UUID(int=3))), ("give", None)],
    ids=["another-being-on-a-pick-up", "no-other-being-on-a-give"],
)
def test_a_body_naming_the_other_being_wrongly_is_refused_at_the_boundary(
    world_app, ability, with_id
):
    world, offering = world_app
    with TestClient(offering()) as client:
        society, knight, things = _scene(client, world)
        refused = _ask(
            client, world, society, knight["id"], ability, things["sword"]["id"], with_id
        )
        assert refused.status_code == 422, refused.text


def _insert(world, society, document, target_id):
    connection = world["connection"]
    latest = connection.execute(
        "select coalesce(max(action_seq),0)+1 as n from world_society_action_request "
        "where workspace_id=%s and society_id=%s",
        (world["workspace"], society["society_id"]),
    ).fetchone()["n"]
    with connection.transaction():
        connection.execute(
            "insert into world_society_action_request(workspace_id,society_id,action_seq,"
            "request_id,requested_by,subject_id,target_id,base_tick,input_seq,document,"
            "document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                world["workspace"],
                society["society_id"],
                latest,
                uuid.UUID(document["request_id"]),
                uuid.UUID(document["requested_by"]),
                uuid.UUID(document["subject_id"]),
                target_id,
                document["base_tick"],
                document["input_seq"],
                Jsonb(document),
                document["document_sha256"],
            ),
        )


#: What the binding says when a v2 request names what the society does not hold or run.
TRIGGER_REFUSAL = "a hands request names a thing and a being of a society running hands"
INTENT_CHECK = "world_society_action_request_intent_check"


def _bound_request(client, world):
    """A v2 request the route built and recorded, the society it is for, and its state read at
    the same minute: the base every insert below changes one thing of."""
    society, knight, things = _scene(client, world)
    asked = _ask(client, world, society, knight["id"], "pick_up", things["sword"]["id"])
    assert asked.status_code == 200, asked.text
    scope, _, society_route = routes(world)
    held = client.get(society_route, headers=OWNER, params={**scope, "places": "true"}).json()
    return society, knight, things, asked.json()["request"], held


def _villager(society):
    return next(p for p in society["state"]["inhabitants"] if p["came_by"] == "populated")


def _changed(base, **change):
    """``base`` with ``change`` and a new request id: another being's request at the same minute
    (one request a being a minute), otherwise bound as the trigger asks."""
    return {**base, "request_id": str(uuid.uuid4()), **change}


def _intent(base, **change):
    return {**base["intent"], **change}


@pytest.mark.parametrize(
    ("case", "refused_by"),
    [
        ("a thing the society does not hold", "trigger"),
        ("another being not here", "trigger"),
        ("the subject as the other being", "trigger"),
        ("carrying a target", "check"),
        ("a v1 request whose intent is a hands act", "check"),
        ("another being named on a pick-up", "check"),
        ("no other being on a give", "check"),
        # No being's id is a number, so the binding refuses it before the check is reached.
        ("another being that is not a string", "trigger"),
        ("a key of its own beside the four", "check"),
    ],
)
def test_the_binding_and_the_checks_refuse_a_v2_request_by_its_one_wrong_thing(
    world_app, case, refused_by
):
    world, offering = world_app
    with TestClient(offering()) as client:
        society, knight, things, request, held = _bound_request(client, world)
    world["connection"].commit()
    villager = _villager(society)
    base = {**request, "subject_id": villager["id"]}
    sword = things["sword"]["id"]
    absent = str(uuid.UUID(int=9))
    changed = {
        "a thing the society does not hold": _changed(base, intent=_intent(base, thing_id=absent)),
        "another being not here": _changed(
            base, intent=_intent(base, ability="give", with_id=absent)
        ),
        "the subject as the other being": _changed(
            base, intent=_intent(base, ability="give", with_id=villager["id"])
        ),
        "carrying a target": _changed(base, target={}),
        "a v1 request whose intent is a hands act": _changed(
            base,
            profile="exulanica.society-action-request/v1",
            target=held["places"]["targets"][0],
        ),
        "another being named on a pick-up": _changed(
            base, intent=_intent(base, with_id=knight["id"])
        ),
        "no other being on a give": _changed(base, intent=_intent(base, ability="give")),
        "another being that is not a string": _changed(
            base, intent=_intent(base, ability="give", with_id=7)
        ),
        "a key of its own beside the four": _changed(base, intent=_intent(base, by="person")),
    }[case]
    target_id = (
        changed["target"]["target_id"]
        if changed["profile"].endswith("/v1")
        else changed["intent"]["thing_id"]
    )
    with pytest.raises(CheckViolation) as refused:
        _insert(world, society, changed, target_id)
    if refused_by == "trigger":
        # A trigger runs before a table's checks, and says why by its own words.
        assert refused.value.diag.constraint_name is None
        assert refused.value.diag.message_primary == TRIGGER_REFUSAL
    else:
        assert refused.value.diag.constraint_name == INTENT_CHECK
    # The positive control: the same base, changed in nothing but its request id, binds.
    world["connection"].rollback()
    _insert(world, society, _changed(base), sword)
    world["connection"].rollback()


def test_a_v2_request_on_a_society_not_running_hands_is_refused_by_the_binding(world_app):
    """The society's state as the binding reads it says no hands module: refused, with the
    trigger's words. The change is rolled back."""
    world, offering = world_app
    with TestClient(offering()) as client:
        society, _knight, things, request, _held = _bound_request(client, world)
    world["connection"].commit()
    base = {**request, "subject_id": _villager(society)["id"]}
    connection = world["connection"]
    connection.execute(
        "update world_society set state = state #- '{modules}' "
        "where workspace_id=%s and society_id=%s",
        (world["workspace"], society["society_id"]),
    )
    with pytest.raises(CheckViolation) as refused:
        _insert(world, society, _changed(base), things["sword"]["id"])
    assert refused.value.diag.message_primary == TRIGGER_REFUSAL
    connection.rollback()


def test_a_v2_request_on_a_purposeful_society_is_refused_by_the_binding(saved_world_app):
    """A society that is not a society of things takes no hands request: the binding's words."""
    world, make_app, _runtime, _database = saved_world_app
    with TestClient(make_app()) as client:
        # A plate to go to, so the purposeful society has a place, then its people.
        saved_world_api.place(client, world, "plate-1", 0, 4_000)
        made = saved_world_api.bring_inhabitants(client, world, saved_world_api.V2)
        assert made.status_code in (200, 201), made.text
        society = made.json()
        assert society["state"]["profile"] != V7
    world["connection"].commit()
    subject = society["state"]["inhabitants"][0]["id"]
    body = {
        "profile": "exulanica.society-action-request/v2",
        "request_id": str(uuid.uuid4()),
        "requested_by": str(world["session"].actor),
        "subject_id": subject,
        "branch_id": society["state"]["branch_id"],
        "base_tick": society["current_tick"],
        "base_state_sha256": society["state_sha256"],
        "input_seq": society["state"]["input_seq"],
        "input_sha256": society["state"]["input_sha256"],
        "intent": {"kind": "hands", "ability": "pick_up", "thing_id": "t", "with_id": None},
    }
    from exulanica.world.society import society_state_sha256

    document = {**body, "document_sha256": society_state_sha256(body)}
    with pytest.raises(CheckViolation) as refused:
        _insert(world, society, document, "t")
    assert refused.value.diag.message_primary == TRIGGER_REFUSAL
    world["connection"].rollback()


def test_the_request_table_checks_are_this_migration_s_two(world_app):
    world, _offering = world_app
    rows = (
        world["connection"]
        .execute(
            "select conname, pg_get_constraintdef(oid) as definition from pg_constraint "
            "where conrelid='world_society_action_request'::regclass and contype='c'"
        )
        .fetchall()
    )
    names = {row["conname"] for row in rows}
    assert {
        "world_society_action_request_profile_check",
        "world_society_action_request_intent_check",
    } <= names
    definitions = " ".join(row["definition"] for row in rows)
    # 0060's four inline checks are gone: none states v1 alone, or go_to outside the intent check.
    for row in rows:
        if row["conname"] != "world_society_action_request_intent_check":
            assert "go_to" not in row["definition"], row
    assert "society-action-request/v2" in definitions
