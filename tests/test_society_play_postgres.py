"""A person plays one being of a saved world's society of things, through the routes and against
PostgreSQL as the runtime role a deployment runs as.

What is shown:

*   a person starts playing the knight; the turn read names what the minute offers; their answer
    is kept, out of every other workspace's reach, and the host takes it as the knight's receipt
    for that minute, which the minute applies (a line said is marked as a person's); an answer for
    a minute already played is refused ``minute_passed`` with the minute that is now, and so is one
    after the minute has taken the being's answer; a pasted line is kept trimmed in normal form C;
    the models read and the card say a person plays it and that it is the reader, never the
    account; given back, its routine decides again; the society replays with no player;
*   a person who stops answering is taken off: after the quiet minutes the being carries on alone
    in, the host gives it back (``player_left``);
*   nobody else's play can be started over theirs (``being_played``), and only a society of things'
    beings are played (``engine_takes_no_play``); only the person playing a being answers for it
    or gives it back (``not_played``, nothing kept), and the owner chooses no decider for it
    meanwhile (409 ``being_played``); at most twelve answers a minute (``too_many_answers``, with
    ``Retry-After`` where the society plays), and another person's answer is never taken as theirs;
*   a played being takes its person's answer where the host asks no model and on a step with no
    host, never its routine; an answer for a being that left is not found;
*   a person walks the knight to a spot they choose: refused without the spot or off the ground,
    and otherwise taken at the minute as the open node nearest it, which the knight walks to;
*   a line carrying a name the account holder saved is never said: one posted before the name was
    saved is passed over when its minute comes (``person_line_withheld``, no quiet minute), and one
    posted after is refused (``line_refused_by_rules``), with nothing kept.
"""

from __future__ import annotations

import dataclasses
import json
import time
import unicodedata
import uuid

import pytest
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_play import QUIET_MINUTES

import test_outside_deciders_postgres as outside
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from test_society_person_decisions_postgres import _claim, _decisions, _services
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
LINE_KINDS = ("say_to", "say_all")


