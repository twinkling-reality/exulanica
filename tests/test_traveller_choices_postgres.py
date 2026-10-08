"""A gate's travellers decided for by the world, through the choice record and against PostgreSQL.

The application connects as a provisioned runtime role. A saved world's society of things has a
gate; one visitor arrives saying the world decides for it, another stating nothing (its program
decides). What is shown:

*   the owner names the mind the gate's travellers get once, as a choice naming the group of
    arrivals under the gate's grant, and the host asks that model for the visitor the world decides
    for, and nobody for the one its program decides for;
*   the models read says where each decider comes from and lists each gate's mind;
*   a choice naming the visitor comes before the group's; the routine decides for a visitor past
    the contract's bound on the people models run; releasing the grant's choice hands its visitors
    back to the routine;
*   an owner's choice for the visitor its program decides for is still refused
    (``decided_from_outside``), and the table refuses a group choice naming people, or a choice
    naming neither.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import decision_contract, person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
import things_society_support as things_support
from test_society_lines_postgres import _Speaker
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
#: Every grant ends: an end an hour from when the tests ran.
_ENDS = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)


def _repository(connection, world) -> SocietyModelChoiceRepository:
    return SocietyModelChoiceRepository(
        connection, world["workspace"], world_id=world["binding"].world_id
    )


def _visitors(world, client):
    """The society with a world-decided visitor and a program-decided one, as (snapshot, world's,
    program's)."""
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
        snapshot = things_api._make_society(client, world)
        society_id = uuid.UUID(snapshot["society_id"])
        traveller = things_support.reference("traveller", 1)
        stream.hand(society_id, things_support.arrival(1, kind=traveller, decided_by="world"))
        stream.hand(society_id, things_support.arrival(2))
        # A kind that takes only an outside decider gets no mind from the gate.
        stream.hand(society_id, things_support.arrival(3, decided_by="world"))
        snapshot = stays._step(world, client, snapshot)
    finally:
        register_crossing_stream(None)
    visitors = {
        person["crossing"]["arrival_id"]: person
        for person in snapshot["state"]["inhabitants"]
        if person["came_by"] == "crossed"
    }
    ours = visitors[str(things_support.arrival(1).crossing_id)]
    theirs = visitors[str(things_support.arrival(2).crossing_id)]
    return snapshot, ours, theirs


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_gate_s_travellers_get_the_mind_its_owner_named(app):
    world, client = app
    services = decisions._services(client)
    snapshot, ours, theirs = _visitors(world, client)
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    role, contract, version = person_role(), decision_contract(), world["binding"].version_id
    key = uuid.uuid4()
    with services.database.session(world["workspace"]) as connection:
        repository = _repository(connection, world)
        chosen = repository.record_traveller_choice(
            version,
            role,
            request_id=key,
            grant_id=things_support.GRANT,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=contract,
            ends_at=_ENDS,
        )
        assert chosen["group"] == {
            "kind": "arrivals_under_grant",
            "grant_id": str(things_support.GRANT),
            "ends_at": _ENDS.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        assert (chosen["people"], chosen["decider"]["kind"]) == ([], "model")
        # The same key again is the same choice; another model under it is refused.
        again = repository.record_traveller_choice(
            version,
            role,
            request_id=key,
            grant_id=things_support.GRANT,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=contract,
            ends_at=_ENDS,
        )
        assert again["choice_seq"] == chosen["choice_seq"]
        with pytest.raises(ModelChoiceRefused) as refused:
            repository.record_traveller_choice(
                version,
                role,
                request_id=key,
                grant_id=things_support.GRANT,
                model=None,
                chosen_by=world["session"].actor,
                manifest=manifest,
                contract=contract,
                ends_at=_ENDS,
            )
        assert refused.value.code == "choice_key_reused"
        deciding = repository.deciding(version, role, contract)
        # The visitor the world decides for gets the gate's mind; the other is its program's.
        assert set(deciding) == {ours["id"]}
        assert (deciding[ours["id"]]["from"], deciding[ours["id"]]["model"]) == (
            "travellers",
            model,
        )
        # Past the contract's bound on the people models run, the routine decides for it.
        full = SimpleNamespace(value=lambda key: 0)
        assert repository.deciding(version, role, full)[ours["id"]]["decider"] == {
            "kind": "routine"
        }
        assert repository.deciding(version, role, full)[ours["id"]]["from"] == (
            "travellers_over_bound"
        )
    # The host asks the gate's model for the visitor the world decides for, and asks nobody for
    # the one its program decides for (no door here).
    transport = _Speaker()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    for _ in range(10):
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        receipts = decisions._decisions(services, world, snapshot)
        if receipts:
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("the gate's traveller was never asked in ten minutes")
    assert {receipt["subject_id"] for receipt in receipts} == {ours["id"]}
    assert receipts[0]["provider"]["model_id"] == model_id
    assert transport.requests
    # The models read says where each decider comes from and names each gate's mind.
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [entry] = read.json()["choices"]
    assert (entry["subject_id"], entry["from"]) == (ours["id"], "travellers")
    [gate] = read.json()["travellers"]
    assert (gate["grant_id"], gate["model"]["model_id"]) == (str(things_support.GRANT), model_id)
    with services.database.session(world["workspace"]) as connection:
        repository = _repository(connection, world)
        # A choice naming the visitor comes before the group's.
        repository.record_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            subjects=[ours["id"]],
            model=None,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=contract,
        )
        assert repository.deciding(version, role, contract)[ours["id"]]["from"] == "choice"
        # The visitor its program decides for takes no owner's choice.
        with pytest.raises(ModelChoiceRefused) as refused:
            repository.record_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                subjects=[theirs["id"]],
                model=model,
                chosen_by=world["session"].actor,
                manifest=manifest,
                contract=contract,
            )
        assert refused.value.code == "decided_from_outside"
        # Nor is the visitor the world decides for handed to another outside program.
        with pytest.raises(ModelChoiceRefused) as refused:
            repository.record_external_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                subjects=[ours["id"]],
                bridge="otherbridge",
                grant_id=uuid.UUID(int=0xB1),
                chosen_by=world["session"].actor,
                contract=contract,
            )
        assert refused.value.code == "decided_from_outside"
        # Releasing the grant's choice hands its travellers to the routine, once.
        released = repository.release_traveller_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            grant_id=things_support.GRANT,
            chosen_by=world["session"].actor,
            contract=contract,
        )
        assert released is not None and released["decider"] == {"kind": "routine"}
        # It ends with the grant, as the choice it released did.
        assert released["group"]["ends_at"] == _ENDS.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert repository.traveller_choices(version, role)[str(things_support.GRANT)][
            "decider"
        ] == {"kind": "routine"}
        assert (
            repository.release_traveller_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                grant_id=uuid.UUID(int=0xB0),
                chosen_by=world["session"].actor,
                contract=contract,
            )
            is None
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_table_holds_a_choice_to_people_or_a_group(app):
    world, client = app
    services = decisions._services(client)
    snapshot, ours, _theirs = _visitors(world, client)
    version, role = world["binding"].version_id, person_role()
    with services.database.session(world["workspace"]) as connection:
        repository = _repository(connection, world)
        society = repository._society(version, lock=False)
        base = {
            "profile": role.choice_profile,
            "society_id": str(society["society_id"]),
            "decider": {"kind": "routine"},
            "contract": decision_contract().binding(),
            "chosen_by": str(world["session"].actor),
        }
        group = {
            "kind": "arrivals_under_grant",
            "grant_id": str(things_support.GRANT),
            "ends_at": "2028-02-29T23:59:59Z",
        }
        cases = {
            "group_naming_people": {**base, "people": [ours["id"]], "group": group},
            "naming_neither": {**base, "people": []},
            # A gate's choice is one shape: its kind, its grant's id in canonical form, the
            # world's own mind; no other key, and never an outside program.
            "an_empty_group": {**base, "people": [], "group": {}},
            "another_kind_of_group": {
                **base,
                "people": [],
                "group": {**group, "kind": "everyone"},
            },
            "a_grant_in_capitals": {
                **base,
                "people": [],
                "group": {**group, "grant_id": group["grant_id"].upper()},
            },
            "a_group_with_more": {**base, "people": [], "group": {**group, "and": "more"}},
            "an_end_not_to_the_second": {
                **base,
                "people": [],
                "group": {**group, "ends_at": "2026-10-07T21:30:00.5Z"},
            },
            # Every grant ends, at an instant that exists.
            "no_end": {
                **base,
                "people": [],
                "group": {k: v for k, v in group.items() if k != "ends_at"},
            },
            "an_hour_past_the_day": {
                **base,
                "people": [],
                "group": {**group, "ends_at": "2026-10-07T24:00:00Z"},
            },
            "a_day_february_lacks": {
                **base,
                "people": [],
                "group": {**group, "ends_at": "2026-02-29T21:30:00Z"},
            },
            "the_thirty_first_of_a_short_month": {
                **base,
                "people": [],
                "group": {**group, "ends_at": "2026-09-31T21:30:00Z"},
            },
            "a_group_an_outside_program_decides_for": {
                **base,
                "people": [],
                "group": group,
                "decider": {"kind": "external", "bridge": "luanti", "grant_id": group["grant_id"]},
            },
        }
        for name, document in cases.items():
            request_id = uuid.uuid4()
            document = {**document, "choice_seq": 1, "request_id": str(request_id)}
            document["document_sha256"] = "0" * 64
            with pytest.raises(psycopg.errors.CheckViolation, match="names_its_subjects"):
                with connection.transaction():
                    repository._insert(
                        society["society_id"], 1, request_id, document, world["session"].actor
                    )
                pytest.fail(f"the table held a choice {name}")
        # The positive control: the same group naming no people is held.
        request_id = uuid.uuid4()
        document = {
            **base,
            "people": [],
            "group": group,
            "choice_seq": 1,
            "request_id": str(request_id),
            "document_sha256": "0" * 64,
        }
        with connection.transaction():
            held = repository._insert(
                society["society_id"], 1, request_id, document, world["session"].actor
            )
        assert held["group"] == group and held["people"] == []
    assert snapshot["society_id"]


