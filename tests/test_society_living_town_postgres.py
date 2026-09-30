"""The living town as a deployment stores it: a town made through the API, its society created
with the engine the table names for a town, advanced, decided for by a chosen model's receipt and
replayed from what it stored, as the runtime role under row-level security."""

from __future__ import annotations

import dataclasses
import uuid
from types import MappingProxyType

import pytest
from exulanica.selection.validation import Session
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import CREATES
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TOWN = CREATES["town"]
PERSON_ROLE = "society_decision"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as tests/test_generated_worlds.py
    tries its own, so an identity none of a preset's four candidates generate is never met."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _town_society(api) -> tuple[dict, str, dict]:
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A living town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": "region:generated", "profile": TOWN})
    assert created.status_code in (200, 201), created.text
    return entry, society, created.json()


def _step(api, entry: dict, body: dict) -> dict:
    stepped = api.post(
        f"/world/versions/{entry['authored_version_id']}/society/steps?world_id={entry['world_id']}",
        {"base_tick": body["current_tick"], "base_state_sha256": body["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


def _repository(api, connection, entry) -> SocietyRepository:
    runtime = api.client.app.state.services.society_runtime
    session = Session(workspace_id=api.repository.workspace_id, actor=api.actor)
    return SocietyRepository(
        connection,
        api.repository.workspace_id,
        world_id=entry["world_id"],
        input_authorizer=lambda document: runtime.authorize(connection, session, document),
    )


def test_a_town_s_society_is_the_living_town_its_people_at_home_and_it_replays(made):
    api = made
    entry, society, body = _town_society(api)
    state = body["state"]
    assert body["profile"] == TOWN == state["profile"]
    assert body["population_size"] == len(state["inhabitants"]) > 0
    assert all(person["location"]["indoors"] for person in state["inhabitants"])
    with api.database.session(api.repository.workspace_id) as connection:
        document = connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()["document"]
    assert document["profile"] == "exulanica.society-input/walking-surfaces-v2"
    assert document["population"]["size"] == body["population_size"]
    assert document["living"]["place"]["destinations"]
    for _ in range(3):
        body = _step(api, entry, body)
    assert body["current_tick"] == 3
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    # Asked again, the town's society is read back as it is, never a second one.
    again = api.post(society, {"region_id": "region:generated", "profile": TOWN})
    assert again.status_code in (200, 201), again.text
    assert again.json()["society_id"] == body["society_id"]


def test_a_saved_world_whose_input_carries_no_homes_gets_no_living_town(made):
    api = made
    starter = api.post("/world-entries/starter", {"title": "No town here"})
    assert starter.status_code == 200, starter.text
    entry = starter.json()
    region = entry["authored_scene"]["region"]["region_id"]
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    refused = api.post(society, {"region_id": region, "profile": TOWN})
    assert refused.status_code == 422, refused.text
    assert "carries its homes" in refused.json()["detail"]


def _decided(api, kind: str) -> tuple[dict, dict, str, dict]:
    """A town whose first free person at a choice point had a scripted model choose an option of
    ``kind`` for them, recorded as the host records a receipt, and the minute that consumed it
    stepped. Returns the entry, the society after that minute, the person and what was chosen."""
    entry, _society, body = _town_society(api)
    role = decision_roles().role(PERSON_ROLE)
    contract = role.contract()
    version_id = uuid.UUID(entry["authored_version_id"])
    config = {
        "provider": "scripted",
        "model_id": "scripted/stroller",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    subject = chosen = None
    for _ in range(90):
        with api.database.session(api.repository.workspace_id) as connection:
            society = _repository(api, connection, entry)
            row = society._row(version_id)
            latest = society._chain(row)
            source = society._inputs(row, [latest])[latest]
            for person in row["state"]["inhabitants"]:
                if person["work"] is not None or not role.adapter.due(row["state"], person["id"]):
                    continue
                options = role.adapter.options(
                    role, row["state"], source, person["id"], contract, seed=row["seed"]
                )
                if any(option.kind == "target" for option in options):
                    subject = person["id"]
                    break
            if subject is not None:
                decisions = SocietyDecisionRepository(society)
                request_id = uuid.uuid4()
                with connection.transaction():
                    reserved, fresh = decisions.prepare_role(
                        role,
                        version_id,
                        request_id=request_id,
                        subject_id=uuid.UUID(subject),
                        base_tick=row["current_tick"],
                        base_state_sha256=row["state_sha256"],
                        contract=contract,
                        provider_config=config,
                    )
                assert fresh
                request = reserved["request"]
                chosen = next(o for o in request["context"]["options"] if o["kind"] == kind)
                with connection.transaction():
                    decisions.finish(
                        version_id,
                        request_id,
                        {
                            "status": "accepted",
                            "reason": "validated_choice",
                            "proposal": {"label": chosen["label"], "option": chosen},
                            "provider": {
                                "provider": config["provider"],
                                "model_id": config["model_id"],
                                "served_model_id": config["model_id"],
                                "mechanism": config["mechanism"],
                                "prompt_version": config["prompt_version"],
                                "messages_sha256": "b" * 64,
                                "answers_asked": 1,
                                "calls": [],
                                "prompt_tokens": 300,
                                "completion_tokens": 40,
                                "cost_usd": "0.00002760",
                                "cost_known": True,
                                "latency_ms": 900,
                            },
                        },
                    )
                break
        body = _step(api, entry, body)
    assert subject is not None and chosen is not None, "nobody in the town came to a choice"
    # The minute that consumes the receipt, stored as the host's playback stores it.
    return entry, _step(api, entry, body), subject, chosen


def _events_and_replay(api, entry: dict, subject: str) -> list[dict]:
    events = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/events?world_id={entry['world_id']}"
    )
    assert events.status_code == 200, events.text
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    return [e for e in events.json()["events"] if e["subject_id"] == subject]


def test_a_chosen_model_s_receipt_decides_for_a_town_person_and_the_minute_replays(made):
    entry, body, subject, chosen = _decided(made, "target")
    theirs = _events_and_replay(made, entry, subject)
    [applied] = [e for e in theirs if e["event_kind"] == "decision_applied"]
    assert applied["document"]["disposition"] == "applied", (
        applied["document"]["disposition"],
        applied["document"]["reason"],
    )
    [selected] = [
        e
        for e in theirs
        if e["event_kind"] == "goal_selected" and e["tick"] == body["current_tick"]
    ]
    assert selected["document"]["decision"]["decided_by"] == "model"
    assert selected["document"]["goal"]["activity"] == chosen["activity"]


def test_a_chosen_model_s_wait_is_stored_and_replayed(made):
    """A model that chose to wait: the minute keeps the person where they are and records only
    the receipt's own event, a kind the store admits (a kind of the engine's own for waiting was
    refused by the event table's check, a 500 on the minute)."""
    entry, body, subject, chosen = _decided(made, "wait")
    theirs = _events_and_replay(made, entry, subject)
    [applied] = [e for e in theirs if e["event_kind"] == "decision_applied"]
    assert applied["document"]["disposition"] == "applied"
    assert applied["document"]["chose"] == chosen["label"]
    person = next(p for p in body["state"]["inhabitants"] if p["id"] == subject)
    assert person["action"]["reason"] == "waiting_a_minute"
    assert not [
        e
        for e in theirs
        if e["event_kind"] == "goal_selected" and e["tick"] == body["current_tick"]
    ]
