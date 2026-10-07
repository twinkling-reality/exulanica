"""An outside program deciding for a saved world's person, as the deployed database and host
take it.

The application connects as a provisioned runtime role. A person's decider is recorded through the
choice repository's grant functions, as an outside program's door records it with its grant, and
the host's decision phase asks a scripted door (:class:`~exulanica.api.external_asking.
ExternalAsker`) with no model client at all. The minute is taken through the steps route and
replay through the replay route. What is shown:

*   the person is asked through the door, the receipt records the program's answer in its own
    fields with no cost, the minute applies it and says an outside program decided, and replay
    regenerates the history without the door;
*   a door that refuses before asking still leaves a receipt naming why, so silence is counted from
    the world's own records, and the routine decides;
*   a host with no door asks no outside program and writes nothing for the person;
*   an outside answer is never counted against the world's hour of model decisions, and the models
    read neither counts nor summarises it;
*   a choice names its decider (migration 0146), every first choice still reads as the routine or
    the model it names, and the table refuses a choice naming both, neither, or a person;
*   ending a grant hands its people back to their routine, a retry of its key returns the choice
    it recorded, and nobody who came from outside can be given a model or the routine by the
    world's owner;
*   a request a stopped host left open closes in the program's own terms, and a request any text
    of which would carry a saved name is undone, not sent;
*   in a society of things, a visitor is decided for by its own program from its arrival, and a
    grant names only beings whose kind allows an outside program (``decider_not_allowed``).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import time
import uuid
from typing import Any

import psycopg
import pytest
from exulanica.api import decision_host as host_module
from exulanica.api.decision_host import DecisionHost, world_hour
from exulanica.canonical import canonical_json
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import decision_contract, person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from psycopg.types.json import Jsonb

import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
import things_society_support as things_support
from test_society_person_decisions_postgres import (
    _choose,
    _claim,
    _decisions,
    _offered,
    _requests,
    _services,
)
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
BRIDGE = "luanti"
GRANT = uuid.UUID("5b4a3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d")
MAPPING = "b" * 64


class _Door:
    """An outside program's door: it states the grant as it stands, and answers each request with
    the first place its person could go, or refuses every ask before asking."""

    def __init__(self, refusal: str | None = None) -> None:
        self.refusal = refusal
        self.configured: list[tuple[uuid.UUID, str, str, dict[str, Any]]] = []
        self.asked: list[dict[str, Any]] = []

    def configuration(self, workspace_id, world_id, subject_id, decider):
        self.configured.append((workspace_id, world_id, subject_id, dict(decider)))
        told = {
            "kind": "external",
            "bridge": decider["bridge"],
            "grant_id": decider["grant_id"],
            "grant_seq": 1,
            "mapping_sha256": MAPPING,
            "deadline_ms": 2500,
        }
        return told, self.refusal

    def answer(self, workspace_id, world_id, request, ends_at):
        self.asked.append(copy.deepcopy(request))
        options = request["context"]["options"]
        option = next((o for o in options if o["kind"] == "target"), options[0])
        frame = canonical_json({"request_id": request["request_id"], "label": option["label"]})
        config = request["provider_config"]
        return {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": {
                "kind": "external",
                "bridge": config["bridge"],
                "adapter_version": "0.1.0",
                "grant_id": config["grant_id"],
                "grant_seq": config["grant_seq"],
                "mapping_sha256": config["mapping_sha256"],
                "answer_sha256": hashlib.sha256(frame).hexdigest(),
                "latency_ms": 5,
                "source_ref_sha256": None,
            },
        }


def _doorkeeping_host(world, services, door) -> DecisionHost:
    """The host as an application with a door and no model client composes it."""
    manifest, _model_id = _offered()
    return DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=None,
        workspaces=frozenset({world["workspace"]}),
        policy_for=lambda workspace_id: pytest.fail("no model is asked here"),
        manifest=manifest,
        manifest_sha256="a" * 64,
        external=door,
    )


def _offering_societies_of_things(client) -> None:
    """The application as a host that offers societies of things (``EXULANICA_SOCIETY_OF_THINGS``)
    composes it."""
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )


def _repository(connection, world) -> SocietyModelChoiceRepository:
    return SocietyModelChoiceRepository(
        connection, world["workspace"], world_id=world["binding"].world_id
    )


def _grant(services, world, people, *, grant=GRANT) -> dict[str, Any]:
    with services.database.session(world["workspace"]) as connection:
        return _repository(connection, world).record_external_choice(
            world["binding"].version_id,
            person_role(),
            request_id=uuid.uuid4(),
            subjects=people,
            bridge=BRIDGE,
            grant_id=grant,
            chosen_by=world["session"].actor,
            contract=decision_contract(),
        )


def _asked_until_decided(world, client, services, host, snapshot) -> dict[str, Any]:
    for _ in range(30):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        if _decisions(services, world, snapshot):
            return snapshot
        snapshot = stays._step(world, client, snapshot)
    raise AssertionError("the person reached no choice point in thirty minutes")


def _events(client, world, kind: str) -> list[dict[str, Any]]:
    scope, _, society = routes(world)
    events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    return [event for event in events if event["event_kind"] == kind]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_outside_program_decides_for_a_person_the_minute_applies_it_and_replay_needs_no_door(
    app,
):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    choice = _grant(services, world, [person])
    assert choice["profile"] == "exulanica.society-model-choice/v2"
    assert choice["decider"] == {"kind": "external", "bridge": BRIDGE, "grant_id": str(GRANT)}
    assert choice["model"] is None
    door = _Door()
    host = _doorkeeping_host(world, services, door)
    snapshot = _asked_until_decided(world, client, services, host, snapshot)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("accepted", "validated_choice")
    assert receipt["subject_id"] == person
    assert receipt["provider"]["kind"] == "external"
    assert "cost_usd" not in receipt["provider"]
    # The door was told the decider the choice names, and sent the sealed request.
    assert [entry[2:] for entry in door.configured] == [(person, choice["decider"])]
    [sent] = door.asked
    assert sent["provider_config"]["contract"] == decision_contract().binding()
    assert sent["provider_config"]["deadline_ms"] == 2500
    after = stays._step(world, client, snapshot)
    [applied] = [
        event
        for event in _events(client, world, "decision_applied")
        if event["tick"] == after["current_tick"]
    ]
    assert applied["document"]["origin"] == "external"
    assert applied["document"]["model"] is None
    assert "outside program" in applied["document"]["summary"]
    # An outside answer is no model decision: not counted in the world's hour, not summarised.
    with services.database.session(world["workspace"]) as connection:
        asked, spent = world_hour(
            connection, world["workspace"], world["binding"].world_id, person_role()
        )
    assert (asked, spent) == (0, 0)
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["by_model"] == [] and body["latest"] == []
    [named] = [entry for entry in body["choices"] if entry["subject_id"] == person]
    assert named["decider"] == choice["decider"] and named["model"] is None
    # Replay regenerates the history from what was stored, and the door hears nothing more.
    heard = len(door.asked)
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert len(door.asked) == heard


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_door_refusing_before_asking_leaves_a_receipt_and_the_routine_decides(app):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    _grant(services, world, [person])
    door = _Door(refusal="decider_disconnected")
    host = _doorkeeping_host(world, services, door)
    snapshot = _asked_until_decided(world, client, services, host, snapshot)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"]) == ("unavailable", "decider_disconnected")
    assert receipt["provider"] is None and receipt["proposal"] is None
    assert door.asked == []
    after = stays._step(world, client, snapshot)
    [applied] = [
        event
        for event in _events(client, world, "decision_applied")
        if event["tick"] == after["current_tick"]
    ]
    assert applied["document"]["origin"] == "external"
    assert applied["document"]["disposition"] == "unavailable"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_host_with_no_door_asks_no_outside_program_and_writes_nothing(app):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    _grant(services, world, [person])
    host = _doorkeeping_host(world, services, None)
    for _ in range(5):
        assert (
            host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS) is False
        )
        snapshot = stays._step(world, client, snapshot)
    assert _requests(services, world, snapshot) == 0


def _raw_choice(connection, world, society_id: str, document: dict[str, Any]) -> None:
    connection.execute(
        "insert into world_society_model_choice(workspace_id,world_id,society_id,"
        "choice_seq,request_id,document,document_sha256,chosen_by) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            world["workspace"],
            world["binding"].world_id,
            uuid.UUID(society_id),
            document["choice_seq"],
            uuid.UUID(document["request_id"]),
            Jsonb(document),
            document["document_sha256"],
            uuid.UUID(document["chosen_by"]),
        ),
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_choice_names_its_decider_and_every_first_choice_still_reads(app):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    manifest, model_id = _offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    chosen = _choose(services, world, [people[0]], model, manifest=manifest)
    assert chosen["profile"] == "exulanica.society-model-choice/v2"
    assert chosen["decider"] == {"kind": "model", **model} and "model" in chosen
    with services.database.session(world["workspace"]) as connection:
        stored = connection.execute(
            "select document from world_society_model_choice where workspace_id=%s "
            "and choice_seq=%s and society_id=%s",
            (world["workspace"], chosen["choice_seq"], uuid.UUID(chosen["society_id"])),
        ).fetchone()["document"]
    # What is stored names the decider alone; the model is what every read derives from it.
    assert "model" not in stored and stored["decider"] == {"kind": "model", **model}
    # A first choice, as every choice was written before the decider: read as the model it names.
    first = {
        "profile": "exulanica.society-model-choice/v1",
        "choice_seq": chosen["choice_seq"] + 1,
        "request_id": str(uuid.uuid4()),
        "society_id": chosen["society_id"],
        "people": [people[1]],
        "model": model,
        "contract": decision_contract().binding(),
        "chosen_by": chosen["chosen_by"],
        "document_sha256": "c" * 64,
    }
    with services.database.session(world["workspace"]) as connection:
        with connection.transaction():
            _raw_choice(connection, world, chosen["society_id"], first)
        current = _repository(connection, world).current(world["binding"].version_id, person_role())
    assert current[people[1]]["model"] == model
    assert current[people[1]]["decider"] == {"kind": "model", **model}
    assert current[people[0]]["model"] == model
    # The table holds a choice to exactly one of the two shapes, and never to a person.
    refused = [
        {**first, "decider": {"kind": "routine"}},
        {key: value for key, value in first.items() if key != "model"},
        {
            **{key: value for key, value in first.items() if key != "model"},
            "profile": "exulanica.society-model-choice/v2",
            "decider": {"kind": "person"},
        },
    ]
    for index, document in enumerate(refused):
        document = {
            **document,
            "choice_seq": first["choice_seq"] + 1,
            "request_id": str(uuid.uuid4()),
        }
        with (
            services.database.session(world["workspace"]) as connection,
            pytest.raises(psycopg.errors.CheckViolation) as caught,
            connection.transaction(),
        ):
            _raw_choice(connection, world, chosen["society_id"], document)
        assert caught.value.diag.constraint_name == (
            "world_society_model_choice_names_its_decider"
        ), index


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_ending_a_grant_hands_its_people_back_to_their_routine(app):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]][:2]
    _grant(services, world, people)
    with services.database.session(world["workspace"]) as connection:
        repository = _repository(connection, world)
        role, version = person_role(), world["binding"].version_id
        key = uuid.uuid4()
        released = repository.release_external_choice(
            version,
            role,
            request_id=key,
            grant_id=GRANT,
            chosen_by=world["session"].actor,
            contract=decision_contract(),
        )
        assert released is not None and released["people"] == sorted(people)
        assert released["decider"] == {"kind": "routine"}
        # A retry of the same key is answered with the choice it recorded, read under the lock.
        again = repository.release_external_choice(
            version,
            role,
            request_id=key,
            grant_id=GRANT,
            chosen_by=world["session"].actor,
            contract=decision_contract(),
        )
        assert again == released
        current = repository.current(version, role)
        assert {current[person]["decider"]["kind"] for person in people} == {"routine"}
        # Ended once, a grant decides for nobody: nothing more is recorded.
        assert (
            repository.release_external_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                grant_id=GRANT,
                chosen_by=world["session"].actor,
                contract=decision_contract(),
            )
            is None
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_nobody_who_came_from_outside_is_given_a_decider_by_the_world_s_owner(app, monkeypatch):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    held = SocietyModelChoiceRepository._society

    def visited(self, version_id, *, lock):
        row = dict(held(self, version_id, lock=lock))
        state = copy.deepcopy(row["state"])
        state["inhabitants"][0]["came_by"] = "crossed"
        return {**row, "state": state}

    monkeypatch.setattr(SocietyModelChoiceRepository, "_society", visited)
    manifest, model_id = _offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    for given in (model, None):
        with pytest.raises(ModelChoiceRefused) as caught:
            _choose(services, world, [person], given, manifest=manifest)
        assert caught.value.code == "decided_from_outside"
    with pytest.raises(ModelChoiceRefused) as caught:
        _grant(services, world, [person], grant=uuid.UUID(int=9))
    assert caught.value.code == "decided_from_outside"
    # The positive control: the same choice for somebody who did not come from outside is taken.
    other = snapshot["state"]["inhabitants"][1]["id"]
    assert _choose(services, world, [other], model, manifest=manifest)["people"] == [other]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_request_a_stopped_host_left_open_closes_in_the_program_s_own_terms(app, monkeypatch):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    _grant(services, world, [person])
    door = _Door()
    host = _doorkeeping_host(world, services, door)
    asked = DecisionHost._asked_by_every_role
    # A host that stops between reserving its requests and recording their answers.
    monkeypatch.setattr(DecisionHost, "_asked_by_every_role", lambda *_args, **_kwargs: [])
    for _ in range(30):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        if _requests(services, world, snapshot):
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("the person reached no choice point in thirty minutes")
    assert _decisions(services, world, snapshot) == []
    monkeypatch.setattr(DecisionHost, "_asked_by_every_role", asked)
    snapshot = stays._step(world, client, snapshot)
    host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    closed = [
        receipt
        for receipt in _decisions(services, world, snapshot)
        if receipt["reason"] == "no_answer_in_time" and receipt["subject_id"] == person
    ]
    assert closed and closed[0]["status"] == "unavailable" and closed[0]["provider"] is None
    stays._step(world, client, snapshot)
    said = [
        event
        for event in _events(client, world, "decision_applied")
        if event["document"].get("reason") == "no_answer_in_time"
        or event["document"].get("disposition_reason") == "no_answer_in_time"
    ]
    assert said and all(event["document"]["origin"] == "external" for event in said)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_request_that_would_carry_a_saved_name_is_undone_and_not_sent(app, monkeypatch):
    world, client = app
    services = _services(client)
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    _grant(services, world, [person])
    door = _Door()
    host = _doorkeeping_host(world, services, door)
    screened: list[dict[str, Any]] = []

    def carries_a_name(names, context):
        screened.append(context)
        return False

    monkeypatch.setattr(host_module, "outside_context_sendable", carries_a_name)
    for _ in range(12):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    # Every reserved request was screened in full, undone, and never sent.
    assert screened and door.configured
    assert door.asked == []
    assert _requests(services, world, snapshot) == 0
    assert _decisions(services, world, snapshot) == []


def test_the_test_door_answers_in_the_receipt_s_one_shape():
    """The scripted door's answer passes the shape check every outside answer meets, so the tests
    above read the host, not a malformed fixture."""
    from exulanica.world.deciders import check_external_record

    door = _Door()
    request = {
        "request_id": str(uuid.uuid4()),
        "context": {"options": [{"kind": "target", "label": "resting on a bench, 5 m away"}]},
        "provider_config": {
            "kind": "external",
            "bridge": BRIDGE,
            "grant_id": str(GRANT),
            "grant_seq": 1,
            "mapping_sha256": MAPPING,
            "contract": {"catalog_versions": {}, "sha256": "d" * 64},
            "deadline_ms": 2500,
        },
    }
    check_external_record(door.answer(None, "w", request, 0.0)["provider"])
    assert json.loads(json.dumps(door.asked[0])) == request


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_visitor_s_own_program_decides_for_it_from_its_arrival_with_no_choice_recorded(app):
    world, client = app
    _offering_societies_of_things(client)
    services = _services(client)
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
        snapshot = things_api._make_society(client, world)
        stream.hand(uuid.UUID(snapshot["society_id"]), things_support.arrival(1, grant_id=GRANT))
        snapshot = stays._step(world, client, snapshot)
        [visitor] = [p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "crossed"]
        door = _Door()
        host = _doorkeeping_host(world, services, door)
        snapshot = _asked_until_decided(world, client, services, host, snapshot)
        receipts = _decisions(services, world, snapshot)
        assert {receipt["subject_id"] for receipt in receipts} == {visitor["id"]}
        assert receipts[0]["provider"]["kind"] == "external"
        # The door was told the visitor's decider as its arrival records it, and nobody chose it.
        arrived_by = {
            "kind": "external",
            "bridge": things_support.BRIDGE,
            "grant_id": str(GRANT),
        }
        assert [entry[2:] for entry in door.configured] == [(visitor["id"], arrived_by)]
        with services.database.session(world["workspace"]) as connection:
            assert (
                _repository(connection, world).current(world["binding"].version_id, person_role())
                == {}
            )
        stays._step(world, client, snapshot)
        scope, _, society = routes(world)
        replayed = client.get(society + "/replay", headers=OWNER, params=scope)
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["replay_verified"] is True
    finally:
        register_crossing_stream(None)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_outside_program_decides_only_for_a_being_whose_kind_allows_it(app):
    world, client = app
    _offering_societies_of_things(client)
    services = _services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    snapshot = things_api._make_society(client, world)
    people = snapshot["state"]["inhabitants"]
    villager = next(person["id"] for person in people if person["came_by"] == "populated")
    [knight] = [person["id"] for person in people if person["came_by"] == "placed"]
    # A villager's kind allows the routine, a model and a person, never an outside program.
    with pytest.raises(ModelChoiceRefused) as caught:
        _grant(services, world, [villager])
    assert caught.value.code == "decider_not_allowed"
    with pytest.raises(ModelChoiceRefused) as caught:
        _grant(services, world, [villager, knight], grant=uuid.UUID(int=7))
    assert caught.value.code == "decider_not_allowed"
    # The positive control: a knight's kind allows one, and the same grant takes it.
    assert _grant(services, world, [knight])["people"] == [knight]
    with services.database.session(world["workspace"]) as connection:
        current = _repository(connection, world).current(world["binding"].version_id, person_role())
    assert set(current) == {knight}