class _Bound:
    """The person role's contract with its bound on the people models run set to ``places``."""

    def __init__(self, places: int) -> None:
        self.places = places
        self.contract = decision_contract()

    def value(self, key: str) -> int:
        if key == person_role().subjects_bound:
            return self.places
        return self.contract.value(key)

    def binding(self):
        return self.contract.binding()

    def __getattr__(self, name):
        # Everything else is the contract's own.
        return getattr(self.contract, name)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_visitor_that_left_keeps_no_model_place(app):
    world, client = app
    services = decisions._services(client)
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    role, version, actor = person_role(), world["binding"].version_id, world["session"].actor
    ours_id = str(things_support.arrival(1, decided_by="world").document["thing_id"])

    def choose(subject, contract):
        with services.database.session(world["workspace"]) as connection:
            return _repository(connection, world).record_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                subjects=[subject],
                model=model,
                chosen_by=actor,
                manifest=manifest,
                contract=contract,
            )

    snapshot, ours, _theirs = _visitors(world, client)
    assert ours["id"] == ours_id
    villager = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "populated")
    # One place: the visitor's model takes it, and a villager's is refused.
    choose(ours["id"], _Bound(1))
    with pytest.raises(ModelChoiceRefused) as refused:
        choose(villager["id"], _Bound(1))
    assert refused.value.code == "too_many_model_people"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_visitor_that_has_left_frees_its_model_place(app):
    # The positive half: the same visitor chosen for, then gone home, frees the one place.
    world, client = app
    services = decisions._services(client)
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    role, version, actor = person_role(), world["binding"].version_id, world["session"].actor
    ours_id = str(things_support.arrival(1, decided_by="world").document["thing_id"])
    snapshot, ours, _theirs = _visitors(world, client)
    assert ours["id"] == ours_id
    with services.database.session(world["workspace"]) as connection:
        _repository(connection, world).record_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            subjects=[ours_id],
            model=model,
            chosen_by=actor,
            manifest=manifest,
            contract=_Bound(1),
        )
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    try:
        stream.hand(uuid.UUID(snapshot["society_id"]), things_support.departure(ours_id, 1))
        snapshot = stays._step(world, client, snapshot)
    finally:
        register_crossing_stream(None)
    assert ours_id not in {p["id"] for p in snapshot["state"]["inhabitants"]}
    villager = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "populated")
    with services.database.session(world["workspace"]) as connection:
        chosen = _repository(connection, world).record_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            subjects=[villager["id"]],
            model=model,
            chosen_by=actor,
            manifest=manifest,
            contract=_Bound(1),
        )
    assert chosen["decider"]["kind"] == "model"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_gate_s_choice_decides_strictly_before_its_end(app):
    world, client = app
    services = decisions._services(client)
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    role, contract, version = person_role(), decision_contract(), world["binding"].version_id
    _snapshot, ours, _theirs = _visitors(world, client)
    now = datetime.now(UTC).replace(microsecond=0)
    for ends_at, decides in ((now + timedelta(hours=1), True), (now - timedelta(seconds=1), False)):
        with services.database.session(world["workspace"]) as connection:
            repository = _repository(connection, world)
            chosen = repository.record_traveller_choice(
                version,
                role,
                request_id=uuid.uuid4(),
                grant_id=things_support.GRANT,
                model=model,
                chosen_by=world["session"].actor,
                manifest=manifest,
                contract=contract,
                ends_at=ends_at,
            )
            assert chosen["group"]["ends_at"] == ends_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            assert (ours["id"] in repository.deciding(version, role, contract)) is decides
            # And the read of each gate's mind leaves an ended one out the same way.
            listed = str(things_support.GRANT) in repository.traveller_choices(version, role)
            assert listed is decides
    # An end not stated in UTC is refused before anything is written.
    with (
        services.database.session(world["workspace"]) as connection,
        pytest.raises(ValueError, match="UTC"),
    ):
        _repository(connection, world).record_traveller_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            grant_id=things_support.GRANT,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=contract,
            ends_at=datetime(2026, 10, 7, 21, 30),
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_a_society_of_things_takes_a_gate_s_choice(app):
    # A purposeful society takes no visitors, so no gate's mind is recorded for one.
    world, client = app
    services = decisions._services(client)
    stays._inhabited(world, client)
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    with (
        services.database.session(world["workspace"]) as connection,
        pytest.raises(ModelChoiceRefused) as refused,
    ):
        _repository(connection, world).record_traveller_choice(
            world["binding"].version_id,
            person_role(),
            request_id=uuid.uuid4(),
            grant_id=things_support.GRANT,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=decision_contract(),
            ends_at=_ENDS,
        )
    assert refused.value.code == "engine_takes_no_traveller_choice"
