"""The Companion's answers about a world's simulated people, over a real run of the small square.

No database: the society is the small square advanced minute by minute exactly as a step advances
it (``living_square_support``), and its state and events are handed over in the shapes
``SocietyRepository.snapshot`` and ``events`` return. The route, the database's authorization and
the hosted boundary are ``tests/test_companion_asks_inhabitants_api.py``.
"""

from __future__ import annotations

import copy
import json
import re
import uuid

import pytest
from exulanica.epistemics.saved_names import SavedName
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TransportError
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import (
    MAX_CLAUSES,
    Abstention,
    Answer,
    AnswerClause,
    ClauseType,
)
from exulanica.selection.calls import CallLog
from exulanica.selection.inhabitant_words import inhabitant_words, inhabitant_words_catalog
from exulanica.selection.plan import SocietyAspect, SocietyScope, SocietySelector
from exulanica.selection.society_question import (
    ANSWER_WAIT_BUDGET_SECONDS,
    INHABITANT_PLACEHOLDER,
    MAX_CHOSEN_LINES,
    Framing,
    SocietyLineChoice,
    SocietyRefusal,
    UnknownSocietyContext,
    answer_about_society,
    build_scene,
    render_society_packet,
)
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
)

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from living_square_support import DEVELOPMENT_SEEDS, SOCIETY, compose, square_objects
from model_fakes import FakeTransport, RecordingPolicy, chat_body

#: Minutes the square runs before a question: enough that people have chosen, walked, stayed and
#: talked, so every aspect has something recorded to answer from.
MINUTES = 40
VERSION = uuid.uuid5(SOCIETY, "version")


