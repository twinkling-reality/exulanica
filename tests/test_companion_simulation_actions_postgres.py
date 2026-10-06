"""The Companion's simulation controls, sent the way any client sends them, on PostgreSQL.

Stage two of the action matrix: play, pause and speed (one configuration), time moved on by a
number of simulated minutes (a chain of control steps under one confirmation) and people brought
into a world with none. Every plan here is carried out as a direct client carries it out: each
step's exact request to the route it names, a later step's bases taken from the response to the
step before it, and the first refusal stopping the chain where it is. Every base a plan sends came
from the version's clock read, and what happened is read back from the controls' own receipts.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pytest
from exulanica.models.errors import TransportError
from exulanica.selection.action_plan import ACTION_PROMPT_VERSION
from exulanica.selection.validation import Session
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_engines import CREATES
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

from personal_world_support import OWNER_TOKEN as MADE_OWNER
from test_companion_actions_postgres import (
    COLLEAGUE,
    OWNER,
    READER,
    REGION,
    STALL,
    Actions,
    _compose,
    kind,
    reply,
    with_answers,
)
from test_companion_actions_postgres import actions as imported_actions  # noqa: F401
from test_society_made_world import made as imported_made  # noqa: F401
from test_society_person_decisions_postgres import _offered

pytestmark = pytest.mark.postgres

CONTROL = "PUT /world/versions/{version_id}/society/control"
CONTROL_STEP = "POST /world/versions/{version_id}/society/control/steps"
BRING_PEOPLE = "POST /world/versions/{version_id}/society"
#: The engine a starter's people are brought in with in these tests: it plays, and its people's
#: decisions take a chosen model.
PLAYABLE = "exulanica-society/v2"


@pytest.fixture(name="actions")
def _actions(request) -> Actions:
    return request.getfixturevalue("imported_actions")


@pytest.fixture(name="made")
def _made(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Each town is tried with the catalog's most candidates, as the living town's own tests do."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


# -- helpers ---------------------------------------------------------------------------------------


def _draft(action: str, *, speed: int | None = None, minutes: int | None = None):
    return reply({"action": action, "speed": speed, "minutes": minutes})


def _path(entry: Mapping[str, Any], tail: str) -> str:
    return f"/world/versions/{entry['authored_version_id']}{tail}?world_id={entry['world_id']}"


def _somewhere(actions: Actions, entry: Mapping[str, Any]) -> None:
    """A market stall placed, so people brought into the starter have somewhere to go."""
    _compose(actions, dict(entry), "cc0.market-stall", "stall", STALL)


def _people(actions: Actions, entry: Mapping[str, Any]) -> dict:
    _somewhere(actions, entry)
    created = actions.post(_path(entry, "/society"), {"region_id": REGION, "profile": PLAYABLE})
    assert created.status_code == 200, created.text
    return created.json()


def _control(api, entry: Mapping[str, Any]) -> dict:
    read = api.get(_path(entry, "/society/control"))
    assert read.status_code == 200, read.text
    return read.json()


def _clock(api, entry: Mapping[str, Any]) -> dict:
    read = api.get(_path(entry, "/clock"))
    assert read.status_code == 200, read.text
    return read.json()


def _play(actions: Actions, entry: Mapping[str, Any], *, speed: int = 1) -> dict:
    control = _control(actions, entry)
    played = actions.client.put(
        _path(entry, "/society/control"),
        json={"base_revision": control["revision"], "mode": "playing", "speed": speed},
        headers={"Authorization": f"Bearer {OWNER}"},
    )
    assert played.status_code == 200, played.text
    return played.json()


def _ask(actions: Actions, entry, version, utterance: str, *drafted, token: str = OWNER):
    actions.script(kind("simulation"), *drafted)
    return actions.ask(entry, version, utterance, token)


def _field(path: str, document: Mapping[str, Any]) -> Any:
    value: Any = document
    for key in path.split("."):
        value = value[key]
    return value


def _run(client, steps, token: str = OWNER, *, start: int = 0, responses=None) -> list:
    """Send a plan's steps from ``start`` the way any client does: each step's exact request, its
    ``body_from`` bases read from the response named, and the first refusal stopping the chain."""
    responses = list(responses or [])
    for step in steps[start:]:
        body = dict(step["body"])
        for field, source in (step.get("body_from") or {}).items():
            body[field] = _field(source["field"], responses[source["step"]].json())
        method, template = step["operation"].split(" ", 1)
        path = template.format(**step["bind"])
        response = client.request(
            method,
            f"{path}?world_id={step['query']['world_id']}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        responses.append(response)
        if not response.is_success:
            break
    return responses


def _outcome(api, entry: Mapping[str, Any], plan: Mapping[str, Any], responses=()) -> dict:
    """The outcome read of ``plan``, each step sent carrying the answer its own request got:
    ``responses`` are the chain's, in step order from the first, as :func:`_run` returns them."""
    read = api.post(
        f"/selection/actions/outcome?world_id={entry['world_id']}",
        {
            "version_id": plan["version_id"],
            "plan_sha256": plan["plan_sha256"],
            "steps": with_answers(plan["steps"], dict(enumerate(responses))),
        },
    )
    assert read.status_code == 200, read.text
    return read.json()


