"""A visitor the world decides for, through the door and against PostgreSQL.

A world's owner issues a grant whose visitors the world decides for, naming the mind its
travellers get. What is shown, through the real routes:

*   each arrival under the grant says the world decides, from the grant and never from the bridge,
    and no ask for that visitor ever reaches the bridge, while the traveller mind decides for it;
    a program grant's arrival keeps its bytes; a kind no world mind may decide for is refused;
*   naming the traveller mind needs ``model.invoke``, is recorded with the grant ending at its end,
    is answered again by its key, and is refused by name where the grant or the model does not fit;
*   revoking releases the mind under a key of its own, and a grant that runs out lapses it, chosen
    by the grant's own actor;
*   a grant that ran out sends its visitors home at the next poll, at its owner's read, and through
    the maintenance pass's sweep when nobody reads it, each once;
*   a bridge calls one of its visitors home with the owner's own departure, once, and is refused for
    a stranger and after its grant's end;
*   a visitor the world decides for is one of the world's beings to its owner: listed with nobody
    outside, and a model may be chosen for it, but it is never handed to a program by a later grant.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import uuid
from typing import Any

import pytest
from exulanica.api.routes import door as door_routes
from exulanica.api.routes import society_models as society_models_routes
from exulanica.db.session import Database
from exulanica.door import sweep as sweep_module
from exulanica.door.bridges import load_bridge_directory
from exulanica.door.grants import GrantRepository, grant_actor
from exulanica.door.sweep import sweep
from exulanica.env import env_get
from psycopg.conninfo import make_conninfo

import door_support
import test_society_authored_world_postgres as helpers
import test_society_person_decisions_postgres as decisions
from test_door_crossing_rules_postgres import _crossings, _expire
from test_door_crossings_postgres import (
    _arrive,
    _departure_id,
    _visitors,
    _world,
)
from test_door_crossings_postgres import crossings as crossings
from test_door_lines_postgres import _host, _Knight, _minute
from test_door_postgres import OWNER, TOKEN
from test_door_postgres import door as door
from test_society_saved_world_api import routes
from test_society_things_postgres import _step
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres

#: A token of the same owner without ``model.invoke``.
UNPAID = "world-decides-without-model-invoke-0001"


def _traveller_mapping() -> dict[str, Any]:
    """The test mapping with its players arriving as travellers, a kind the world may decide for."""
    document = door_support.mapping_v2()
    document["visitors"][0]["kind"] = {"key": "traveller", "version": 1}
    return document


@contextlib.contextmanager
def _application(door, monkeypatch):
    """The application with the test bridge pinning both mappings, a second token without
    ``model.invoke``, and the manifest that offers the test model."""
    world = door["world"]
    every = {
        "workspace_id": str(world["workspace"]),
        "actor": str(world["session"].actor),
        "permissions": EVERY_PERMISSION,
    }
    unpaid = {**every, "permissions": [p for p in EVERY_PERMISSION if p != "model.invoke"]}
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps({TOKEN: every, UNPAID: unpaid}))
    manifest, model_id = decisions._offered()
    monkeypatch.setattr(door_routes, "load_manifest", lambda: manifest)
    monkeypatch.setattr(society_models_routes, "load_manifest", lambda: manifest)
    entries = json.loads(
        door_support.bridges_setting(
            listed=False, workspaces=[str(world["workspace"])], hold_seconds=1
        )
    )
    entries[0]["mapping_sha256"] = [
        door_support.mapping_sha256(),
        door_support.mapping_sha256(_traveller_mapping()),
    ]
    client, _runtime = door["application"](
        load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    )
    with client:
        yield client, {"provider": manifest.spec(model_id).provider, "model_id": model_id}


def _issue(client, door, key: str, *, headers=OWNER, **change: Any):
    world = door["world"]
    body = {
        "idempotency_key": key,
        "bridge": "test-bridge",
        "visitors_maximum": 2,
        "kinds": ["player"],
        "version_id": str(world["binding"].version_id),
        "gate": "gate",
        "visitors_decided_by": "world",
        "channel_credential": True,
        **change,
    }
    return client.post(
        "/door/grants", headers=headers, params={"world_id": world["binding"].world_id}, json=body
    )


def _opened(client, door, key: str, mapping=None, **change: Any) -> tuple[str, dict[str, str]]:
    """A grant issued and its channel said hello on, with the mapping given."""
    issued = _issue(client, door, key, **change)
    assert issued.status_code == 201, issued.text
    channel = {"Authorization": f"Bearer {issued.json()['channel_credential']['credential']}"}
    said = client.post(
        "/door/channel/hello",
        headers=channel,
        json={
            "adapter_version": door_support.ADAPTER_VERSION,
            "mapping": _traveller_mapping() if mapping is None else mapping,
            "reads": door_support.READS,
        },
    )
    assert said.status_code == 200, said.text
    return issued.json()["grant"]["grant_id"], channel


def _choice(world, request_id: uuid.UUID) -> dict[str, Any] | None:
    connection = world["connection"]
    row = connection.execute(
        "select document, chosen_by from world_society_model_choice "
        "where workspace_id = %s and request_id = %s",
        (world["workspace"], request_id),
    ).fetchone()
    connection.commit()
    return row


def _departures(world, grant_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _crossings(world)
        if row["kind"] == "departure"
        and row["document"]["departure_id"]
        and row["crossing_id"]
        in {
            uuid.UUID(_departure_id(grant_id, str(row["thing_id"]), reason))
            for reason in ("grant_ended", "sent_away")
        }
    ]


def test_a_world_grant_s_visitor_is_decided_for_by_its_mind_and_never_asked_through_the_door(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, "world-0001", traveller=traveller)
        arrival = str(uuid.uuid4())
        sent = _arrive(client, channel, arrival, carried=[])
        assert sent.status_code == 201, sent.text
        thing_id = sent.json()["thing_id"]
        # A bridge cannot say who decides: the arrival's body has no such field.
        claimed = client.post(
            "/door/channel/arrivals",
            headers=channel,
            json={
                "arrival_id": str(uuid.uuid4()),
                "game_type": "player",
                "look_key": "otherwise",
                "carried": [],
                "decided_by": "program",
            },
        )
        assert claimed.status_code == 422
        # A program grant's arrival states nobody, as before the world could decide.
        _program_id, program = _opened(client, door, "program-0001", visitors_decided_by="program")
        programs = _arrive(client, program, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    documents = {str(row["thing_id"]): row["document"] for row in _crossings(world)}
    assert documents[thing_id]["decided_by"] == "world"
    assert "decided_by" not in documents[programs]

    host, _manifest, model_id = _host(door, _Knight())
    for _ in range(6):
        society = _minute(door, host, world, society)
        connection = world["connection"]
        decided = connection.execute(
            "select d.document->'provider' as provider from world_society_decision d "
            "join world_society_decision_request r on r.workspace_id = d.workspace_id "
            " and r.society_id = d.society_id and r.request_id = d.request_id "
            "where d.workspace_id = %s and r.subject_id = %s",
            (world["workspace"], uuid.UUID(thing_id)),
        ).fetchall()
        connection.commit()
        if decided:
            break
    else:
        raise AssertionError("the world-decided visitor was never decided for in six minutes")
    assert {row["provider"].get("model_id") for row in decided} == {model_id}
    asked = (
        world["connection"]
        .execute(
            "select count(*) as n from door_ask where workspace_id = %s and grant_id = %s",
            (world["workspace"], uuid.UUID(grant_id)),
        )
        .fetchone()
    )
    world["connection"].commit()
    assert asked["n"] == 0
    [visitor] = [v for v in _visitors(society) if v["id"] == thing_id]
    assert visitor["crossing"]["decided_by"] == "world"


def test_naming_a_traveller_mind_needs_model_invoke_and_is_recorded_with_the_grant(
    door, crossings, monkeypatch
):
    world, _society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        unpaid = _issue(
            client,
            door,
            "world-unpaid",
            headers={"Authorization": f"Bearer {UNPAID}"},
            traveller=traveller,
        )
        assert (unpaid.status_code, unpaid.json()["code"]) == (403, "not_authorised")
        assert "model.invoke" in unpaid.json()["detail"]
        params = {"world_id": world["binding"].world_id}
        assert client.get("/door/grants", headers=OWNER, params=params).json()["grants"] == []
        # Without a mind, the same owner without model.invoke issues a world grant.
        plain = _issue(client, door, "world-plain", headers={"Authorization": f"Bearer {UNPAID}"})
        assert plain.status_code == 201, plain.text

        issued = _issue(client, door, "world-mind", traveller=traveller)
        assert issued.status_code == 201, issued.text
        grant = issued.json()["grant"]
        assert grant["scope"]["visitors_decided_by"] == "world"
        recorded = _choice(world, uuid.uuid5(uuid.UUID(grant["grant_id"]), "traveller"))
        assert recorded is not None
        ends = dt.datetime.fromisoformat(grant["expires_at"]).astimezone(dt.UTC)
        assert recorded["document"]["group"] == {
            "kind": "arrivals_under_grant",
            "grant_id": grant["grant_id"],
            "ends_at": ends.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        assert recorded["document"]["decider"] == {"kind": "model", **traveller}
        # The same issue again is the same grant and the same choice; another model under its
        # key, or none, is another grant.
        again = _issue(client, door, "world-mind", traveller=traveller)
        assert again.status_code == 200, again.text
        other = _issue(
            client,
            door,
            "world-mind",
            traveller={"provider": traveller["provider"], "model_id": "another/model"},
        )
        assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reused")
        bare = _issue(client, door, "world-mind")
        assert (bare.status_code, bare.json()["code"]) == (409, "idempotency_key_reused")
        # A mind is named only for visitors the world decides for, and only one it may run.
        program = _issue(
            client, door, "program-mind", visitors_decided_by="program", traveller=traveller
        )
        assert (program.status_code, program.json()["code"]) == (422, "invalid_scope")
        unknown = _issue(
            client,
            door,
            "world-unknown",
            traveller={"provider": traveller["provider"], "model_id": "nobody/offers-this"},
        )
        assert unknown.status_code == 422
        assert unknown.json()["code"] in {"model_not_declared", "model_not_offered"}


def test_revoking_releases_the_traveller_mind_and_running_out_lapses_it(
    door, crossings, monkeypatch
):
    world, _society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        revoked_id, _channel = _opened(client, door, "world-revoked", traveller=traveller)
        assert client.post(f"/door/grants/{revoked_id}/revoke", headers=OWNER).status_code == 200
        released = _choice(world, uuid.uuid5(uuid.UUID(revoked_id), "traveller-release"))
        assert released is not None
        assert released["document"]["decider"] == {"kind": "routine"}
        assert released["chosen_by"] == world["session"].actor
        # The named things' key is not the mind's.
        assert _choice(world, uuid.uuid5(uuid.UUID(revoked_id), "release")) is None
        # The same issue repeated after the end answers with the grant and records nothing, so
        # nothing revives the gate's mind.
        repeated = _issue(client, door, "world-revoked", traveller=traveller)
        assert (repeated.status_code, repeated.json()["grant"]["state"]) == (200, "revoked")
        connection = world["connection"]
        minds = connection.execute(
            "select count(*) as n from world_society_model_choice "
            "where workspace_id = %s and document->'group'->>'grant_id' = %s",
            (world["workspace"], revoked_id),
        ).fetchone()
        connection.commit()
        assert minds["n"] == 2

        lapsed_id, _channel = _opened(client, door, "world-lapsed", traveller=traveller)
        _expire(world, lapsed_id)
        assert client.get(f"/door/grants/{lapsed_id}", headers=OWNER).status_code == 200
        lapse = uuid.uuid5(uuid.UUID(lapsed_id), "traveller-lapse")
        lapsed = _choice(world, lapse)
        assert lapsed is not None
        assert lapsed["document"]["decider"] == {"kind": "routine"}
        assert lapsed["chosen_by"] == grant_actor(uuid.UUID(lapsed_id))
        # Reading it again settles nothing more.
        assert client.get(f"/door/grants/{lapsed_id}", headers=OWNER).status_code == 200
        connection = world["connection"]
        count = connection.execute(
            "select count(*) as n from world_society_model_choice "
            "where workspace_id = %s and document->'group'->>'grant_id' = %s",
            (world["workspace"], lapsed_id),
        ).fetchone()
        connection.commit()
        assert count["n"] == 2


def test_a_grant_that_ran_out_sends_its_visitors_home_when_the_door_reads_it(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        polled_id, polled = _opened(client, door, "world-polled", traveller=traveller)
        _frames_read, cursor = _read_from(client, polled, _hello_cursor(client, polled))
        first = _arrive(client, polled, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        read_id, read = _opened(client, door, "world-read", traveller=traveller)
        second = _arrive(client, read, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        assert {visitor["id"] for visitor in _visitors(society)} == {first, second}
        _expire(world, polled_id)
        _expire(world, read_id)
        # Its bridge's next poll settles the first; its owner's read of the world's grants the
        # second.
        frames, cursor = _read_from(client, polled, cursor)
        assert [row["thing_id"] for row in _departures(world, polled_id)] == [uuid.UUID(first)]
        listed = client.get(
            "/door/grants", headers=OWNER, params={"world_id": world["binding"].world_id}
        )
        assert listed.status_code == 200
        assert [row["thing_id"] for row in _departures(world, read_id)] == [uuid.UUID(second)]
        society = _step(client, world, society)
        assert _visitors(society) == []
        frames, cursor = _read_from(client, polled, cursor)
        kinds = [frame["kind"] for frame in frames]
        assert kinds[-2:] == ["departed", "grant_ended"], kinds


def _swept(grants: int, departures: int, failed: int = 0, stuck=()) -> dict[str, Any]:
    return {"grants": grants, "departures": departures, "failed": failed, "stuck": list(stuck)}


def _finder(spine_schema) -> Database:
    """The role that reads every workspace's rows for the sweep, on the test's schema."""
    _psycopg, scratch = spine_schema
    return Database(
        url=make_conninfo(env_get("TEST_DATABASE_URL"), options=f"-csearch_path={scratch},public")
    )


def _hello_cursor(client, channel) -> str:
    said = client.post(
        "/door/channel/hello",
        headers=channel,
        json={
            "adapter_version": door_support.ADAPTER_VERSION,
            "mapping": _traveller_mapping(),
            "reads": door_support.READS,
        },
    )
    assert said.status_code == 200, said.text
    return said.json()["cursor"]


def _read_from(client, channel, cursor: str) -> tuple[list[dict[str, Any]], str]:
    read = client.get("/door/channel/frames", headers=channel, params={"after": cursor})
    assert read.status_code == 200, read.text
    return read.json()["frames"], read.json()["cursor"]


def test_the_maintenance_sweep_settles_grants_nobody_reads(
    door, crossings, monkeypatch, spine_schema
):
    world, society = _world(door)
    _psycopg, scratch = spine_schema
    finder = Database(
        url=make_conninfo(env_get("TEST_DATABASE_URL"), options=f"-csearch_path={scratch},public")
    )
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, "world-swept", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        # The arm before: a grant that stands is not swept.
        assert sweep(finder, door["database"]) == _swept(0, 0)
        _expire(world, grant_id)
        assert sweep(finder, door["database"]) == _swept(1, 1)
        assert [row["thing_id"] for row in _departures(world, grant_id)] == [uuid.UUID(thing_id)]
        assert _choice(world, uuid.uuid5(uuid.UUID(grant_id), "traveller-lapse")) is not None
        assert sweep(finder, door["database"]) == _swept(0, 0)
        society = _step(client, world, society)
        assert _visitors(society) == []


def test_a_bridge_calls_its_visitor_home_with_its_owner_s_departure_once(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, "world-home", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        leaving = _departure_id(grant_id, thing_id, "sent_away")
        called = client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})
        assert (called.status_code, called.json()) == (
            202,
            {"departure_id": leaving, "recorded": True},
        )
        again = client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})
        assert (again.status_code, again.json()) == (
            202,
            {"departure_id": leaving, "recorded": False},
        )
        # The owner's send-away finds the same departure written.
        sent = client.post(
            f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
        )
        assert sent.status_code == 202
        assert [str(row["crossing_id"]) for row in _departures(world, grant_id)] == [leaving]
        stranger = client.post(
            "/door/channel/home", headers=channel, json={"thing_id": str(uuid.uuid4())}
        )
        assert (stranger.status_code, stranger.json()["code"]) == (404, "unknown_reference")
        society = _step(client, world, society)
        assert _visitors(society) == []
        assert client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER).status_code == 200
        ended = client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})
        assert (ended.status_code, ended.json()["code"]) == (410, "grant_ended")


def test_a_visitor_the_world_decides_for_is_one_of_its_beings_to_its_owner(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        _grant_id, channel = _opened(client, door, "world-beings", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        scope, _root, society_route = routes(world)
        models = client.get(society_route + "/models", headers=OWNER, params=scope)
        assert models.status_code == 200, models.text
        assert [entry["subject_id"] for entry in models.json()["outside"]] == []
        chosen = client.post(
            society_route + "/models",
            headers=OWNER,
            params=scope,
            json={"idempotency_key": str(uuid.uuid4()), "people": [thing_id], "model": traveller},
        )
        assert chosen.status_code in (200, 201), chosen.text


def test_a_visitor_the_world_decides_for_is_never_handed_to_a_program(door, crossings, monkeypatch):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        _grant_id, channel = _opened(client, door, "world-kept", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        assert [v["id"] for v in _visitors(society)] == [thing_id]
        params = {"world_id": world["binding"].world_id}
        named = client.post(
            "/door/grants",
            headers=OWNER,
            params=params,
            json={
                "idempotency_key": "a-program-for-a-visitor",
                "bridge": "test-bridge",
                "things": [thing_id],
                "version_id": str(world["binding"].version_id),
            },
        )
        # The world decides for it; no grant hands it to an outside program
        # (docs/decision-roles-contract.md).
        assert (named.status_code, named.json()["code"]) == (409, "decided_from_outside")
        listed = client.get("/door/grants", headers=OWNER, params=params).json()["grants"]
        assert [grant["scope"]["things"] for grant in listed] == [[]]


def test_a_world_grant_takes_no_visitor_of_a_kind_no_world_mind_may_decide_for(
    door, crossings, monkeypatch
):
    _world(door)
    with _application(door, monkeypatch) as (client, _traveller):
        _grant_id, channel = _opened(client, door, "world-visitors", door_support.mapping())
        refused = _arrive(client, channel, str(uuid.uuid4()), carried=[])
        assert (refused.status_code, refused.json()["code"]) == (422, "kind_not_world_decided")


@pytest.mark.parametrize(
    ("request_kind", "answered"), [("arrival", 410), ("delivery", 404), ("home", 410)]
)
def test_a_grant_that_ran_out_is_settled_by_any_request_of_its_bridge(
    door, crossings, monkeypatch, request_kind, answered
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, f"world-{request_kind}", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        _expire(world, grant_id)
        if request_kind == "arrival":
            answer = _arrive(client, channel, str(uuid.uuid4()), carried=[])
        elif request_kind == "delivery":
            answer = client.post(
                f"/door/channel/departures/{uuid.uuid4()}/delivered",
                headers=channel,
                json={"delivered": [], "not_delivered": []},
            )
        else:
            answer = client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})
        assert answer.status_code == answered, answer.text
        assert [row["thing_id"] for row in _departures(world, grant_id)] == [uuid.UUID(thing_id)]


def test_an_issue_sent_again_naming_a_mind_its_first_did_not_is_refused(
    door, crossings, monkeypatch
):
    _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        first = _issue(client, door, "world-no-mind-first")
        assert first.status_code == 201, first.text
        again = _issue(client, door, "world-no-mind-first", traveller=traveller)
        assert (again.status_code, again.json()["code"]) == (409, "idempotency_key_reused")


def test_the_sweep_hands_back_the_mind_of_a_grant_that_ran_out_with_no_visitor(
    door, crossings, monkeypatch, spine_schema
):
    _world(door)
    world = door["world"]
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, _channel = _opened(client, door, "world-mind-only", traveller=traveller)
        _expire(world, grant_id)
        assert sweep(_finder(spine_schema), door["database"]) == _swept(1, 0)
        assert _choice(world, uuid.uuid5(uuid.UUID(grant_id), "traveller-lapse")) is not None


def test_a_bridge_calls_home_a_visitor_whose_arrival_no_minute_has_taken(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        _grant_id, channel = _opened(client, door, "world-home-early", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        called = client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})
        assert (called.status_code, called.json()["recorded"]) == (202, True)
        society = _step(client, world, society)
        assert _visitors(society) == []


def test_a_player_leaving_is_refused_for_a_visitor_the_world_decides_for(
    door, crossings, monkeypatch
):
    world, society = _world(door)
    with _application(door, monkeypatch) as (client, traveller):
        _grant_id, channel = _opened(client, door, "world-gone", traveller=traveller)
        thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        gone = client.post("/door/channel/gone", headers=channel, json={"thing_id": thing_id})
        assert (gone.status_code, gone.json()["code"]) == (409, "decided_by_world")
        assert "/door/channel/home" in gone.json()["detail"]


@pytest.mark.parametrize("fails", ["raising", "changing nothing"])
def test_a_grant_the_sweep_cannot_settle_is_held_back_and_named_until_it_is_settled(
    door, crossings, monkeypatch, spine_schema, fails
):
    world, society = _world(door)
    finder = _finder(spine_schema)
    with _application(door, monkeypatch) as (client, traveller):
        stuck_id, stuck = _opened(client, door, "world-stuck", traveller=traveller)
        stuck_visitor = _arrive(client, stuck, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        later_id, later = _opened(client, door, "world-later", traveller=traveller)
        later_visitor = _arrive(client, later, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        society = _step(client, world, society)
        _expire(world, stuck_id)  # the older end: first in the sweep's order
        _expire(world, later_id)
        held = [uuid.UUID(stuck_id)]
        settle = GrantRepository.settle

        def failing(self, grant_id):
            if str(grant_id) != stuck_id:
                return settle(self, grant_id)
            if fails == "raising":
                raise RuntimeError("this grant cannot be settled")
            return 0  # settled, it says, yet left as it was

        with monkeypatch.context() as broken:
            broken.setattr(GrantRepository, "settle", failing)
            failed = 1 if fails == "raising" else 0
            first = sweep(finder, door["database"], limit=1)
            assert first == _swept(0, 0, failed=failed, stuck=held)
            # Held back: the newer grant goes first, and the held one is still named.
            second = sweep(finder, door["database"], limit=1, deferred=first["stuck"])
            assert second == _swept(1, 1, stuck=held)
            assert [row["thing_id"] for row in _departures(world, later_id)] == [
                uuid.UUID(later_visitor)
            ]
            third = sweep(finder, door["database"], limit=1, deferred=second["stuck"])
            assert third == _swept(0, 0, failed=failed, stuck=held)
        assert sweep(finder, door["database"], limit=1, deferred=third["stuck"]) == _swept(1, 1)
        assert [row["thing_id"] for row in _departures(world, stuck_id)] == [
            uuid.UUID(stuck_visitor)
        ]


def test_the_sweep_looks_only_at_grants_that_ran_out_within_its_window(
    door, crossings, monkeypatch, spine_schema
):
    world, society = _world(door)
    finder = _finder(spine_schema)
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, "world-window", traveller=traveller)
        _arrive(client, channel, str(uuid.uuid4()), carried=[])
        society = _step(client, world, society)
        _expire(world, grant_id)  # ended a second ago
        with monkeypatch.context() as narrow:
            narrow.setattr(sweep_module, "SETTLE_WINDOW", dt.timedelta(milliseconds=500))
            assert sweep(finder, door["database"]) == _swept(0, 0)
        assert sweep(finder, door["database"]) == _swept(1, 1)


def test_a_settled_grant_read_again_waits_on_no_minute(door, crossings, monkeypatch):
    world, society = _world(door)
    runtime, workspace = door["database"], world["workspace"]
    with _application(door, monkeypatch) as (client, traveller):
        grant_id, channel = _opened(client, door, "world-settled-again", traveller=traveller)
        _arrive(client, channel, str(uuid.uuid4()), carried=[])
        society = _step(client, world, society)
        _expire(world, grant_id)
        grant = uuid.UUID(grant_id)
        with runtime.session(workspace) as connection:
            assert GrantRepository(connection, workspace, grant_actor(grant)).settle(grant) == 1
        # A minute holding the world's society: settling again reads that nothing is left first.
        with runtime.session(workspace) as minute, minute.transaction():
            minute.execute(
                "select 1 from world_society where workspace_id = %s and world_id = %s "
                "and version_id = %s for update",
                (workspace, world["binding"].world_id, world["binding"].version_id),
            )
            with runtime.session(workspace) as connection:
                connection.execute("set statement_timeout = '2s'")
                again = GrantRepository(connection, workspace, grant_actor(grant))
                assert again.settle(grant) == 0