def _run() -> tuple[dict, list[dict], list[dict]]:
    document = compose(square_objects())
    seed = DEVELOPMENT_SEEDS[0]
    state = initial_purposeful_society(
        SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    recorded = []
    for _ in range(MINUTES):
        state, events = advance_purposeful_society(state, seed, [document])
        recorded.extend(events)
    events = [
        {
            "event_id": str(event.event_id),
            "tick": event.tick,
            "event_kind": event.kind,
            "subject_id": str(event.subject_id),
            "document": event.document,
        }
        for event in sorted(recorded, key=lambda e: (-e.tick, e.document["order"]))
    ]
    return state, document["targets"], events


STATE, TARGETS, EVENTS = _run()
SNAPSHOT = {
    "society_id": SOCIETY,
    "version_id": VERSION,
    "profile": PURPOSEFUL_PROFILE,
    "current_tick": STATE["tick"],
    "state": STATE,
}
NAMES = [person["display_name"] for person in STATE["inhabitants"]]


def _scene(question: str = "why are they there?", *, selected=None, saved=(), events=None):
    shown = EVENTS if events is None else events
    return build_scene(
        SNAPSHOT,
        targets=TARGETS,
        events=shown,
        # As read_scene reads them: every explaining event by its id, however old.
        explaining=EVENTS,
        selected=selected,
        question=question,
        saved=saved,
    )


def _explained() -> dict:
    """Somebody whose state names the event that explains it, in the latest events."""
    latest = {event["event_id"] for event in EVENTS[:24]}
    return next(
        person
        for person in STATE["inhabitants"]
        if set(person["explanation"]["event_ids"]) & latest
    )


def _answer(scene, scope, aspect, client=None):
    return answer_about_society(
        scene,
        SocietySelector(scope=scope, aspect=aspect),
        client=client,
        saved=(),
        log=CallLog(),
        max_tokens=1000,
        attempts=2,
    )


def _texts(answer: Answer) -> str:
    return " ".join(clause.text for clause in answer.clauses)


def test_why_a_selected_person_is_there_is_the_inspector_s_words_cited_to_the_explaining_event():
    person = _explained()
    scene = _scene(selected=uuid.UUID(person["id"]))
    said = _answer(scene, SocietyScope.SELECTED, SocietyAspect.WHY)

    # Nothing a model wrote was discarded: no model was asked.
    assert said.abstention is None and not said.deterministic
    packet = said.packet
    label = dict((str(i), label) for label, i in packet.inhabitants)[person["id"]]
    assert label == "[inhabitant A]"
    # The same words the inspector draws, with the person and places as placeholders.
    spots = {target: label for label, target in packet.spots}
    words = inhabitant_words(
        person, spots.get, lambda other: dict((str(i), lb) for lb, i in packet.inhabitants)[other]
    )
    doing, why = said.answer.clauses[0], said.answer.clauses[1]
    assert doing.text == f"{label}: {words.doing}"
    assert why.text == words.why
    cited = [packet.resolve(token) for token in why.citations]
    assert {str(item.event_id) for item in cited if item.event_id} == set(
        person["explanation"]["event_ids"]
    )
    assert all(item.truth_class == "simulation" for item in packet.items)
    assert not any(item.personal_visit_evidence for item in packet.items)
    # It closes saying what these people are.
    assert "none of it is a memory or a real visit" in said.answer.clauses[-1].text


@pytest.mark.parametrize("aspect", [SocietyAspect.WHO, SocietyAspect.DOING, SocietyAspect.RECENT])
def test_no_answer_about_a_person_names_anybody(aspect):
    person = _explained()
    said = _answer(_scene(selected=uuid.UUID(person["id"])), SocietyScope.SELECTED, aspect)
    text = _texts(said.answer)
    assert INHABITANT_PLACEHOLDER.search(text)
    for name in NAMES:
        for part in name.split():
            if len(part) >= 3:
                assert part not in text, (part, text)


def test_what_happened_is_fixed_words_without_a_model_and_names_the_minutes_it_covers():
    scene = _scene("what happened in the square this morning?")
    said = _answer(scene, SocietyScope.WORLD, SocietyAspect.RECENT)
    first = said.answer.clauses[0]
    assert first.type is ClauseType.META and "not times of day" in first.text
    assert all(said.packet.value(key) for key in first.value_refs)
    lines = said.answer.clauses[1:-1]
    assert lines and all(len(clause.citations) == 1 for clause in lines)
    rendered = render_society_packet(said.packet)
    # What a composer would be sent: rebuilt lines, never a stored summary, position or seed.
    assert "(simulated):" not in rendered and "position" not in rendered
    assert "seed" not in rendered and "sha256" not in rendered
    for name in NAMES:
        assert name not in rendered


def test_a_question_naming_one_person_is_about_them_and_their_name_is_not_sent():
    person = STATE["inhabitants"][3]
    scene = _scene(f"Why is {person['display_name']} there?")
    assert scene.question == "Why is [inhabitant A] there?"
    said = _answer(scene, SocietyScope.SELECTED, SocietyAspect.WHY)
    assert dict(said.packet.inhabitants)["[inhabitant A]"] == uuid.UUID(person["id"])


def test_a_part_several_but_not_all_share_names_nobody_unless_the_selected_one_has_it():
    # Two people called Ari, the rest not: "Ari" is then no one person's name.
    state = copy.deepcopy(STATE)
    first = state["inhabitants"][0]["display_name"].split()[0]
    state["inhabitants"][1]["display_name"] = f"{first} Bell 2"
    snapshot = {**SNAPSHOT, "state": state}

    def scene(selected=None):
        return build_scene(
            snapshot,
            targets=TARGETS,
            events=EVENTS,
            explaining=EVENTS,
            selected=selected,
            question=f"Why is {first} there?",
            saved=(),
        )

    unselected = scene()
    # No one person's name, so it stays the person's own word, and is refused below.
    assert unselected.question == f"Why is {first} there?"
    said = _answer(unselected, SocietyScope.SELECTED, SocietyAspect.WHY)
    assert said.rejections == (f"society_refused: {SocietyRefusal.SELECT_A_PERSON}",)
    # With one of the two selected, the name is theirs.
    chosen = scene(uuid.UUID(state["inhabitants"][1]["id"]))
    assert _answer(chosen, SocietyScope.SELECTED, SocietyAspect.WHY).abstention is None


def test_a_name_that_is_part_of_a_saved_person_s_and_an_inhabitant_s_is_refused_by_name():
    first = NAMES[0].split()[0]
    saved = (SavedName(uuid.uuid4(), "person", f"{first} Cohen"),)
    person = STATE["inhabitants"][0]
    scene = _scene(f"Why is {first} there?", selected=uuid.UUID(person["id"]), saved=saved)
    said = _answer(scene, SocietyScope.SELECTED, SocietyAspect.WHY)
    assert said.abstention is Abstention.AMBIGUOUS
    assert said.rejections == (f"society_refused: {SocietyRefusal.SYNTHETIC_NAME_COLLISION}",)
    assert "use their full name or clear the selection" in _texts(said.answer)
    assert said.packet is None
    # Left as written, so the saved person's own photographs can still be asked about.
    assert first in scene.question

    # Positive control: the same question with nobody saved under that name is answered.
    plain = _scene(f"Why is {NAMES[0]} there?", selected=uuid.UUID(person["id"]))
    assert _answer(plain, SocietyScope.SELECTED, SocietyAspect.WHY).abstention is None


def test_a_saved_place_s_whole_name_is_not_a_collision_with_a_part():
    first = NAMES[0].split()[0]
    saved = (SavedName(uuid.uuid4(), "place", f"{first} Hall"),)
    scene = _scene(f"Why is {first} there?", saved=saved)
    assert not scene.collision


@pytest.mark.parametrize(
    ("aspect", "code", "reason"),
    [
        (
            SocietyAspect.TALK_CONTENT,
            SocietyRefusal.TALK_HAS_NO_CONTENT,
            Abstention.NOT_IN_MODALITY,
        ),
        (SocietyAspect.UNRECORDED, SocietyRefusal.NOT_SIMULATED, Abstention.NOT_CAPTURED),
    ],
)
def test_what_the_simulation_does_not_record_is_refused_by_name(aspect, code, reason):
    person = _explained()
    said = _answer(_scene(selected=uuid.UUID(person["id"])), SocietyScope.SELECTED, aspect)
    assert said.abstention is reason
    assert said.rejections == (f"society_refused: {code}",)


def test_a_selected_inhabitant_not_in_the_society_is_unknown():
    with pytest.raises(UnknownSocietyContext):
        _scene(selected=uuid.uuid4())


def _packet():
    return _answer(_scene("what happened?"), SocietyScope.WORLD, SocietyAspect.RECENT).packet


# -- round 2: names read after the saved ones, late explanations, talk, clause types -------------


def test_a_word_every_inhabitant_shares_names_nobody_and_is_left_as_written():
    shared = NAMES[0].split()[1]
    assert all(name.split()[1] == shared for name in NAMES)  # a positive control: "Ash"
    scene = _scene(f"Which photos show the {shared.lower()} cloud?")
    assert scene.question == f"Which photos show the {shared.lower()} cloud?"
    assert not scene.named and not scene.named_ambiguously and not scene.collision


def test_a_saved_place_s_words_are_left_as_written_whatever_an_inhabitant_is_called():
    juno = next(name for name in NAMES if name.startswith("Juno "))
    assert juno  # a positive control: an inhabitant is called Juno
    saved = (SavedName(uuid.uuid4(), "place", "Juno Beach"),)
    scene = _scene("Which photos were taken at Juno Beach?", saved=saved)
    assert scene.question == "Which photos were taken at Juno Beach?"
    assert not scene.named and not scene.collision


def test_the_selected_person_s_whole_name_names_them_although_everyone_shares_a_part():
    person = STATE["inhabitants"][0]
    first, shared = person["display_name"].split()[:2]
    scene = _scene(f"Why is {first} {shared} there?", selected=uuid.UUID(person["id"]))
    # The full name is one unit: nothing of it is left to send.
    assert scene.question == "Why is [inhabitant A] there?"
    said = _answer(scene, SocietyScope.SELECTED, SocietyAspect.WHY)
    assert said.abstention is None, said.rejections


def test_why_cites_the_explaining_event_however_long_ago_it_was_recorded():
    latest = EVENTS[:4]
    shown = {event["event_id"] for event in latest}
    person = next(
        person
        for person in STATE["inhabitants"]
        if person["explanation"]["event_ids"]
        and not set(person["explanation"]["event_ids"]) & shown
    )
    scene = _scene(selected=uuid.UUID(person["id"]), events=latest)
    said = _answer(scene, SocietyScope.SELECTED, SocietyAspect.WHY)
    cited = {
        str(item.event_id)
        for token in said.answer.clauses[1].citations
        if (item := said.packet.resolve(token)).event_id
    }
    assert cited == set(person["explanation"]["event_ids"])


def test_every_simulated_fact_is_a_simulation_clause_never_a_historical_one():
    person = _explained()
    for aspect in (SocietyAspect.WHO, SocietyAspect.DOING, SocietyAspect.WHY):
        said = _answer(_scene(selected=uuid.UUID(person["id"])), SocietyScope.SELECTED, aspect)
        types = {clause.type for clause in said.answer.clauses}
        assert ClauseType.HISTORICAL not in types
        assert ClauseType.SIMULATION in types


def test_the_fixed_words_state_the_minutes_of_the_lines_they_show():
    said = _answer(_scene("what happened?"), SocietyScope.WORLD, SocietyAspect.RECENT)
    shown = [said.packet.resolve(c.citations[0]) for c in said.answer.clauses[1:-1]]
    first, last = min(item.tick for item in shown), max(item.tick for item in shown)
    span = said.answer.clauses[0]
    assert {said.packet.value(key).text for key in span.value_refs} == {str(first), str(last)}
    # A positive control: the packet holds more minutes than the answer shows.
    assert min(item.tick for item in said.packet.items) < first


# -- round 3: one longest-first reading of saved and inhabitant names -----------------------------


def _with_second_ari():
    state = copy.deepcopy(STATE)
    state["inhabitants"][1]["display_name"] = "Ari Bell 2"
    return {**SNAPSHOT, "state": state}, state


@pytest.mark.parametrize("name", ["Ari Ash", "Ari Ash 1", "Ari Bell"])
def test_a_full_name_that_names_one_inhabitant_is_one_unit(name):
    snapshot, state = _with_second_ari()
    scene = build_scene(
        snapshot,
        targets=TARGETS,
        events=EVENTS,
        explaining=EVENTS,
        selected=None,
        question=f"Why is {name} there?",
        saved=(),
    )
    owner = next(p for p in state["inhabitants"] if p["display_name"].startswith(name))
    assert scene.question == "Why is [inhabitant A] there?"
    assert scene.named == (owner["id"],)


def test_a_society_of_one_names_its_one_person_by_every_form():
    person = copy.deepcopy(STATE["inhabitants"][0])
    snapshot = {**SNAPSHOT, "state": {**STATE, "inhabitants": [person]}}
    first, last = person["display_name"].split()[:2]
    for question in (f"Why is {first} there?", f"Why is {first} {last} there?"):
        scene = build_scene(
            snapshot,
            targets=TARGETS,
            events=EVENTS,
            explaining=EVENTS,
            selected=None,
            question=question,
            saved=(),
        )
        assert scene.question == "Why is [inhabitant A] there?", question


def test_a_saved_person_with_the_shared_surname_does_not_split_an_inhabitant_s_full_name():
    person = STATE["inhabitants"][0]
    first, last = person["display_name"].split()[:2]
    saved = (SavedName(uuid.uuid4(), "person", f"{last} Ketchum"),)
    scene = _scene(f"Why is {first} {last} there?", saved=saved)
    assert scene.question == "Why is [inhabitant A] there?"
    assert not scene.collision


def test_a_saved_person_s_full_name_is_theirs_and_the_first_name_alone_collides():
    emi = next(p for p in STATE["inhabitants"] if p["display_name"].startswith("Emi "))
    saved = (SavedName(uuid.uuid4(), "person", "Emi Tanaka"),)
    photo = _scene("Show me photos of Emi Tanaka at the beach", saved=saved)
    # The longer words win outright: no collision, and no note that someone shares the name.
    assert not photo.collision and not photo.shared_name and not photo.named
    assert photo.question == "Show me photos of Emi Tanaka at the beach"
    alone = _scene("Why is Emi there?", selected=uuid.UUID(emi["id"]), saved=saved)
    assert alone.collision


def test_a_note_is_its_own_clause_and_never_costs_the_answer_one():
    from exulanica.selection.answer import MAX_NOTES
    from exulanica.selection.question import AnsweredQuestion, _led_by_notes

    note = "The people in this world could not be read right now, so this answer leaves them out."
    full = Answer(
        clauses=[
            AnswerClause(text=f"Photograph {n}.", type=ClauseType.HISTORICAL, citations=["T"])
            for n in range(MAX_CLAUSES)
        ]
    )
    led = _led_by_notes(AnsweredQuestion(answer=full), [note, "A second note."])
    assert len(led.answer.clauses) == MAX_CLAUSES + MAX_NOTES
    assert [c.text for c in led.answer.clauses[:2]] == [note, "A second note."]
    assert all(c.type is ClauseType.META for c in led.answer.clauses[:2])
    assert [c.text for c in led.answer.clauses[2:]] == [c.text for c in full.clauses]
    # The answer the composer may write stays at its limit.
    from exulanica.selection.answer import ComposedAnswer

    with pytest.raises(ValueError):
        ComposedAnswer(clauses=[*full.clauses, full.clauses[0]])


@pytest.mark.parametrize(
    "failure",
    [
        TransportError("the composer timed out", timed_out=True, reached_provider=None),
        TransportError("HTTP 503 from the provider", retryable=True, reached_provider=True),
    ],
    ids=["timed out", "failed"],
)
def test_a_composer_that_gives_no_answer_leaves_the_fixed_words_after_one_attempt(failure):
    transport = FakeTransport([failure, failure])
    log = CallLog()
    client = (
        ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        )
        .with_policy(RecordingPolicy())
        .with_attempts(log.attempt)
    )
    said = answer_about_society(
        _scene("what happened in the square?"),
        SocietySelector(scope=SocietyScope.WORLD, aspect=SocietyAspect.RECENT),
        client=client,
        saved=(),
        log=log,
        max_tokens=1000,
        attempts=2,
    )
    # One attempt, not a repair after it: the person waits on one bound at most.
    assert len(transport.requests) == 1
    assert [call.outcome for call in log.calls] == ["timed_out" if failure.timed_out else "failed"]
    texts = [clause.text for clause in said.answer.clauses]
    cause = "did not answer in time." if failure.timed_out else "did not answer."
    assert texts[1] == (
        f"The model that chooses the lines for this answer {cause} "
        "Here are the latest recorded lines instead."
    )
    assert all(clause.citations for clause in said.answer.clauses[2:-1])
    # Nothing a model wrote was discarded, because it wrote nothing.
    assert not said.deterministic
    assert said.rejections == ("composer_unanswered: TransportError",)
    assert len(said.answer.clauses) <= MAX_CLAUSES