def _knight_society(world, client, *, beside: bool = False):
    """A society of things with a knight placed in it, and, ``beside``, a second knight a metre
    away, so the first is offered a line to it from the first minute."""
    outside._offering_societies_of_things(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    if beside:
        things_api._place(client, world, "knight-2", "knight", 1, 3_000, 4_000)
    snapshot = things_api._make_society(client, world)
    [knight] = [p["id"] for p in snapshot["state"]["inhabitants"] if p["placed_id"] == "knight"]
    return snapshot, knight


def _post(client, path, scope, body):
    return client.post(path, headers=OWNER, params=scope, json=body)


def _start(client, world, knight):
    scope, _, society = routes(world)
    return _post(
        client,
        society + "/play",
        scope,
        {"idempotency_key": str(uuid.uuid4()), "subject_id": knight},
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_plays_the_knight_and_its_minute_takes_their_answer(app):
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client, beside=True)
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    actor = str(world["session"].actor)
    started = _start(client, world, knight)
    assert started.status_code == 201, started.text
    assert started.json()["played_by_you"] is True and actor not in started.text
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    assert (turn["played_by_you"], turn["base_tick"]) == (True, snapshot["current_tick"])
    # A line, to the other knight or to everyone near.
    chosen = next(o for o in turn["options"] if o["takes_line"])
    line = "Good evening."
    answered = _post(
        client,
        play + "/answer",
        scope,
        {"base_tick": turn["base_tick"], "label": chosen["label"], "line": line},
    )
    assert answered.status_code == 202, answered.text
    # The answer is the workspace's alone: another workspace's session reads none of it.
    with services.database.session(world["workspace"]) as mine:
        assert (
            mine.execute("select count(*) as n from world_society_person_answer").fetchone()["n"]
            == 1
        )
    with services.database.session(uuid.uuid4()) as theirs:
        assert (
            theirs.execute("select count(*) as n from world_society_person_answer").fetchone()["n"]
            == 0
        )
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["status"], receipt["reason"], receipt["proposal"]["label"]) == (
        "accepted",
        "validated_choice",
        chosen["label"],
    )
    assert receipt["provider"]["kind"] == "person" and actor not in json.dumps(receipt)
    snapshot = stays._step(world, client, snapshot)
    [applied] = [
        e
        for e in outside._events(client, world, "decision_applied")
        if e["tick"] == snapshot["current_tick"]
    ]
    assert applied["document"]["origin"] == "person"
    said = [e for e in outside._events(client, world, "said") if e["subject_id"] == knight]
    assert said[-1]["document"]["thing"]["decider"] == "person"
    # An answer for a minute already played is refused, with the minute that is now.
    late = _post(
        client,
        play + "/answer",
        scope,
        {"base_tick": turn["base_tick"], "label": chosen["label"], "line": line},
    )
    assert late.status_code == 409
    assert (late.json()["code"], late.json()["current_tick"]) == (
        "minute_passed",
        snapshot["current_tick"],
    )
    # The reads say a person plays it, and that it is the reader; never which account.
    models = client.get(society + "/models", headers=OWNER, params=scope).json()
    [entry] = [c for c in models["choices"] if c["subject_id"] == knight]
    assert (entry["decider"], entry["played_by_you"], entry["chosen_by"]) == (
        {"kind": "person"},
        True,
        None,
    )
    card = client.get(f"{society}/things/{knight}", headers=OWNER, params=scope).json()
    assert (card["decider"]["kind"], card["decider"]["played_by_you"]) == ("person", True)
    assert actor not in json.dumps(entry) and actor not in json.dumps(card["decider"])
    # Given back, its routine decides for it again.
    back = _post(client, play + "/give-back", scope, {"idempotency_key": str(uuid.uuid4())})
    assert back.status_code == 200, back.text
    models = client.get(society + "/models", headers=OWNER, params=scope).json()
    assert knight not in {c["subject_id"] for c in models["choices"]}
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_answer_is_taken_until_its_minute_takes_the_being_s(app):
    """A line pasted in another normal form with a space after it is the same line, kept trimmed
    in normal form C. Once the minute has taken the knight's answer, and before it has run, a later
    answer would be read by nothing: it is refused with the minute, and nothing is kept."""
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client, beside=True)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    say = next(o for o in turn["options"] if o["takes_line"])
    body = {"base_tick": turn["base_tick"], "label": say["label"]}
    pasted = unicodedata.normalize("NFD", "Café au lait? ")
    assert _post(client, play + "/answer", scope, {**body, "line": pasted}).status_code == 202
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["reason"], receipt["proposal"]["line"]) == ("validated_choice", "Café au lait?")
    late = _post(client, play + "/answer", scope, {**body, "line": "Good night."})
    assert (late.status_code, late.json()["code"], late.json()["current_tick"]) == (
        409,
        "minute_passed",
        turn["base_tick"],
    )
    assert _answers_kept(services, world) == 1


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_being_whose_person_stops_answering_is_given_back(app):
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client)
    assert _start(client, world, knight).status_code == 201
    host = outside._doorkeeping_host(world, services, None)
    for _ in range(QUIET_MINUTES):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    reasons = [r["reason"] for r in _decisions(services, world, snapshot)]
    assert reasons == ["person_no_answer"] * QUIET_MINUTES
    with services.database.session(world["workspace"]) as connection:
        history = SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).history(world["binding"].version_id, person_role())
    assert [choice.get("ended") for choice in history] == [None, "player_left"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_nobody_plays_a_being_another_person_plays(app):
    world, client = app
    services = _services(client)
    _snapshot, knight = _knight_society(world, client)
    assert _start(client, world, knight).status_code == 201
    role = person_role()
    with services.database.session(world["workspace"]) as connection:
        repository = SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        )
        with pytest.raises(ModelChoiceRefused) as caught:
            repository.record_play(
                world["binding"].version_id,
                role,
                request_id=uuid.uuid4(),
                subject=knight,
                account_id=uuid.UUID(int=0xB0B),
                contract=role.contract(role.terms("exulanica-society/v7").versions),
            )
    assert caught.value.code == "being_played"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_a_society_of_things_beings_are_played(app):
    world, client = app
    snapshot = stays._inhabited(world, client)
    person = snapshot["state"]["inhabitants"][0]["id"]
    refused = _start(client, world, person)
    assert refused.status_code == 409 and refused.json()["code"] == "engine_takes_no_play"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_carrying_a_saved_name_is_never_said(app):
    """A line posted before the account holder saved a name it carries is not said when its
    minute comes (the being carries on), and one posted after is refused when it is posted."""
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client, beside=True)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    say = next(o for o in turn["options"] if o["takes_line"])
    body = {"base_tick": turn["base_tick"], "label": say["label"]}
    posted = _post(client, play + "/answer", scope, {**body, "line": "Good evening, Hazel."})
    assert posted.status_code == 202
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    rename_entity(
        identity,
        AssertionWriter(connection, world["workspace"]),
        entity_id=identity.entities.create(entity_class="person"),
        display_name="Hazel Moss",
        actor=world["session"].actor,
    )
    connection.commit()
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    [receipt] = _decisions(services, world, snapshot)
    assert receipt["reason"] == "person_line_withheld"
    snapshot = stays._step(world, client, snapshot)
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    # The person answered, so the minute is no quiet one.
    assert turn["quiet_left"] == QUIET_MINUTES
    say = next(o for o in turn["options"] if o["takes_line"])
    body = {"base_tick": turn["base_tick"], "label": say["label"]}
    refused = _post(client, play + "/answer", scope, {**body, "line": "Good evening, Hazel."})
    assert refused.status_code == 422 and refused.json()["code"] == "line_refused_by_rules"
    with services.database.session(world["workspace"]) as held:
        kept = held.execute(
            "select count(*) as n from world_society_person_answer where base_tick = %s",
            (turn["base_tick"],),
        ).fetchone()
    assert kept["n"] == 0
    # The positive control: the same line without the name is kept.
    assert (
        _post(client, play + "/answer", scope, {**body, "line": "Good evening."}).status_code == 202
    )