def _events(api, entry: Mapping[str, Any]) -> list[dict]:
    read = api.get(_path(entry, "/society/control/events"))
    assert read.status_code == 200, read.text
    return read.json()["events"]


def _held_in_project_context_shape(receipt: Mapping[str, Any], events: list[dict]) -> bool:
    """Whether a project's context finds this receipt the way it reads one: the version's control
    event of the operation's kind, by revision, and for a step by its minute and state."""
    stepped = receipt["operation"] == CONTROL_STEP
    for event in events:
        if event["kind"] != ("manual_step" if stepped else "configured"):
            continue
        if event["revision"] != receipt["revision"]:
            continue
        if stepped and (event["tick_to"], event["state_sha256"]) != (
            receipt["tick"],
            receipt["state_sha256"],
        ):
            continue
        return True
    return False


# -- play, pause and speed: one configuration ------------------------------------------------------


def test_pausing_is_the_control_request_pinned_to_the_clock_read_and_read_back(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    playing = _play(actions, entry)
    version = actions.version(entry)
    clock = _clock(actions, entry)
    before = actions.counts()

    plan = _ask(actions, entry, version, "pause everyone", _draft("pause")).json()

    assert plan["outcome"] == "plan", (plan["refusal"], plan["clarification"])
    assert actions.counts() == before, "planning wrote something"
    assert plan["clock"]["revision"] == clock["revision"]
    (step,) = plan["steps"]
    assert step["operation"] == CONTROL and step["confirmation"] == "required"
    assert step["body"] == {
        "base_revision": playing["revision"],
        "mode": "paused",
        "speed": 1,
        "base_clock_revision": clock["revision"],
    }
    assert step["pins"]["control_revision"] == clock["society"]["control_revision"]
    assert plan["spends"] is False
    assert _outcome(actions, entry, plan)["state"] == "not_applied"

    (sent,) = _run(actions.client, plan["steps"])
    assert sent.status_code == 200, sent.text
    assert _control(actions, entry)["mode"] == "paused"

    read = _outcome(actions, entry, plan, [sent])
    assert read["state"] == "applied"
    (receipt,) = read["steps"][0]["receipts"]
    assert receipt["revision"] == playing["revision"] + 1
    assert (receipt["tick"], receipt["state_sha256"]) == (None, None)
    assert _held_in_project_context_shape(receipt, _events(actions, entry))
    # The same confirmation sent again meets a control that moved past its base.
    (again,) = _run(actions.client, plan["steps"])
    assert (again.status_code, again.json()["code"]) == (409, "stale_society_state")
    assert _outcome(actions, entry, plan, [sent])["state"] == "applied"


def test_asking_for_what_the_controls_hold_changes_nothing(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    plan = _ask(actions, entry, version, "pause", _draft("pause")).json()
    assert plan["outcome"] == "refused"
    assert plan["refusal"]["code"] == "no_change"
    assert plan["steps"] == []


def test_a_speed_the_request_left_open_is_asked_about_and_prepared_with_no_model(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    asked = _ask(actions, entry, version, "change the speed", _draft("set_speed")).json()
    assert asked["outcome"] == "clarify"
    clarification = asked["clarification"]
    assert clarification["code"] == "speed_required"
    assert [c["value"] for c in clarification["candidates"]] == ["1", "2", "4"]
    calls = len(actions.transport.requests)

    # The open slot is filled with a candidate's value as the clarification gives it.
    four = next(c["value"] for c in clarification["candidates"] if c["value"] == "4")
    answered = {**clarification["actions"][0], "speed": four}
    prepared = actions.post(
        "/selection/actions/prepare",
        {
            "version_id": version["version_id"],
            "base_state_sha256": version["state_sha256"],
            "actions": [answered],
        },
        OWNER,
        entry["world_id"],
    )
    assert prepared.status_code == 200, prepared.text
    assert len(actions.transport.requests) == calls, "preparing asked a model"
    (step,) = prepared.json()["steps"]
    assert step["body"]["speed"] == 4 and step["body"]["mode"] == "paused"


# -- time moved on: a chain under one confirmation -------------------------------------------------


def test_a_paused_world_moves_on_by_the_chain_and_each_minute_is_its_receipt(actions):
    entry, _version = actions.starter()
    society = _people(actions, entry)
    version = actions.version(entry)

    plan = _ask(actions, entry, version, "move time on three minutes", _draft("advance", minutes=3))
    plan = plan.json()
    assert plan["outcome"] == "plan", (plan["refusal"], plan["clarification"])
    assert [step["operation"] for step in plan["steps"]] == [CONTROL_STEP] * 3
    assert [step["confirmation"] for step in plan["steps"]] == ["required", "chained", "chained"]

    responses = _run(actions.client, plan["steps"])
    assert [response.status_code for response in responses] == [200, 200, 200]
    after = _control(actions, entry)
    assert after["current_tick"] == society["current_tick"] + 3

    read = _outcome(actions, entry, plan, responses)
    assert read["state"] == "applied"
    ticks = [step["receipts"][0]["tick"] for step in read["steps"]]
    assert ticks == [society["current_tick"] + minute for minute in (1, 2, 3)]
    assert read["steps"][-1]["receipts"][0]["state_sha256"] == after["state_sha256"]
    events = _events(actions, entry)
    assert all(
        _held_in_project_context_shape(step["receipts"][0], events) for step in read["steps"]
    )
    assert read["current"]["society"]["tick"] == after["current_tick"]
    assert read["alternatives"] == []


def test_a_playing_world_is_paused_moved_on_and_played_again_at_its_speed(actions):
    entry, _version = actions.starter()
    society = _people(actions, entry)
    _play(actions, entry, speed=2)
    version = actions.version(entry)

    plan = _ask(actions, entry, version, "skip two minutes", _draft("advance", minutes=2)).json()
    assert [step["operation"] for step in plan["steps"]] == [
        CONTROL,
        CONTROL_STEP,
        CONTROL_STEP,
        CONTROL,
    ]
    responses = _run(actions.client, plan["steps"])
    assert [response.status_code for response in responses] == [200] * 4
    control = _control(actions, entry)
    assert (control["mode"], control["speed"]) == ("playing", 2)
    assert control["current_tick"] == society["current_tick"] + 2
    assert _outcome(actions, entry, plan, responses)["state"] == "applied"


def _playback_minute(actions: Actions) -> None:
    """One minute of playback, as the host's playback worker claims and runs it."""
    workspace = actions.repository.workspace_id
    database, runtime = actions.services.database, actions.services.society_runtime
    with database.session(workspace) as connection:
        connection.execute(
            "update world_society_control set next_due_at=clock_timestamp()-interval '1 minute' "
            "where workspace_id=%s",
            (workspace,),
        )

    def authorizer(connection):
        return lambda actor, doc: runtime.authorize(
            connection, Session(workspace_id=workspace, actor=actor), doc
        )

    with database.session(workspace) as connection:
        claim = SocietyControlRepository.claim_in_workspace(
            connection, workspace, input_authorizer=authorizer(connection)
        )
    assert claim is not None
    with database.session(workspace) as connection:
        SocietyControlRepository(
            connection, workspace, world_id=claim.world_id, input_authorizer=authorizer(connection)
        ).execute(claim, max_ticks=1)


def test_a_world_that_plays_on_until_its_pause_is_read_from_where_the_pause_left_it(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    _play(actions, entry)
    version = actions.version(entry)
    plan = _ask(actions, entry, version, "skip two minutes", _draft("advance", minutes=2)).json()
    pinned = plan["steps"][0]["pins"]["tick"]
    # The world plays on between the plan and the person's confirmation.
    _playback_minute(actions)
    assert _control(actions, entry)["current_tick"] == pinned + 1

    (paused,) = _run(actions.client, plan["steps"][:1])
    assert paused.status_code == 200, paused.text
    stopped = _outcome(actions, entry, plan, [paused])
    # Its first minute is still to be sent, from where the pause left the world.
    assert [step["state"] for step in stopped["steps"]] == [
        "applied",
        "not_applied",
        "not_applied",
        "not_applied",
    ]
    assert stopped["alternatives"] == ["play"]

    rest = _run(actions.client, plan["steps"], start=1, responses=[paused])
    # The pause's own answer, then the two minutes and the play sent after it.
    assert [response.status_code for response in rest] == [200, 200, 200, 200]
    read = _outcome(actions, entry, plan, rest)
    assert read["state"] == "applied"
    assert [step["receipts"][0]["tick"] for step in read["steps"][1:3]] == [
        pinned + 2,
        pinned + 3,
    ]
    assert read["alternatives"] == []


def test_the_same_minute_sent_by_another_client_is_never_that_steps_record(actions):
    """Another client, here the same person in another tab, runs the step's minute first from the
    same bases, and the step's own request is refused as stale. That minute has the step's bases
    and is never the step's receipt: the step is superseded, and the other client's own answer is
    what credits that minute."""
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    plan = _ask(actions, entry, version, "move time on a minute", _draft("advance", minutes=1))
    (step,) = plan.json()["steps"]
    other = actions.post(_path(entry, "/society/control/steps"), dict(step["body"]))
    assert other.status_code == 200, other.text
    (again,) = _run(actions.client, [step])
    assert (again.status_code, again.json()["code"]) == (409, "stale_society_state")
    read = _outcome(actions, entry, plan.json(), [again])
    assert (read["state"], read["steps"][0]["receipts"]) == ("superseded", [])
    # Sent back without an answer: no record is credited either.
    assert _outcome(actions, entry, plan.json())["steps"][0]["state"] == "superseded"
    # The other client's answer names its own minute, which is then credited.
    theirs = _outcome(actions, entry, plan.json(), [other])
    assert theirs["state"] == "applied"
    (receipt,) = theirs["steps"][0]["receipts"]
    assert receipt["event_seq"] == other.json()["receipt"]["event_seq"]
    assert receipt["tick"] == other.json()["society"]["current_tick"]


def test_a_chain_stopped_after_its_pause_leaves_the_world_paused_and_offers_play(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    _play(actions, entry)
    version = actions.version(entry)
    plan = _ask(actions, entry, version, "skip two minutes", _draft("advance", minutes=2)).json()

    (paused,) = _run(actions.client, plan["steps"][:1])
    assert paused.status_code == 200, paused.text
    # Another client changes the paused world's speed first, from what the pause answered, so
    # the control the next minute is pinned to has moved.
    changed = actions.client.put(
        _path(entry, "/society/control"),
        json={"base_revision": paused.json()["revision"], "mode": "paused", "speed": 2},
        headers={"Authorization": f"Bearer {OWNER}"},
    )
    assert changed.status_code == 200, changed.text
    rest = _run(actions.client, plan["steps"], start=1, responses=[paused])
    stopped = rest[-1]
    assert len(rest) == 2, "the chain went on past a refusal"
    assert (stopped.status_code, stopped.json()["code"]) == (409, "stale_society_state")

    read = _outcome(actions, entry, plan, rest)
    assert [step["state"] for step in read["steps"]] == [
        "applied",
        "superseded",
        "not_applied",
        "not_applied",
    ]
    assert read["state"] == "partial"
    assert read["current"]["society"]["mode"] == "paused"
    assert read["alternatives"] == ["play"]
    # Nothing resumes it on its own.
    assert _control(actions, entry)["mode"] == "paused"


@pytest.mark.parametrize(
    ("minutes", "status", "steps"), [(0, 422, 0), (1, 200, 1), (10, 200, 10), (11, 422, 0)]
)
def test_the_server_takes_one_to_ten_minutes_and_no_other_count(actions, minutes, status, steps):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    prepared = actions.post(
        "/selection/actions/prepare",
        {
            "version_id": version["version_id"],
            "base_state_sha256": version["state_sha256"],
            "actions": [{"operation": "advance", "minutes": minutes}],
        },
        OWNER,
        entry["world_id"],
    )
    assert prepared.status_code == status, prepared.text
    if status == 200:
        assert len(prepared.json()["steps"]) == steps


def test_a_drafted_count_past_ten_is_refused_by_the_form_twice_and_never_planned(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    eleven = _draft("advance", minutes=11)
    plan = _ask(actions, entry, version, "skip eleven minutes", eleven, eleven).json()
    assert plan["refusal"]["code"] == "not_drafted"
    assert plan["steps"] == []
    assert [call["outcome"] for call in plan["execution"]["calls"]] == [
        "completed",
        "reply_refused",
        "reply_refused",
    ]


# -- spending, permission and the model's own failures ---------------------------------------------


def test_playing_a_world_whose_person_runs_on_a_chosen_model_is_said_to_spend(actions):
    """Only the playback worker asks a person's chosen model, before each minute it plays: a
    control step never does, so only the steps that play the world are said to spend."""
    entry, _version = actions.starter()
    society = _people(actions, entry)
    manifest, model_id = _offered()
    person = sorted(p["id"] for p in society["state"]["inhabitants"])[0]
    role = next(role for role in decision_roles() if role.subject == "person")
    with actions.services.database.session(actions.repository.workspace_id) as connection:
        SocietyModelChoiceRepository(
            connection, actions.repository.workspace_id, world_id=entry["world_id"]
        ).record_choice(
            uuid.UUID(entry["authored_version_id"]),
            role,
            request_id=uuid.uuid4(),
            subjects=[person],
            model={"provider": manifest.spec(model_id).provider, "model_id": model_id},
            chosen_by=actions.actor,
            manifest=manifest,
            contract=role.contract(),
        )
    version = actions.version(entry)
    stepped = _ask(actions, entry, version, "skip two minutes", _draft("advance", minutes=2))
    assert stepped.json()["spends"] is False and stepped.json()["spends_by"] == []
    played = _ask(actions, entry, version, "play", _draft("play")).json()
    assert played["spends"] is True and played["spends_by"] == [role.key]

    _play(actions, entry)
    version = actions.version(entry)
    chain = _ask(actions, entry, version, "skip a minute", _draft("advance", minutes=1)).json()
    assert chain["spends"] is True
    assert chain["spends_by"] == [role.key]
    assert [step["spends"] for step in chain["steps"]] == [False, False, True]
    paused = _ask(actions, entry, version, "pause", _draft("pause")).json()
    assert paused["spends"] is False and paused["spends_by"] == []


def test_a_grant_that_cannot_control_is_refused_before_a_draft_is_paid_for(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    actions.script(kind("simulation"))
    plan = actions.ask(entry, version, "pause everyone", READER).json()
    assert plan["refusal"]["code"] == "action_not_permitted"
    assert len(plan["execution"]["calls"]) == 1


def test_a_drafter_that_times_out_is_a_problem_carrying_what_was_spent(actions):
    entry, _version = actions.starter()
    _people(actions, entry)
    version = actions.version(entry)
    timed_out = TransportError("timed out", timed_out=True, reached_provider=None, retryable=False)
    before = actions.counts()
    response = _ask(actions, entry, version, "pause everyone", timed_out)
    assert response.status_code == 502, response.text
    problem = response.json()
    assert problem["code"] == "model_refused"
    assert [call["outcome"] for call in problem["execution"]["calls"]] == [
        "completed",
        "timed_out",
    ]
    assert problem["execution"]["prompt_version"] == ACTION_PROMPT_VERSION
    assert actions.counts() == before


# -- people brought in -----------------------------------------------------------------------------


def test_a_world_with_nobody_offers_bringing_people_in_and_brings_them(actions):
    entry, _version = actions.starter()
    _somewhere(actions, entry)
    version = actions.version(entry)
    refused = _ask(actions, entry, version, "pause everyone", _draft("pause")).json()
    assert refused["refusal"]["code"] == "action_unavailable"
    assert refused["refusal"]["capability"]["code"] == "society_unavailable"
    assert refused["refusal"]["alternatives"] == ["bring_people"]

    plan = _ask(actions, entry, version, "bring people in", _draft("bring_people")).json()
    (step,) = plan["steps"]
    assert step["operation"] == BRING_PEOPLE
    assert step["body"]["region_id"] == REGION
    (created,) = _run(actions.client, plan["steps"])
    assert created.status_code == 200, created.text
    read = _outcome(actions, entry, plan, [created])
    assert read["state"] == "applied"
    (receipt,) = read["steps"][0]["receipts"]
    assert receipt["society_id"] == created.json()["society_id"]
    assert receipt["region_id"] == REGION

    again = _ask(actions, entry, actions.version(entry), "bring people", _draft("bring_people"))
    assert again.json()["refusal"]["code"] == "no_change"


def test_people_a_colleague_brought_in_first_are_the_step_s_only_as_its_own_answer_says(actions):
    """The plan's step sent by a colleague first: the version holds the colleague's society, in
    the step's region and with its engine. Sent back with no answer, or a refusal, it is not the
    step's; the person's own request, idempotent, is answered with that society, and that answer
    credits it."""
    entry, _version = actions.starter()
    _somewhere(actions, entry)
    plan = _ask(actions, entry, actions.version(entry), "bring people in", _draft("bring_people"))
    plan = plan.json()
    (theirs,) = _run(actions.client, plan["steps"], token=COLLEAGUE)
    assert theirs.status_code == 200, theirs.text
    refused = {**plan["steps"][0], "answer": {"status": 409, "code": "society_exists"}}
    for steps in ([plan["steps"][0]], [refused]):
        read = _outcome(actions, entry, {**plan, "steps": steps})
        assert (read["steps"][0]["state"], read["steps"][0]["receipts"]) == ("superseded", [])
    (own,) = _run(actions.client, plan["steps"])
    assert own.status_code == 200, own.text
    assert own.json()["society_id"] == theirs.json()["society_id"]
    read = _outcome(actions, entry, plan, [own])
    assert read["steps"][0]["state"] == "applied"
    assert read["steps"][0]["receipts"][0]["society_id"] == own.json()["society_id"]


# -- the world clock: pins, the lead and what the page shows ---------------------------------------


def _town(api) -> dict:
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A coupled town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": CREATES["town"]}
    )
    assert created.status_code in (200, 201), created.text
    return entry


def _couple(api, entry: Mapping[str, Any], token: str = MADE_OWNER) -> dict:
    coupled = api.client.put(
        _path(entry, "/clock"),
        json={"base_revision": 0, "profile": "coupled"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert coupled.status_code == 200, coupled.text
    return coupled.json()


def _prepare(api, entry: Mapping[str, Any], action: Mapping[str, Any]) -> dict:
    version = api.version(entry)
    prepared = api.post(
        f"/selection/actions/prepare?world_id={entry['world_id']}",
        {
            "version_id": version["version_id"],
            "base_state_sha256": version["state_sha256"],
            "actions": [dict(action)],
        },
    )
    assert prepared.status_code == 200, prepared.text
    return prepared.json()


def test_a_coupled_town_stops_the_chain_at_its_lead_and_says_how_far_it_went(made):
    entry = _town(made)
    coupled = _couple(made, entry)
    assert coupled["lead_ticks"] == 2
    plan = _prepare(made, entry, {"operation": "advance", "minutes": 5})
    assert plan["clock"]["revision"] == coupled["revision"]
    assert all(step["body"]["base_clock_revision"] == coupled["revision"] for step in plan["steps"])

    responses = _run(made.client, plan["steps"], token=MADE_OWNER)
    assert [response.status_code for response in responses] == [200, 200, 409]
    assert responses[-1].json()["code"] == "clock_lead_exhausted"

    read = _outcome(made, entry, plan, responses)
    assert read["state"] == "partial"
    assert [step["state"] for step in read["steps"]] == [
        "applied",
        "applied",
        "not_applied",
        "not_applied",
        "not_applied",
    ]
    # The refused minute changed nothing: its bases still stand, so it can be sent again later.
    assert read["current"]["society"]["tick"] == read["steps"][1]["receipts"][0]["tick"]


def test_a_plan_made_before_the_clock_was_coupled_is_refused_as_stale(made):
    entry = _town(made)
    plan = _prepare(made, entry, {"operation": "advance", "minutes": 1})
    assert plan["steps"][0]["body"]["base_clock_revision"] == 0
    _couple(made, entry)
    (refused,) = _run(made.client, plan["steps"], token=MADE_OWNER)
    assert (refused.status_code, refused.json()["code"]) == (409, "stale_clock_revision")
    assert _outcome(made, entry, plan, [refused])["steps"][0]["state"] == "superseded"


def test_an_answer_about_a_coupled_towns_people_cites_no_minute_the_page_has_not_reached(actions):
    """A coupled town's people run ahead of what the page shows; an answer cites none of that.

    A generated town's people need not do anything in a given minute, so the town is moved on a
    minute at a time, its traffic sealing a minute whenever the people reach the lead, until it
    has recorded events both in minutes the page shows and in minutes it does not.
    """
    entry = _town(actions)
    _couple(actions, entry, OWNER)
    controller = actions.client.app.state.traffic_signal_controller
    version = uuid.UUID(entry["authored_version_id"])
    events_path = _path(entry, "/society/events") + "&limit=256"
    for _ in range(24):
        (stepped,) = _run(
            actions.client,
            _prepare(actions, entry, {"operation": "advance", "minutes": 1})["steps"],
        )
        if stepped.status_code == 409:
            assert stepped.json()["code"] == "clock_lead_exhausted", stepped.text
            controller.prepare_world(actions.repository.workspace_id, entry["world_id"], version)
            continue
        assert stepped.status_code == 200, stepped.text
        presented = _clock(actions, entry)["presented_through_tick"]
        events = actions.get(events_path).json()["events"]
        ahead = {event["event_id"] for event in events if event["tick"] > presented}
        seen = {event["event_id"] for event in events if event["tick"] <= presented}
        if ahead and seen:
            break
    else:
        pytest.fail("in 24 minutes the town recorded nothing both shown and ahead of the page")

    answered = _ask_recent(actions, entry)
    assert answered["abstained"] is None, answered["abstained"]
    cited = _cited_events(answered)
    # The positive arm: what the page shows is cited; the negative: nothing it has not reached.
    assert cited and set(cited) <= seen
    assert all(tick <= presented for tick in cited.values())


def _ask_recent(actions: Actions, entry: Mapping[str, Any]) -> dict:
    asked = actions.post(
        "/selection/ask",
        {
            "question": "What has happened lately?",
            "plan": {"intent": "society", "society": {"scope": "world", "aspect": "recent"}},
            "society_context": {"version_id": entry["authored_version_id"]},
        },
        OWNER,
        entry["world_id"],
    )
    assert asked.status_code == 200, asked.text
    return asked.json()


def _cited_events(answer: Mapping[str, Any]) -> dict[str, int]:
    """Each event an answer cites, by id, and its minute."""
    return {
        citation["event_id"]: citation["tick"]
        for citation in answer["simulation"].values()
        if citation["result_kind"] == "simulation_event"
    }