# -- round 4 --------------------------------------------------------------------------------------


@pytest.mark.parametrize("saved_as", ["Emi", "Emi Tanaka"])
@pytest.mark.parametrize("question", ["Show me photos of Emi", "Why is Emi there?"])
def test_a_shared_name_is_the_saved_person_s_unless_the_one_selected_has_it(saved_as, question):
    emi = next(p for p in STATE["inhabitants"] if p["display_name"].startswith("Emi "))
    saved = (SavedName(uuid.uuid4(), "person", saved_as),)
    unselected = _scene(question, saved=saved)
    assert unselected.shared_name and not unselected.collision
    assert unselected.question == question
    selected = _scene(question, saved=saved, selected=uuid.UUID(emi["id"]))
    assert selected.collision


def _society_of(count: int) -> dict:
    """A society of ``count`` people named as the legacy table names them: first names cycle
    every eight, surnames every sixty-four."""
    firsts = ("Ari", "Bela", "Cleo", "Dara", "Emi", "Faye", "Ivo", "Juno")
    lasts = ("Ash", "Bell", "Cove", "Dawn", "Elm", "Fox", "Grove", "Hart")
    template = STATE["inhabitants"][0]
    people = [
        {
            **copy.deepcopy(template),
            "id": str(uuid.uuid5(SOCIETY, f"person-{n}")),
            "display_name": f"{firsts[n % 8]} {lasts[(n // 8) % 8]} {n + 1}",
        }
        for n in range(count)
    ]
    return {**SNAPSHOT, "state": {**STATE, "inhabitants": people}}


