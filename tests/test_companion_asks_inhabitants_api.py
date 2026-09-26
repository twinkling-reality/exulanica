"""A person asks the Companion about the people in their world, through the deployed route.

Every question here goes to ``POST /selection/ask`` on the real application, connected as a
provisioned runtime role, over a saved world with the small square's people brought in and a few
minutes advanced. What is held:

*   A selected inhabitant's "why" is answered with no model call, in the inspector's words, cited to
    the society's state and to the event that explains it, every citation of truth class
    ``simulation`` and none a personal visit; no inhabitant's name is in the answer.
*   An unknown version, an unknown inhabitant and a version from another world answer alike.
*   A name that is part of a saved person's and an inhabitant's is refused by name.
*   "What happened" is composed through the workspace's hosted-request policy, from rebuilt event
    lines alone: no inhabitant's name, no stored summary, no position, no seed and no saved name
    reaches the request. A composed sentence that reports speech is refused, and the fixed words
    given instead.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.models.transport import HttpResponse
from exulanica.selection import question as question_module
from exulanica.selection import society_question
from exulanica.selection.plan import Intent, SelectionPlan, SocietyAspect, SocietyScope
from exulanica.selection.society_question import Framing, SocietyLineChoice
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.worlds import AUTHORED_STARTER
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
from conftest import TEST_CEILING_USD, TEST_MAX_CALLS, scratch_role_database
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER, TOKEN, place, routes
from tests_support_api import EVERY_PERMISSION
from world_support import registered_world

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_ask_inhabitants_suite"
#: Minutes advanced before asking: people have chosen, walked and arrived, so a state and the
#: event that explains it are both recorded.
MINUTES = 6
#: A person the account holder saved, whose first name the society's first inhabitant shares.
SAVED_SURNAME = "Cohen"
#: A second workspace's credential, for a society asked about from another workspace.
STRANGER_TOKEN = "saved-world-inhabitants-stranger-token-long-enough"
STRANGER = {"Authorization": f"Bearer {STRANGER_TOKEN}"}
#: The latest-events window for the late question: two, so explanations fall outside it.
WINDOW = 2


class _Scripted(FakeTransport):
    """A hosted model that plans every question as what happened in the world, and composes by
    choosing the first event line it was sent, or a token not in the list when told to."""

    def __init__(
        self,
        *,
        unknown: bool = False,
        plan: SelectionPlan | None = None,
        composer_fails: Exception | None = None,
    ) -> None:
        super().__init__()
        self.unknown = unknown
        self.plan = plan
        self.composer_fails = composer_fails
        #: The line each composer request was answered with, as it was sent.
        self.chosen: list[str] = []

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        system = payload["messages"][0]["content"]
        if system.startswith("You turn a question"):
            reply = (
                self.plan
                or SelectionPlan(
                    intent=Intent.SOCIETY,
                    society={"scope": SocietyScope.WORLD, "aspect": SocietyAspect.RECENT},
                )
            ).model_dump_json()
        elif self.composer_fails is not None:
            raise self.composer_fails
        else:
            sent = payload["messages"][1]["content"]
            token, line = re.search(r"^\[([A-Z0-9]{10})\] (.*)$", sent, re.MULTILINE).groups()
            self.chosen.append(line)
            reply = SocietyLineChoice(
                lines=["ZZZZZZZZZZ" if self.unknown else token], framing=Framing.RECORDED
            ).model_dump_json()
        return HttpResponse(status_code=200, text=json.dumps(chat_body(reply)))


@pytest.fixture
def world(saved_world, spine_schema, monkeypatch):
    """The saved world with people in it, and a way to open the application over it."""
    world = saved_world
    world["stranger"] = uuid.uuid4()
    world["connection"].commit()
    _psycopg, scratch = spine_schema
    provision_runtime_role(world["connection"], role=ROLE)
    database = scratch_role_database(scratch, ROLE)
    with database.session(world["workspace"]) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
                    "permissions": EVERY_PERMISSION,
                },
                STRANGER_TOKEN: {
                    "workspace_id": str(world["stranger"]),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                },
            }
        ),
    )

    def open_app(transport: FakeTransport | None = None) -> TestClient:
        model = (
            None
            if transport is None
            else ModelClient(
                api_key="test-key-not-real",
                transport=transport,
                budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
            )
        )
        services = Services(
            database=database,
            readonly_database=database,
            store=world["store"],
            tokens=load_token_directory(),
            executor_shares_the_write_role=True,
            model_client=model,
            society_runtime=SocietyRuntime(
                store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
            ),
        )
        return TestClient(create_app(services, verify=False), raise_server_exceptions=False)

    with open_app() as client:
        _inhabited(world, client)
    world["open_app"] = open_app
    return world


def _inhabited(world, client) -> None:
    """Three places to rest and one to visit, people brought in, and a few minutes advanced."""
    for index, (x_mm, z_mm) in enumerate(((3_000, 5_000), (-3_000, 5_000), (0, 9_000))):
        place(client, world, f"object:plate-{index}", x_mm, z_mm)
    place(client, world, "object:pillar", 6_000, 9_000, asset="pillar")
    scope, _, society = routes(world)
    created = client.post(
        society,
        headers=OWNER,
        params=scope,
        json={
            "region_id": world["binding"].region_id,
            "seed": "7a" * 32,
            "profile": "exulanica-society/v2",
        },
    )
    assert created.status_code in (200, 201), created.text
    for _ in range(MINUTES):
        snapshot = client.get(society, headers=OWNER, params=scope).json()
        stepped = client.post(
            society + "/steps",
            headers=OWNER,
            params=scope,
            json={
                "base_tick": snapshot["current_tick"],
                "base_state_sha256": snapshot["state_sha256"],
            },
        )
        assert stepped.status_code == 200, stepped.text


def _save_person(world, name: str) -> None:
    """A person the account holder named, through the naming assertion the product writes."""
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    writer = AssertionWriter(connection, world["workspace"])
    entity_id = identity.entities.create(entity_class="person")
    rename_entity(
        identity, writer, entity_id=entity_id, display_name=name, actor=world["session"].actor
    )
    connection.commit()


def _society(world, client) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scope, _, society = routes(world)
    snapshot = client.get(society, headers=OWNER, params=scope).json()
    events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    return snapshot, events


def _ask(
    client,
    world,
    question: str,
    *,
    plan=None,
    inhabitant=None,
    version=None,
    scope=None,
    headers=OWNER,
    supplied=None,
):
    body: dict[str, Any] = {
        "question": question,
        "society_context": {
            "version_id": str(version or world["binding"].version_id),
            "inhabitant_id": None if inhabitant is None else str(inhabitant),
        },
    }
    if plan is not None:
        body["plan"] = {"intent": "society", "society": {"scope": plan[0], "aspect": plan[1]}}
    if supplied is not None:
        body["plan"] = supplied
    return client.post(
        "/selection/ask", headers=headers, params=scope or routes(world)[0], json=body
    )


def _names(snapshot) -> list[str]:
    return [person["display_name"] for person in snapshot["state"]["inhabitants"]]


def _parts(names: list[str]) -> set[str]:
    return {part for name in names for part in name.split() if len(part) >= 3}


def test_a_selected_person_s_why_is_answered_from_the_society_with_simulation_citations(world):
    with world["open_app"]() as client:
        snapshot, events = _society(world, client)
        recorded = {event["event_id"] for event in events}
        person = next(
            p
            for p in snapshot["state"]["inhabitants"]
            if set(p["explanation"]["event_ids"]) & recorded
        )
        response = _ask(
            client, world, "why are they there?", plan=("selected", "why"), inhabitant=person["id"]
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is None and body["execution"]["calls"] == []
    # The inspector's words: no model was asked, so nothing a model wrote was discarded.
    assert body["deterministic"] is False
    assert body["citations"] == {}
    assert body["inhabitants"]["[inhabitant A]"] == {
        "version_id": str(world["binding"].version_id),
        "inhabitant_id": person["id"],
    }
    simulation = body["simulation"]
    assert simulation and all(
        view["truth_class"] == "simulation" and view["personal_visit_evidence"] is False
        for view in simulation.values()
    )
    cited = {token for clause in body["answer"]["clauses"] for token in clause["citations"]}
    assert cited <= set(simulation)
    cited_events = {simulation[token]["event_id"] for token in cited} - {None}
    # The event that explains where they are, and one the society's own event route serves.
    assert cited_events == set(person["explanation"]["event_ids"])
    assert cited_events <= recorded
    text = " ".join(clause["text"] for clause in body["answer"]["clauses"])
    assert "[inhabitant A]" in text and text.startswith("[inhabitant A]: ")
    assert not {part for part in _parts(_names(snapshot)) if part in text}
    assert "none of it is a memory or a real visit" in text


def test_a_society_this_world_does_not_hold_is_answered_as_none_alike_in_every_case(world):
    """Not there and not yours answer the same bytes: an unknown inhabitant, an unknown version,
    this workspace's society asked about from its other world, and from another workspace."""
    connection = world["connection"]
    other = registered_world(
        connection, world["workspace"], f"world:authored:{uuid.uuid4()}", kind=AUTHORED_STARTER
    )
    stranger_world = registered_world(
        connection, world["stranger"], f"world:authored:{uuid.uuid4()}", kind=AUTHORED_STARTER
    )
    connection.commit()
    with world["open_app"]() as client:
        snapshot, _ = _society(world, client)
        person = snapshot["state"]["inhabitants"][0]["id"]
        plan = ("selected", "who")
        answers = [
            _ask(client, world, "who is that?", plan=plan, inhabitant=uuid.uuid4()),
            _ask(client, world, "who is that?", plan=plan, version=uuid.uuid4()),
            _ask(
                client,
                world,
                "who is that?",
                plan=plan,
                inhabitant=person,
                scope={"world_id": other},
            ),
            _ask(
                client,
                world,
                "who is that?",
                plan=plan,
                inhabitant=person,
                scope={"world_id": stranger_world},
                headers=STRANGER,
            ),
        ]
        # A positive control: the same person in the right world is answered.
        known = _ask(client, world, "who is that?", plan=plan, inhabitant=person)
    assert known.status_code == 200 and known.json()["abstained"] is None, known.text
    assert [answer.status_code for answer in answers] == [200, 200, 200, 200]
    assert len({answer.content for answer in answers}) == 1, [a.content for a in answers]
    body = answers[0].json()
    assert body["abstained"] == "UNANSWERABLE_NOT_CAPTURED"
    assert body["execution"]["rejections"] == ["society_refused: no_society_here"]