def _play_for_someone_else(services, world, knight) -> None:
    """Another account plays the knight, recorded as the play route records a play."""
    role = person_role()
    with services.database.session(world["workspace"]) as connection:
        SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_play(
            world["binding"].version_id,
            role,
            request_id=uuid.uuid4(),
            subject=knight,
            account_id=uuid.UUID(int=0xB0B),
            contract=role.contract(role.terms("exulanica-society/v7").versions),
        )


def _answers_kept(services, world) -> int:
    with services.database.session(world["workspace"]) as held:
        return held.execute("select count(*) as n from world_society_person_answer").fetchone()["n"]


def _quiet_option(turn):
    """An option of the turn that takes neither a line nor a spot: waiting, or the first such."""
    return next(
        option
        for option in turn["options"]
        if not option["takes_line"] and not option["takes_point"]
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_the_person_playing_a_being_answers_for_it_or_gives_it_back(app):
    world, client = app
    services = _services(client)
    _snapshot, knight = _knight_society(world, client)
    _play_for_someone_else(services, world, knight)
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    assert (turn["played"], turn["played_by_you"]) == (True, False)
    body = {"base_tick": turn["base_tick"], "label": _quiet_option(turn)["label"]}
    answered = _post(client, play + "/answer", scope, body)
    assert (answered.status_code, answered.json()["code"]) == (409, "not_played")
    back = _post(client, play + "/give-back", scope, {"idempotency_key": str(uuid.uuid4())})
    assert (back.status_code, back.json()["code"]) == (409, "not_played")
    assert _answers_kept(services, world) == 0
    # Nor does the owner choose for it meanwhile: refused as the play routes refuse it.
    chose = _post(
        client,
        society + "/models",
        scope,
        {"idempotency_key": str(uuid.uuid4()), "people": [knight], "model": None},
    )
    assert (chose.status_code, chose.json()["code"]) == (409, "being_played")


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_answers_at_most_twelve_times_a_minute(app):
    world, client = app
    services = _services(client)
    _snapshot, knight = _knight_society(world, client)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    body = {"base_tick": turn["base_tick"], "label": _quiet_option(turn)["label"]}
    for _ in range(12):
        assert _post(client, play + "/answer", scope, body).status_code == 202
    # The society plays, its next minute due in a minute and a half: the refusal says when the
    # person may answer again.
    control = client.get(society + "/control", headers=OWNER, params=scope).json()
    playing = client.put(
        society + "/control",
        headers=OWNER,
        params=scope,
        json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
    )
    assert playing.status_code == 200, playing.text
    world["connection"].execute(
        "update world_society_control set next_due_at = clock_timestamp() + interval '90 seconds' "
        "where workspace_id = %s",
        (world["workspace"],),
    )
    world["connection"].commit()
    over = _post(client, play + "/answer", scope, body)
    assert (over.status_code, over.json()["code"]) == (429, "too_many_answers")
    assert 60 <= int(over.headers["Retry-After"]) <= 90
    assert _answers_kept(services, world) == 12


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_another_person_s_answer_is_never_taken_as_theirs(app):
    """A answers for the minute and gives the knight back; B takes it in the same minute and
    posts nothing: the minute is B's carrying on, never A's line."""
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client, beside=True)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    say = next(option for option in turn["options"] if option["takes_line"])
    body = {"base_tick": turn["base_tick"], "label": say["label"], "line": "Good evening."}
    assert _post(client, play + "/answer", scope, body).status_code == 202
    back = _post(client, play + "/give-back", scope, {"idempotency_key": str(uuid.uuid4())})
    assert back.status_code == 200, back.text
    _play_for_someone_else(services, world, knight)
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    [receipt] = _decisions(services, world, snapshot)
    assert (receipt["reason"], receipt["provider"]["answer_sha256"]) == ("person_no_answer", None)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_played_being_takes_its_answer_where_no_model_is_asked(app):
    """The host asks no model in this workspace, and then no host runs at all (the step route):
    each minute is still the person's answer, never the knight's routine."""
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client, beside=True)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"

    def say(line):
        turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
        chosen = next(option for option in turn["options"] if option["takes_line"])
        body = {"base_tick": turn["base_tick"], "label": chosen["label"], "line": line}
        assert _post(client, play + "/answer", scope, body).status_code == 202

    say("Good evening.")
    host = dataclasses.replace(
        outside._doorkeeping_host(world, services, None), workspaces=frozenset()
    )
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    snapshot = stays._step(world, client, snapshot)
    say("Good night.")
    snapshot = stays._step(world, client, snapshot)
    receipts = _decisions(services, world, snapshot)
    assert [(r["reason"], r["proposal"].get("line")) for r in receipts] == [
        ("validated_choice", "Good evening."),
        ("validated_choice", "Good night."),
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_answer_for_a_played_being_that_left_is_not_found(app):
    world, client = app
    snapshot, knight = _knight_society(world, client)
    assert _start(client, world, knight).status_code == 201
    scope, root, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    body = {"base_tick": turn["base_tick"], "label": _quiet_option(turn)["label"]}
    base = client.get(root, headers=OWNER, params=scope).json()["state_sha256"]
    removed = _post(client, root + "/things/knight/remove", scope, {"base_state_sha256": base})
    assert removed.status_code == 200, removed.text
    snapshot = stays._step(world, client, snapshot)
    assert knight not in {p["id"] for p in snapshot["state"]["inhabitants"]}
    gone = _post(client, play + "/answer", scope, {**body, "base_tick": snapshot["current_tick"]})
    assert (gone.status_code, gone.json()["code"]) == (404, "person_not_in_this_world")


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_walks_the_knight_to_a_spot_they_choose(app):
    world, client = app
    services = _services(client)
    snapshot, knight = _knight_society(world, client)
    assert _start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    play = f"{society}/play/{knight}"
    turn = client.get(play + "/turn", headers=OWNER, params=scope).json()
    [walk] = [option for option in turn["options"] if option["takes_point"]]
    body = {"base_tick": turn["base_tick"], "label": walk["label"]}
    refused = _post(client, play + "/answer", scope, body)
    assert (refused.status_code, refused.json()["code"]) == (422, "point_needed")
    off = _post(client, play + "/answer", scope, {**body, "point": [10**8, 10**8]})
    assert (off.status_code, off.json()["code"]) == (422, "not_walkable")
    here = next(p for p in snapshot["state"]["inhabitants"] if p["id"] == knight)["position_mm"]
    spot = [here[0], here[1] + 4_000]
    assert _post(client, play + "/answer", scope, {**body, "point": spot}).status_code == 202
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    [receipt] = _decisions(services, world, snapshot)
    node = receipt["proposal"]["node_id"]
    assert (receipt["reason"], receipt["proposal"]["label"]) == ("validated_choice", walk["label"])
    snapshot = stays._step(world, client, snapshot)
    walker = next(p for p in snapshot["state"]["inhabitants"] if p["id"] == knight)
    assert walker["route"]["destination_node_id"] == node
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True