@pytest.mark.parametrize("count", [9, 16])
def test_a_form_several_share_stays_the_person_s_word_and_one_person_s_name_is_substituted(count):
    snapshot = _society_of(count)
    people = snapshot["state"]["inhabitants"]

    def read(question, selected=None):
        return build_scene(
            snapshot,
            targets=TARGETS,
            events=EVENTS,
            explaining=EVENTS,
            selected=selected,
            question=question,
            saved=(),
        )

    cloud = read("Which photos show the ash cloud?")
    assert cloud.question == "Which photos show the ash cloud?"
    ari = read("Why is Ari there?")
    assert ari.question == "Why is Ari there?" and ari.named_ambiguously
    said = _answer(ari, SocietyScope.SELECTED, SocietyAspect.WHY)
    assert said.rejections == (f"society_refused: {SocietyRefusal.SELECT_A_PERSON}",)
    second_ari = next(p for p in people[8:] if p["display_name"].startswith("Ari "))
    chosen = read("Why is Ari there?", selected=uuid.UUID(second_ari["id"]))
    assert chosen.question == "Why is [inhabitant A] there?"
    bela = people[1]["display_name"]
    whole = read(f"Why is {bela} there?")
    assert whole.question == "Why is [inhabitant A] there?"


def test_a_typed_inhabitant_label_names_nobody_and_is_noted():
    for typed in ("Why is [inhabitant A] there?", "what did [Spot b] hold?"):
        assert _scene(typed).typed_label, typed
    assert not _scene("Why is Ari there?").typed_label