def test_a_stale_society_context_does_not_stop_a_photograph_question(world):
    """A context the world does not hold is answered as a question asked with none, not a 404."""
    with world["open_app"](_Scripted()) as client:
        response = _ask(
            client,
            world,
            "which photographs?",
            version=uuid.uuid4(),
            supplied={"intent": "captures"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["simulation"] == {}


def test_an_unreadable_society_is_left_out_and_the_answer_says_so(world):
    def withdrawn(connection, session, document):
        raise UnavailableSocietyInput("the input's rights were withdrawn")

    with world["open_app"](_Scripted()) as client:
        client.app.state.society_input_authorizer = withdrawn
        photo = _ask(client, world, "which photographs?", supplied={"intent": "captures"}).json()
        about = _ask(client, world, "who is that?", plan=("world", "who")).json()
    assert photo["answer"]["clauses"][0]["text"].startswith(
        "The people in this world could not be read right now"
    )
    assert about["execution"]["rejections"] == ["society_refused: society_unavailable"]


def test_a_typed_question_with_a_colliding_name_is_refused_before_it_is_planned(world):
    """Decided on the words: planned first, it would search the saved person's photographs."""
    transport = _Scripted()
    with world["open_app"](transport) as client:
        snapshot, _ = _society(world, client)
        person = snapshot["state"]["inhabitants"][0]
        first = person["display_name"].split()[0]
        _save_person(world, f"{first} {SAVED_SURNAME}")
        body = _ask(client, world, f"Why is {first} there?", inhabitant=person["id"]).json()
    assert transport.requests == [], "the question was sent to a model before it was refused"
    assert body["abstained"] == "UNANSWERABLE_AMBIGUOUS"
    assert body["names"] == {} and body["simulation"] == {}
    assert "use their full name or clear the selection" in body["answer"]["clauses"][0]["text"]


def test_the_plan_route_refuses_a_society_context_by_name(world):
    with world["open_app"]() as client:
        response = client.post(
            "/selection/plan",
            headers=OWNER,
            params=routes(world)[0],
            json={
                "question": "who is that?",
                "society_context": {"version_id": str(world["binding"].version_id)},
            },
        )
    assert response.status_code == 422, response.text
    assert "society_context_not_planned" in response.text


def test_why_cites_the_explaining_event_long_after_it_left_the_latest_events(world, monkeypatch):
    """The explaining event is read by its id, not looked for among the latest events. The window
    is narrowed to the latest two events here, because in this small world everybody is recorded
    most minutes; what is held is the read by id through the database, as the runtime role."""
    monkeypatch.setattr(society_question, "EVENT_LINES", WINDOW)
    with world["open_app"]() as client:
        scope, _, society = routes(world)
        snapshot = client.get(society, headers=OWNER, params=scope).json()
        latest = client.get(
            society + "/events", headers=OWNER, params={**scope, "limit": WINDOW}
        ).json()
        shown = {event["event_id"] for event in latest["events"]}
        person = next(
            p
            for p in snapshot["state"]["inhabitants"]
            if p["explanation"]["event_ids"] and not set(p["explanation"]["event_ids"]) & shown
        )
        body = _ask(
            client, world, "why are they there?", plan=("selected", "why"), inhabitant=person["id"]
        ).json()
    cited = {token for clause in body["answer"]["clauses"] for token in clause["citations"]}
    events = {body["simulation"][token]["event_id"] for token in cited} - {None}
    assert events == set(person["explanation"]["event_ids"])


def test_a_name_that_is_both_a_saved_person_s_and_an_inhabitant_s_is_refused_by_name(world):
    with world["open_app"]() as client:
        snapshot, _ = _society(world, client)
        person = snapshot["state"]["inhabitants"][0]
        first = person["display_name"].split()[0]
        question = f"why is {first} there?"
        plan = ("selected", "why")
        # Positive control: with nobody saved under the name, the same question is answered.
        answered = _ask(client, world, question, plan=plan, inhabitant=person["id"]).json()
        _save_person(world, f"{first} {SAVED_SURNAME}")
        refused = _ask(client, world, question, plan=plan, inhabitant=person["id"]).json()
    assert answered["abstained"] is None
    assert refused["abstained"] == "UNANSWERABLE_AMBIGUOUS"
    assert refused["simulation"] == {} and refused["inhabitants"] == {}
    assert refused["names"] == {}
    text = refused["answer"]["clauses"][0]["text"]
    assert "use their full name or clear the selection" in text
    assert first not in text and SAVED_SURNAME not in text


def test_talk_content_is_refused_by_name(world):
    with world["open_app"]() as client:
        snapshot, _ = _society(world, client)
        person = snapshot["state"]["inhabitants"][0]["id"]
        body = _ask(
            client,
            world,
            "what did they talk about?",
            plan=("selected", "talk_content"),
            inhabitant=person,
        ).json()
    assert body["abstained"] == "UNANSWERABLE_NOT_IN_MODALITY"
    assert "never what they said" in body["answer"]["clauses"][0]["text"]


def _sent(transport: FakeTransport) -> list[str]:
    return [json.dumps(request["payload"]) for request in transport.requests]


def test_what_happened_is_composed_from_event_lines_alone_through_the_policy(world):
    _save_person(world, f"Maria {SAVED_SURNAME}")
    transport = _Scripted()
    with world["open_app"](transport) as client:
        snapshot, _ = _society(world, client)
        response = _ask(
            client, world, f"What happened in the square while Maria {SAVED_SURNAME} was away?"
        )
    assert response.status_code == 200, response.text
    body = response.json()
    planner, composer = _sent(transport)
    # Positive controls: the planner was told people are in view, and the composer got lines.
    assert "simulated people are in view" in planner
    assert "Simulated minute" in composer and "[inhabitant A]" in composer
    for sent in (planner, composer):
        assert not {part for part in _parts(_names(snapshot)) if part in sent}
        assert SAVED_SURNAME not in sent and "Maria" not in sent
    assert "(simulated):" not in composer and "position" not in composer
    assert "seed" not in composer and snapshot["state_sha256"] not in composer
    clauses = body["answer"]["clauses"]
    assert body["deterministic"] is False
    assert "not times of day" in clauses[0]["text"]
    assert clauses[1]["text"] == "Here is what the simulation recorded."
    # The chosen line, in the words it was sent in, cited to it.
    assert clauses[2]["text"] == transport.chosen[0] and clauses[2]["type"] == "simulation"
    assert body["simulation"][clauses[2]["citations"][0]]["line"] == transport.chosen[0]
    assert "[inhabitant A]" in body["inhabitants"]


def test_a_choice_of_a_line_not_in_the_list_is_asked_again_then_fixed_words_given(world):
    transport = _Scripted(unknown=True)
    with world["open_app"](transport) as client:
        response = _ask(client, world, "What happened in the square?")
    body = response.json()
    assert response.status_code == 200, response.text
    # The plan, one choice and one more, both refused, then the fixed words.
    assert len(transport.requests) == 3
    assert body["deterministic"] is True
    assert body["execution"]["rejections"] == ["ZZZZZZZZZZ is not a token in the list"]
    assert all(
        clause["type"] == "meta" or clause["citations"] for clause in body["answer"]["clauses"]
    )


def test_a_society_plan_is_never_searched(world):
    with world["open_app"]() as client:
        response = client.post(
            "/selection/packet",
            headers=OWNER,
            params=routes(world)[0],
            json={"intent": "society", "society": {"scope": "world", "aspect": "who"}},
        )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "malformed_plan"
    assert "never searched" in response.text


# -- round 3 --------------------------------------------------------------------------------------


def test_a_photograph_question_about_a_saved_person_is_planned_with_people_on_screen(world):
    """A saved "Emi Tanaka" is that person, however an inhabitant called Emi is named; "Emi" alone,
    beside her, is refused before it is planned."""
    transport = _Scripted(plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="beach"))
    with world["open_app"](transport) as client:
        snapshot, _ = _society(world, client)
        emi = next(
            p for p in snapshot["state"]["inhabitants"] if p["display_name"].startswith("Emi")
        )
        _save_person(world, "Emi Tanaka")
        photo = _ask(client, world, "Show me photos of Emi Tanaka at the beach").json()
        planned = len(transport.requests)
        alone = _ask(client, world, "Why is Emi there?", inhabitant=emi["id"]).json()
    assert planned >= 1, "the photograph question was never planned"
    assert photo["execution"]["rejections"] != ["society_refused: synthetic_name_collision"]
    assert photo["plan"]["intent"] == "captures"
    assert "[person A]" in json.dumps(transport.requests[0]["payload"])
    assert len(transport.requests) == planned, "the colliding question reached a model"
    assert alone["execution"]["rejections"] == ["society_refused: synthetic_name_collision"]


def test_no_inhabitant_name_reaches_the_planner_s_request(world):
    """The v2 society of eight: a full name the question uses is sent as one placeholder."""
    transport = _Scripted(
        plan=SelectionPlan(
            intent=Intent.SOCIETY,
            society={"scope": SocietyScope.SELECTED, "aspect": SocietyAspect.WHY},
        )
    )
    with world["open_app"](transport) as client:
        snapshot, _ = _society(world, client)
        people = snapshot["state"]["inhabitants"]
        assert len(people) == 8
        first, last = people[0]["display_name"].split()[:2]
        body = _ask(
            client, world, f"Why is {first} {last} there?", inhabitant=people[0]["id"]
        ).json()
    assert body["abstained"] is None, body
    (planner,) = [json.dumps(r["payload"]) for r in transport.requests]
    assert "Why is [inhabitant A] there?" in planner
    assert not {part for part in _parts(_names(snapshot)) if part in planner}


def test_an_explaining_event_under_a_withdrawn_input_is_left_out_and_the_state_answers(
    world, monkeypatch
):
    """One withdrawal leaves out the events recorded under it, and only them."""
    monkeypatch.setattr(society_question, "EVENT_LINES", WINDOW)
    with world["open_app"]() as client:
        scope, _, society = routes(world)
        # An object placed after people are here gives the society a second input.
        place(client, world, "object:plate-late", 0, 12_000)
        for _ in range(2):
            snapshot = client.get(society, headers=OWNER, params=scope).json()
            stepped = client.post(
                society + "/steps",
                headers=OWNER,
                params=scope,
                json={
                    "base_tick": snapshot["current_tick"],
                    "base_state_sha256": snapshot["state_sha256"],
                },
            )
            assert stepped.status_code == 200, stepped.text
        snapshot = client.get(society, headers=OWNER, params=scope).json()
        assert snapshot["input_seq"] >= 2, "no later input was recorded"
        recorded = {
            event["event_id"]: event["document"]["input_seq"]
            for event in client.get(society + "/events", headers=OWNER, params=scope).json()[
                "events"
            ]
        }
        person = next(
            p
            for p in snapshot["state"]["inhabitants"]
            if p["explanation"]["event_ids"]
            and all(recorded.get(e) == 1 for e in p["explanation"]["event_ids"])
        )
        granted = client.app.state.society_input_authorizer

        def withdrawn_first(connection, session, document):
            if document["input_seq"] == 1:
                raise UnavailableSocietyInput("the first input's rights were withdrawn")
            return granted(connection, session, document)

        client.app.state.society_input_authorizer = withdrawn_first
        body = _ask(
            client, world, "why are they there?", plan=("selected", "why"), inhabitant=person["id"]
        ).json()
    assert body["abstained"] is None, body
    assert "could not be read" not in json.dumps(body["answer"])
    cited = {token for clause in body["answer"]["clauses"] for token in clause["citations"]}
    assert cited and {body["simulation"][t]["event_id"] for t in cited} == {None}


@pytest.mark.parametrize(
    "failure",
    [
        TransportError(
            "the composer did not answer in time", timed_out=True, reached_provider=None
        ),
        TransportError("HTTP 503 from the provider", retryable=True, reached_provider=True),
    ],
    ids=["timed out", "failed"],
)
def test_a_composer_that_gives_no_answer_leaves_the_fixed_words_and_a_200(world, failure):
    transport = _Scripted(composer_fails=failure)
    with world["open_app"](transport) as client:
        response = _ask(client, world, "What happened in the square?")
    assert response.status_code == 200, response.text
    body = response.json()
    texts = [clause["text"] for clause in body["answer"]["clauses"]]
    cause = "did not answer in time." if failure.timed_out else "did not answer."
    assert texts[1].startswith(f"The model that chooses the lines for this answer {cause}")
    assert body["deterministic"] is False
    composer = [call for call in body["execution"]["calls"] if call["role"] == "reasoning_cheap"]
    assert [call["outcome"] for call in composer] == [
        "timed_out" if failure.timed_out else "failed"
    ]


def _later_input(world, client) -> dict[str, Any]:
    """An object placed after people are here, and two minutes under the input it records."""
    scope, _, society = routes(world)
    place(client, world, "object:plate-late", 0, 12_000)
    for _ in range(2):
        snapshot = client.get(society, headers=OWNER, params=scope).json()
        stepped = client.post(
            society + "/steps",
            headers=OWNER,
            params=scope,
            json={
                "base_tick": snapshot["current_tick"],
                "base_state_sha256": snapshot["state_sha256"],
            },
        )
        assert stepped.status_code == 200, stepped.text
    snapshot = client.get(society, headers=OWNER, params=scope).json()
    assert snapshot["input_seq"] >= 2, "no later input was recorded"
    return snapshot


def test_a_withdrawn_input_behind_the_latest_events_leaves_out_only_its_events(world):
    """With the full window, the latest events include some recorded under the first input; its
    withdrawal leaves them out and nothing else, so the society still answers."""
    with world["open_app"](_Scripted()) as client:
        scope, _, society = routes(world)
        snapshot = _later_input(world, client)
        latest = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
        seqs = {event["document"]["input_seq"] for event in latest[:24]}
        assert {1, snapshot["input_seq"]} <= seqs, seqs  # a positive control on the window
        granted = client.app.state.society_input_authorizer

        def withdrawn_first(connection, session, document):
            if document["input_seq"] == 1:
                raise UnavailableSocietyInput("the first input's rights were withdrawn")
            return granted(connection, session, document)

        client.app.state.society_input_authorizer = withdrawn_first
        happened = _ask(client, world, "what happened?", plan=("world", "recent")).json()
        photo = _ask(client, world, "which photographs?", supplied={"intent": "captures"}).json()
    assert happened["abstained"] is None, happened
    under = {event["event_id"]: event["document"]["input_seq"] for event in latest}
    cited = [view["event_id"] for view in happened["simulation"].values() if view["event_id"]]
    assert cited, "nothing recorded under the later input was cited"
    assert all(under[event_id] != 1 for event_id in cited)
    assert "could not be read" not in json.dumps(photo["answer"])


def test_each_input_is_authorized_once_per_question(world):
    """Every authorization reads and hashes the reviewed assets its input names, so a question
    asks it once per input: the scene, its latest events and the explaining events share it."""
    calls: list[int] = []
    with world["open_app"](_Scripted()) as client:
        snapshot, _ = _society(world, client)
        granted = client.app.state.society_input_authorizer

        def counted(connection, session, document):
            calls.append(document["input_seq"])
            return granted(connection, session, document)

        client.app.state.society_input_authorizer = counted
        person = snapshot["state"]["inhabitants"][0]["id"]
        for kwargs in (
            {"supplied": {"intent": "captures"}},
            {"plan": ("selected", "why"), "inhabitant": person},
            {},
        ):
            calls.clear()
            response = _ask(client, world, "what happened in the square?", **kwargs)
            assert response.status_code == 200, response.text
            assert sorted(calls) == sorted(set(calls)) and calls, (kwargs, calls)


def test_a_shared_name_plans_a_photo_question_with_a_note_unless_the_one_selected_has_it(world):
    transport = _Scripted(plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="beach"))
    with world["open_app"](transport) as client:
        snapshot, _ = _society(world, client)
        emi = next(
            p for p in snapshot["state"]["inhabitants"] if p["display_name"].startswith("Emi")
        )
        _save_person(world, "Emi Tanaka")
        answers = {}
        for question in ("Show me photos of Emi", "Why is Emi there?"):
            before = len(transport.requests)
            unselected = _ask(client, world, question).json()
            planned = len(transport.requests) > before
            before = len(transport.requests)
            selected = _ask(client, world, question, inhabitant=emi["id"]).json()
            answers[question] = (unselected, planned, selected, len(transport.requests) > before)
    for question, (unselected, planned, selected, sent) in answers.items():
        assert planned, f"{question}: not planned without a selection"
        assert unselected["answer"]["clauses"][0]["text"].startswith(
            "Someone in this world shares a name in your question"
        ), question
        assert selected["execution"]["rejections"] == [
            "society_refused: synthetic_name_collision"
        ], question
        assert not sent, f"{question}: sent to a model with the selected person's name"


