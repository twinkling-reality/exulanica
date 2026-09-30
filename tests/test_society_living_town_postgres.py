"""The living town as a deployment stores it: a town made through the API, its society created
with the engine the table names for a town, advanced, decided for by a chosen model's receipt and
replayed from what it stored, as the runtime role under row-level security."""

from __future__ import annotations

import dataclasses
import time
import uuid
from types import MappingProxyType

import pytest
from exulanica.selection.validation import Session
from exulanica.world import society_catalogs
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import CREATES
from exulanica.world.society_living import town_routine
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

import test_world_objects_api as object_helpers
from society_living_fixtures import grid_input
from test_society_made_world import _place
from test_society_made_world import made as imported_made  # noqa: F401

objects_api = object_helpers.objects_api

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


def test_living_town_comparison_records_a_fourth_score_and_rereads_its_verdict(made):
    import hashlib

    from exulanica.api.society_comparison_start import development_seeds
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_catalogs import comparison_catalogs_for_engine
    from exulanica.world.society_comparison import play
    from exulanica.world.society_comparison_repository import SocietyComparisonRepository
    from exulanica.world.society_comparison_result import comparison_result, run_outcome
    from exulanica.world.society_decision_contract import person_role

    from comparison_support import development_body
    from test_society_living_comparison import _Choosing

    api = made
    entry, _society, town = _town_society(api)
    version_id = uuid.UUID(entry["authored_version_id"])
    comparison_id = uuid.uuid4()
    catalogs = comparison_catalogs_for_engine(TOWN)
    seeds = development_seeds(catalogs)[:2]
    body = development_body(catalogs)
    body["seeds"] = [hashlib.sha256(seed.encode()).hexdigest() for seed in seeds]
    body["group"] = {
        "people": sorted(person["id"] for person in town["state"]["inhabitants"][:4]),
        "source": {"kind": "named"},
    }
    body["others"] = [
        {
            "id": person["id"],
            "decider": {"kind": "routine"},
            "provider_config": None,
            "choice": None,
            "answering": None,
        }
        for person in sorted(town["state"]["inhabitants"][4:], key=lambda person: person["id"])
    ]
    with api.database.session(api.repository.workspace_id) as connection, connection.transaction():
        repository = SocietyComparisonRepository(_repository(api, connection, entry))
        definition = repository.define(
            version_id,
            comparison_id=comparison_id,
            body=body,
            created_by=api.actor,
            role=person_role(),
            catalogs=catalogs,
        )
        assert definition["scoring"]["catalogs"]["versions"]["society-person-score"] == 4
        for seed in seeds:
            for arm in body["arms"]:
                run_id = repository.reserve(comparison_id, arm=arm, seed=seed, created_by=api.actor)
                plan, recorded = repository.plan(comparison_id, run_id)
                played = play(plan, _Choosing())
                repository.append(comparison_id, run_id, played.requests, played.receipts)
                outcome = run_outcome(
                    plan,
                    recorded,
                    arm,
                    hashlib.sha256(seed.encode()).hexdigest(),
                    played,
                    None,
                    catalogs,
                )
                repository.finish(comparison_id, run_id, outcome)
    with api.database.session(api.repository.workspace_id) as connection:
        repository = SocietyComparisonRepository(_repository(api, connection, entry))
        row = repository.definition(version_id, comparison_id)
        result = comparison_result(
            row, repository.runs(comparison_id), catalogs, model_name=load_manifest().model_name
        )
        assert result["score_version"] == 4
        assert result["seeds"]
        assert result["verdict"]["code"]
        assert all(
            run["terms"]["need_thresholds"]
            for seed in result["seeds"]
            for run in seed["runs"].values()
        )
    reread = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/comparisons/"
        f"{comparison_id}?world_id={entry['world_id']}"
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["score_version"] == 4
    assert reread.json()["verdict"] == result["verdict"]


def test_a_saved_world_whose_input_carries_no_homes_gets_no_living_town(made):
    api = made
    starter = api.post("/world-entries/starter", {"title": "No town here"})
    assert starter.status_code == 200, starter.text
    entry = starter.json()
    region = entry["authored_scene"]["region"]["region_id"]
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    refused = api.post(society, {"region_id": region, "profile": TOWN})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "engine_not_for_this_ground"


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
    from exulanica.selection.calls import CallLog
    from exulanica.selection.plan import SocietyAspect, SocietyScope, SocietySelector
    from exulanica.selection.society_question import (
        SocietyContext,
        answer_about_society,
        read_scene,
    )

    with made.database.session(made.repository.workspace_id) as connection:
        runtime = made.client.app.state.services.society_runtime
        session = Session(workspace_id=made.repository.workspace_id, actor=made.actor)
        scene = read_scene(
            connection,
            made.repository.workspace_id,
            entry["world_id"],
            SocietyContext(uuid.UUID(entry["authored_version_id"]), uuid.UUID(subject)),
            authorize=lambda document: runtime.authorize(connection, session, document),
            question="What did their model decide?",
            saved=(),
        )
        answer = answer_about_society(
            scene,
            SocietySelector(scope=SocietyScope.SELECTED, aspect=SocietyAspect.RECENT),
            client=None,
            saved=(),
            log=CallLog(),
            max_tokens=1000,
        )
    assert answer.answer is not None
    assert any(event["event_kind"] == "decision_applied" for event in scene.selected_events), [
        event["event_kind"] for event in scene.selected_events
    ]
    said = " ".join(clause.text for clause in answer.answer.clauses)
    assert "model" in said.lower() and "[inhabitant A]" in said, [
        event["event_kind"] for event in scene.events
    ]
    assert "of 1000" not in said and "premises:" not in said


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