# -- the whole answer's wait bound -----------------------------------------------------------------


# -- round 5: the composer chooses lines and writes nothing ---------------------------------------


class _Choosing(FakeTransport):
    """A composer that answers each request with the next reply: a choice, a choice made from
    the request (a callable given its payload, since tokens are random per request), or an error."""

    def __init__(self, *replies) -> None:
        super().__init__()
        self.replies = list(replies)

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(payload)
        return HttpResponse(status_code=200, text=json.dumps(chat_body(reply.model_dump_json())))


def _tokens(payload) -> list[str]:
    """The tokens of the lines a request sent, in the list's order."""
    return re.findall(r"^\[([A-Z0-9]{10})\]", payload["messages"][1]["content"], re.MULTILINE)


def _choosing(*replies) -> tuple[ModelClient, _Choosing]:
    transport = _Choosing(*replies)
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
    ).with_policy(RecordingPolicy())
    return client, transport


def _happened(client, scene=None, **timing):
    return answer_about_society(
        scene or _scene("what happened in the square?"),
        SocietySelector(scope=SocietyScope.WORLD, aspect=SocietyAspect.RECENT),
        client=client,
        saved=(),
        log=CallLog(),
        max_tokens=1000,
        attempts=2,
        **timing,
    )


def test_a_composed_answer_is_the_chosen_lines_each_in_its_own_words_in_the_list_s_order():
    """Nothing the model writes reaches the answer, so it cannot say what no line says: talk
    moved onto somebody as speech, a reason moved between lines, a word no line has."""
    later, earlier = 5, 2
    client, transport = _choosing(
        lambda payload: SocietyLineChoice(
            lines=[_tokens(payload)[i] for i in (later, earlier, earlier)], framing=Framing.TALK
        )
    )
    said = _happened(client)
    assert len(transport.requests) == 1
    clauses = said.answer.clauses
    chosen = [said.packet.items[earlier], said.packet.items[later]]
    assert [clause.text for clause in clauses[2:-1]] == [item.line for item in chosen]
    assert [clause.citations for clause in clauses[2:-1]] == [[item.token] for item in chosen]
    assert all(clause.type is ClauseType.SIMULATION for clause in clauses[2:-1])
    assert clauses[0].text.startswith("The simulation counts minutes, not times of day.")
    assert "These lines are from its minute" in clauses[0].text
    assert clauses[1].text == (
        "The simulation records who talked with whom, and never what they said."
    )
    # Every sentence is a line's own words or code's: no text of the model's anywhere.
    lines = {item.line for item in said.packet.items}
    assert all(c.type is ClauseType.META or c.text in lines for c in clauses)
    assert not said.deterministic and not said.repaired