def test_a_typed_inhabitant_label_is_refused_by_name_before_it_is_planned(world):
    transport = _Scripted()
    with world["open_app"](transport) as client:
        body = _ask(client, world, "Why is [inhabitant B] there?").json()
    assert transport.requests == []
    assert body["execution"]["rejections"] == ["society_refused: typed_inhabitant_label"]
    assert (
        "Use the person's name, or select them in the world" in body["answer"]["clauses"][0]["text"]
    )


def test_the_wait_bound_is_counted_from_the_question_s_start(world, monkeypatch):
    """The planner's time is part of the person's wait, so the composer is given the question's
    start, taken before the planner is asked, not a time of its own."""
    seen: dict[str, float | None] = {}
    plan, answer = question_module.propose_plan, question_module.answer_about_society

    def planning(*args, **kwargs):
        seen["planner"] = time.monotonic()
        return plan(*args, **kwargs)

    def answering(*args, **kwargs):
        seen["started"] = kwargs.get("started")
        return answer(*args, **kwargs)

    monkeypatch.setattr(question_module, "propose_plan", planning)
    monkeypatch.setattr(question_module, "answer_about_society", answering)
    with world["open_app"](_Scripted()) as client:
        _society(world, client)
        before = time.monotonic()
        response = _ask(client, world, "What happened in the square?")
    assert response.status_code == 200, response.text
    # Positive control: the question was planned, and answered about the world's people.
    assert response.json()["plan"]["intent"] == "society" and "planner" in seen
    started = seen["started"]
    assert started is not None and before <= started <= seen["planner"]