def test_the_living_town_is_refused_over_a_district_s_input(objects_api, repository):
    """The ground-to-engine pairing is the server's: a caller naming the living town over a
    district's input is refused by name, and nothing is written."""
    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (repository.workspace_id, place)
    )
    repository.connection.commit()
    version_id = uuid.UUID(api.version()["version_id"])
    document = grid_input(version_id=version_id)
    api.client.app.state.society_initial_input = lambda *_args: document
    api.client.app.state.society_input_authorizer = lambda _conn, _session, _value: None
    route = api.in_world(f"/world/versions/{version_id}/society")
    refused = api.post(route, {"place_id": str(place), "region_id": "region-a", "profile": TOWN})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "engine_not_for_this_ground"
    assert api.get(route).status_code == 404


def test_a_town_edited_after_its_routine_is_bumped_keeps_its_own_routine(made, monkeypatch):
    """A town's next input is made under the routine its society recorded, never the routine a
    new town is made under: after TOWN_ROUTINE_VERSIONS moves, an edit of a stored town still
    records an input its society reads, and it still advances and replays."""
    api = made
    entry, _society, body = _town_society(api)
    recorded = body["state"]["routine"]
    body = _step(api, entry, body)
    bumped = dict(society_catalogs.TOWN_ROUTINE_VERSIONS, **{"society-policy": 1})
    monkeypatch.setattr(society_catalogs, "TOWN_ROUTINE_VERSIONS", bumped)
    assert town_routine().binding() != recorded
    edited = _place(api, entry, "a-plate-in-town", "region:generated", x_mm=4_000, z_mm=-6_000)
    assert edited["authored_edit_seq"] > entry["authored_edit_seq"]
    with api.database.session(api.repository.workspace_id) as connection:
        inputs = connection.execute(
            "select i.input_seq,i.document->'living'->'routine' as routine "
            "from world_society_input i join world_society s using(workspace_id,society_id) "
            "where s.workspace_id=%s "
            "and s.world_id=%s and s.version_id=%s order by i.input_seq",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchall()
    assert [row["input_seq"] for row in inputs] == [1, 2]
    assert all(row["routine"] == recorded for row in inputs)
    body = _step(api, entry, body)
    assert body["input_seq"] == 2
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True


def test_the_decision_host_asks_a_chosen_model_for_a_town_person(made):
    """The host's decision phase, unchanged, asks the model the owner chose for a living town's
    person at the engine's own choice point, and the minute after it applies the receipt."""
    from exulanica.api.decision_host import DecisionHost
    from exulanica.epistemics.hosted_requests import no_place_released
    from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
    from exulanica.world.society_decision_contract import decision_contract, person_role
    from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository

    from test_society_person_decisions_postgres import _Chooser, _client, _offered

    api = made
    services = api.client.app.state.services
    workspace = api.repository.workspace_id
    entry, _society, body = _town_society(api)
    version_id = uuid.UUID(entry["authored_version_id"])
    free = [p["id"] for p in body["state"]["inhabitants"] if p["work"] is None][:2]
    manifest, model_id = _offered()
    spec = manifest.models[model_id]
    with services.database.session(workspace) as connection:
        SocietyModelChoiceRepository(
            connection, workspace, world_id=entry["world_id"]
        ).record_choice(
            version_id,
            person_role(),
            request_id=uuid.uuid4(),
            subjects=free,
            model={"provider": spec.provider, "model_id": model_id},
            chosen_by=api.actor,
            manifest=manifest,
            contract=decision_contract(),
        )
    transport = _Chooser()
    host = DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=_client(manifest, transport),
        workspaces=frozenset({workspace}),
        policy_for=lambda workspace_id: services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        ),
        manifest=manifest,
        manifest_sha256="a" * 64,
    )
    asked = False
    for _ in range(90):
        claim = ControlClaim(
            workspace_id=workspace,
            world_id=entry["world_id"],
            society_id=uuid.UUID(body["society_id"]),
            version_id=version_id,
            token=uuid.uuid4(),
            revision=1,
            actor=api.actor,
        )
        assert host.before_minute(claim, time.monotonic() + LEASE_SECONDS)
        body = _step(api, entry, body)
        if transport.requests:
            asked = True
            break
    assert asked, "no chosen town person came to a choice point"
    events = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/events?world_id={entry['world_id']}"
    ).json()["events"]
    applied = [e for e in events if e["event_kind"] == "decision_applied"]
    assert applied and applied[0]["subject_id"] in free
    assert applied[0]["document"]["model"]["model_id"] == model_id
    assert applied[0]["document"]["disposition"] == "applied", applied[0]["document"]["reason"]