def test_two_tokens_written_into_one_entry_are_both_read():
    """Measured live: the composer wrote ``7S3NG9EFUH", "VFS2MRJ9DY`` as one entry."""
    client, transport = _choosing(
        lambda payload: SocietyLineChoice(lines=['{}", "{}'.format(*_tokens(payload)[1:3])])
    )
    said = _happened(client)
    assert len(transport.requests) == 1
    assert [clause.text for clause in said.answer.clauses[1:-1]] == [
        item.line for item in said.packet.items[1:3]
    ]
    assert not said.repaired and not said.deterministic


@pytest.mark.parametrize("count", [9, 10, 12, 13])
def test_a_choice_of_more_lines_than_an_answer_holds_is_refused_by_name(count):
    """The schema caps entries, not the tokens written in them: twelve lines and the three code
    clauses would be more than an answer may hold."""

    def over(payload):
        tokens = _tokens(payload)
        assert len(tokens) >= count
        # Written into two entries, so the schema's cap on entries admits it.
        half = count // 2
        return SocietyLineChoice(
            lines=[", ".join(tokens[:half]), ", ".join(tokens[half:count])],
            framing=Framing.RECORDED,
        )

    client, transport = _choosing(over, over)
    said = _happened(client)
    assert len(said.answer.clauses) <= MAX_CLAUSES
    if count <= MAX_CHOSEN_LINES:
        # Positive control: as many lines as an answer holds are shown, filling it.
        assert len(transport.requests) == 1 and not said.deterministic
        assert len(said.answer.clauses) == count + 3 == MAX_CLAUSES
    else:
        assert len(transport.requests) == 2
        retry = transport.requests[1]["payload"]["messages"][-1]["content"]
        assert f"the choice names {count} lines; choose at most {MAX_CHOSEN_LINES}" in retry
        assert said.deterministic
        assert said.rejections == (
            f"the choice names {count} lines; choose at most {MAX_CHOSEN_LINES}",
        )