def _save_name(world, name: str, entity_class: str) -> None:
    """A name the account holder saved for an entity of ``entity_class``."""
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    writer = AssertionWriter(connection, world["workspace"])
    entity_id = identity.entities.create(entity_class=entity_class)
    rename_entity(
        identity, writer, entity_id=entity_id, display_name=name, actor=world["session"].actor
    )
    connection.commit()


def test_the_shared_name_note_is_never_said_of_an_answer_about_the_world_s_people(world):
    """An answer about the world's people is not about anybody saved, so "this answer is about the
    person you saved" would be false there."""
    photo = SelectionPlan(intent=Intent.CAPTURES, semantic_query="beach")
    with world["open_app"](_Scripted()) as client:
        _society(world, client)
        _save_person(world, "Emi Tanaka")
        about_people = _ask(client, world, "What happened with Emi in the square?").json()
    with world["open_app"](_Scripted(plan=photo)) as client:
        control = _ask(client, world, "Show me photos of Emi").json()
    shared = "Someone in this world shares a name in your question"
    assert about_people["plan"]["intent"] == "society"
    assert not any(c["text"].startswith(shared) for c in about_people["answer"]["clauses"])
    # Positive control: the same name in a photograph question carries the note.
    assert control["answer"]["clauses"][0]["text"].startswith(shared)


def test_a_saved_place_that_shares_an_inhabitant_s_name_is_noted_as_the_name_you_saved(world):
    photo = SelectionPlan(intent=Intent.CAPTURES, semantic_query="beach")
    with world["open_app"](_Scripted(plan=photo)) as client:
        snapshot, _ = _society(world, client)
        first = next(
            p["display_name"].split()[0]
            for p in snapshot["state"]["inhabitants"]
            if p["display_name"].startswith("Bela")
        )
        _save_name(world, first, "place")
        body = _ask(client, world, f"Show me photos of {first}").json()
    note = body["answer"]["clauses"][0]["text"]
    assert note.startswith("Someone in this world shares a name in your question")
    assert "reads it as the name you saved" in note and "person you saved" not in note