def test_an_entry_with_no_token_is_refused_without_its_words():
    """The reasons are returned with the answer, so they carry no text the model wrote."""
    words = "the people who sat on the bench"
    client, _ = _choosing(SocietyLineChoice(lines=[words]), SocietyLineChoice(lines=[words]))
    said = _happened(client)
    assert said.rejections == ("1 of the entries hold no token from the list",)
    assert said.deterministic


def test_a_token_not_in_the_list_is_asked_for_once_more_and_then_the_fixed_words_given():
    client, transport = _choosing(
        SocietyLineChoice(lines=["ZZZZZZZZZZ"]), SocietyLineChoice(lines=["YYYYYYYYYY"])
    )
    said = _happened(client)
    assert len(transport.requests) == 2
    retry = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert "ZZZZZZZZZZ is not a token in the list" in retry
    assert said.deterministic and not said.repaired
    assert said.rejections == ("YYYYYYYYYY is not a token in the list",)
    assert not any("did not answer" in clause.text for clause in said.answer.clauses)


def test_a_repaired_choice_is_shown_and_says_it_was_repaired():
    client, transport = _choosing(
        SocietyLineChoice(lines=["ZZZZZZZZZZ"]),
        lambda payload: SocietyLineChoice(lines=_tokens(payload)[:1]),
    )
    said = _happened(client)
    assert len(transport.requests) == 2
    assert said.repaired and not said.deterministic
    assert said.answer.clauses[1].text == said.packet.items[0].line


@pytest.mark.parametrize("late", [True, False], ids=["late", "early"])
def test_a_refused_choice_is_asked_again_only_while_a_whole_attempt_fits_the_wait_bound(late):
    """Measured live: a refused reply 17 and 22 seconds in, then a repair that timed out, made the
    person wait 78 and 83 seconds for the fixed words they could have had at once."""
    client, transport = _choosing(
        SocietyLineChoice(lines=["ZZZZZZZZZZ"]), SocietyLineChoice(lines=["ZZZZZZZZZZ"])
    )
    bound = client.manifest[Role.REASONING_CHEAP].timeout_seconds
    # The first reply is back, and one second less, or one more, than a whole attempt is left.
    now = ANSWER_WAIT_BUDGET_SECONDS - bound + (1.0 if late else -1.0)
    said = _happened(client, started=0.0, clock=lambda: now)
    # A choice the model made was refused either way, so the answer is the fixed words.
    assert said.deterministic
    texts = [clause.text for clause in said.answer.clauses]
    if late:
        assert len(transport.requests) == 1
        assert said.rejections[-1] == "composer_repair_skipped: the wait bound"
        assert texts[1] == (
            "The lines the model chose could not be used, and there was no time left to ask it "
            "again. Here are the latest recorded lines instead."
        )
    else:
        assert len(transport.requests) == 2
        assert not any("could not be used" in text for text in texts)


def test_with_one_line_the_fixed_words_say_one_line_and_show_it():
    one = EVENTS[:1]
    client, _ = _choosing(
        TransportError("the composer timed out", timed_out=True, reached_provider=None)
    )
    said = _happened(client, _scene("what happened?", events=one))
    texts = [clause.text for clause in said.answer.clauses]
    assert texts[1].endswith("Here is the latest recorded line instead.")
    assert [clause.type for clause in said.answer.clauses] == [
        ClauseType.META,
        ClauseType.META,
        ClauseType.SIMULATION,
        ClauseType.META,
    ]
    assert "This is its latest recorded minute" in texts[0]


def test_no_refusal_or_note_carries_a_bracketed_label_the_page_would_draw_as_a_person():
    """The page draws every bracketed label as a person or a place, so a refusal that named one
    would be drawn as "a simulated person this page is not showing"."""
    from exulanica.selection import question, society_question

    texts = [
        *(text for _, text in society_question._REFUSALS.values()),
        *society_question._UNANSWERED.values(),
        *society_question._UNANSWERED_SHOWN.values(),
        society_question._UNANSWERED_SHOWN_MANY,
        society_question._NOT_A_MEMORY,
        *question._SHARED_NAME.values(),
        question._PEOPLE_LEFT_OUT,
    ]
    assert len(texts) > 15
    assert [text for text in texts if re.search(r"\[[^\]]*\]", text)] == []


def test_a_saved_place_that_shares_an_inhabitant_s_name_is_noted_as_a_name_not_a_person():
    person = next(p for p in STATE["inhabitants"] if p["display_name"].startswith("Emi "))
    first = person["display_name"].split()[0]
    place = _scene(f"Show me photos of {first}", saved=(SavedName(uuid.uuid4(), "place", first),))
    assert place.shared_name == "place" and not place.collision
    saved = _scene(f"Show me photos of {first}", saved=(SavedName(uuid.uuid4(), "person", first),))
    assert saved.shared_name == "person"


def test_every_framing_has_its_words_in_the_catalog():
    catalog = inhabitant_words_catalog()
    for framing in Framing:
        assert catalog.words("phrase", f"framing_{framing}")
