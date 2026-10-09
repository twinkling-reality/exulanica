"""Lines through the door, both ways, against PostgreSQL.

Through the real routes, as a world's owner and as a bridge with a channel credential, with the
door's crossings handed to the society of things and a decision host that asks a scripted model
for a knight placed beside the gate and the door for a visitor:

*   the visitor's ask names which labels say a line and how long one may be, in the words of the
    terms the request was asked under, and an answer is held to them by name;
*   the visitor's line to the knight and the knight's line to the visitor reach the visitor's bridge
    as said frames: who said each, in words and by who decided it, to whom, and the line;
*   another grant, whose visitor arrived after those lines were said, reads none of them, and a line
    said once a grant's visitor has gone never reaches that grant, though another grant's visitor
    said it in the same society;
*   a name the account holder saves afterwards is screened from every said frame read again: a
    line, a speaker's words and an addressee's words carrying it are sent as null;
*   a grant's first line refused for carrying a saved name closes its lines: every later line is
    refused while the grant acts on, and its owner reads that its lines are closed; every line the
    grant's program answered in that minute is refused with it, so the program cannot tell which
    carried the name; a line holding a placeholder-shaped token is refused;
*   more lines than one poll holds are each told once, in order, read again from an old cursor; a
    poll with nothing to tell moves its line place past the minutes it read, and reads a grant's
    departures before its lines; one whose read moves nothing at all is held for its whole hold;
*   a visitor that chooses to leave departs, and one whose player left goes home after its kind's
    quiet minutes; its bridge reads why, in the society's own words.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.door.channel import PLACES_A_MINUTE, ChannelRepository
from exulanica.door.protocol import Cursor
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.models.transport import HttpResponse
from exulanica.world.society_controls import LEASE_SECONDS

import test_society_authored_world_postgres as helpers
import test_society_person_decisions_postgres as decisions
from model_fakes import FakeTransport, chat_body
from test_door_crossings_postgres import _arrive, _grant, crossings
from test_door_postgres import (
    OWNER,
    _credential,
    _frames,
    _grant_for,
    _hello,
    _person_request,
    _store_external,
)
from test_door_postgres import door as door
from test_society_things_postgres import _make_society, _place, _replayed, _step

saved_world = helpers.saved_world
crossings = crossings
pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
#: What the knight's model says to the visitor, and the visitor's player to the knight.
KNIGHT_LINE = "Well met, traveller from afar."
VISITOR_LINE = "Good day to you, sir."
#: What a second visitor says after a first one has gone home.
STAYING_LINE = "Is anyone about?"


def _catalog(name: str) -> Any:
    return json.loads((ROOT / "assets" / "catalogs" / name).read_text(encoding="utf-8"))


def _things_terms() -> dict[str, Any]:
    """The terms a society of things' people are asked under, read from the role registry's newest
    version, the one a host asks under."""
    versions = (ROOT / "assets" / "catalogs" / "roles").glob("decision-roles.v*.json")
    newest = max(int(path.name.removeprefix("decision-roles.v").split(".")[0]) for path in versions)
    registry = _catalog(f"roles/decision-roles.v{newest}.json")
    [role] = [entry for entry in registry["entries"] if entry["key"] == "society_decision"]
    [terms] = [t for t in role["engine_terms"] if t["engine"] == "exulanica-society/v7"]
    return terms


def _line_bound() -> int:
    """The longest line, as the policy catalog the society of things asks under states it."""
    policy = _catalog(f"society/society-decision-policy.v{_things_terms()['policy_version']}.json")
    return next(
        int(bound["value"])
        for bound in policy["entries"]
        if bound["key"] == "line_characters_maximum"
    )


class _Knight(FakeTransport):
    """A scripted model that says ``KNIGHT_LINE`` to the visitor whenever it may, else to everyone
    near, and otherwise goes on or waits; it keeps each label it said a line by."""

    def __init__(self) -> None:
        super().__init__()
        self.said_to: list[str] = []

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        properties = payload["tools"][0]["function"]["parameters"]["properties"]
        labels = properties["action"]["enum"]
        to_all = next((each for each in labels if each.startswith("say something to every")), None)
        say = next(
            (label for label in labels if label.startswith("say something to the visitor")), to_all
        )
        if say is not None:
            self.said_to.append(say)
            arguments = {"action": say, "line": KNIGHT_LINE}
        else:
            idle = next(label for label in labels if label.startswith(("carry on", "wait")))
            arguments = {"action": idle, **({"line": None} if "line" in properties else {})}
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps(arguments)},
            }
        ]
        return HttpResponse(200, json.dumps(body))


class _Bridge:
    """A bridge beside the host, as an adapter runs: it polls its channel, keeps every frame it
    reads, and answers each ask with what ``choose`` gives for the frame (a body, or None to let
    the ask run out), keeping each answer's status."""

    def __init__(self, client, channel, cursor, choose: Callable[[dict], dict | None]) -> None:
        self.client = client
        self.channel = channel
        self.cursor = cursor
        self.choose = choose
        self.frames: list[dict[str, Any]] = []
        self.answers: list[tuple[dict[str, Any], int, dict[str, Any]]] = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> _Bridge:
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stopped.set()
        self.thread.join(timeout=10)

    def _run(self) -> None:
        while not self.stopped.is_set():
            read = self.client.get(
                "/door/channel/frames", headers=self.channel, params={"after": self.cursor}
            )
            if read.status_code != 200:
                time.sleep(0.2)
                continue
            self.cursor = read.json()["cursor"]
            for frame in read.json()["frames"]:
                self.frames.append(frame)
                if frame["kind"] != "asked":
                    continue
                for body in self._bodies(frame):
                    answered = self.client.post(
                        "/door/channel/answers", headers=self.channel, json=body
                    )
                    self.answers.append((body, answered.status_code, answered.json()))
                    if answered.status_code == 202:
                        break

    def _bodies(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        chosen = self.choose(frame)
        if chosen is None:
            return []
        tries = chosen if isinstance(chosen, list) else [chosen]
        return [
            {"request_id": frame["request_id"], "request_sha256": frame["request_sha256"], **body}
            for body in tries
        ]


def _host(door, transport) -> tuple[DecisionHost, Any, str]:
    """A host that asks a scripted model for the world's own people and the door for its
    visitors, the manifest it reads and the model it offers."""
    services = door["client"].app.state.services
    manifest, model_id = decisions._offered()

    def policy_for(workspace_id):
        return services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        )

    host = DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=decisions._client(manifest, transport),
        workspaces=frozenset({door["world"]["workspace"]}),
        policy_for=policy_for,
        manifest=manifest,
        manifest_sha256="a" * 64,
        external=door["runtime"].asker(),
    )
    return host, manifest, model_id


def _world_with_a_knight(door) -> tuple[dict[str, Any], dict[str, Any]]:
    """A society of things with a gate and a knight within hearing of where visitors arrive."""
    world, client = door["world"], door["client"]
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "gate", "gate", 1, 0, 6_000)
    _place(client, world, "knight", "knight", 1, 3_000, 3_000)
    return world, _make_society(client, world)


def _person(society: dict[str, Any], *, placed: str | None = None, came_by: str | None = None):
    [found] = [
        p
        for p in society["state"]["inhabitants"]
        if (placed is None or p.get("placed_id") == placed)
        and (came_by is None or p["came_by"] == came_by)
    ]
    return found


def _minute(door, host, world, society) -> dict[str, Any]:
    """One minute: the host asks whoever is due, then the society steps."""
    host.before_minute(decisions._claim(world, society), time.monotonic() + LEASE_SECONDS)
    return _step(door["client"], world, society)


def _said(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [frame for frame in frames if frame["kind"] == "said"]


def _read_all(door, channel, cursor) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for _ in range(20):
        read = _frames(door, channel, cursor)
        assert read.status_code == 200, read.text
        frames.extend(read.json()["frames"])
        if read.json()["cursor"] == cursor:
            return frames
        cursor = read.json()["cursor"]
    raise AssertionError("a channel kept reading frames after twenty polls")


# On the endless ground: the bounded ground's villagers may stand nearer the knight than the visitor
# does, and a being is offered a line to its three nearest hearers only, so whether these two speak
# there depends on where the seed puts everyone; what the door sends does not depend on the ground.
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_lines_reach_the_visitor_s_bridge_as_said_frames_screened_as_they_are_sent(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    knight = _person(society, placed="knight")
    transport = _Knight()
    host, manifest, model_id = _host(door, transport)
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(client.app.state.services, world, [knight["id"]], model, manifest=manifest)
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    hello = _hello(door, channel)
    assert hello.status_code == 200, hello.text
    start = hello.json()["cursor"]
    visitor_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    visitor = _person(society, came_by="crossed")
    assert visitor["id"] == visitor_id
    bridges: list[_Bridge] = []

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        """Say the visitor's line to the knight until it is taken, then go on or wait."""
        options = frame["context"]["options"]
        to_knight = next(
            (o for o in options if o["kind"] == "say_to" and o["addressee_id"] == knight["id"]),
            None,
        )
        taken = any(
            body.get("line") == VISITOR_LINE and status == 202
            for body, status, _answer in bridges[0].answers
        )
        if to_knight is not None and not taken:
            return {"label": to_knight["label"], "line": VISITOR_LINE}
        return {"label": frame["idle_label"]}

    with _Bridge(client, channel, start, choose) as bridge:
        bridges.append(bridge)
        for _ in range(20):
            society = _minute(door, host, world, society)
            lines = {(f["speaker"]["id"], f["line"]) for f in _said(bridge.frames)}
            if {(visitor_id, VISITOR_LINE), (knight["id"], KNIGHT_LINE)} <= lines:
                break
            time.sleep(1.5)  # a poll held one second reads what the minute said
        else:
            asked = [
                r["payload"]["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
                for r in transport.requests
            ]
            where = {
                p["id"][:8]: (p.get("came_by"), p.get("position_mm"))
                for p in society["state"]["inhabitants"]
            }
            raise AssertionError(
                f"the two lines were not both read in twenty minutes: {lines}; the knight's model "
                f"was offered {asked}; knight {knight['id'][:8]} visitor {visitor_id[:8]} {where}"
            )
    knight_words = f"the knight (person {knight['ordinal'] + 1})"
    visitor_words = f"the visitor (person {visitor['ordinal'] + 1})"
    said = _said(bridge.frames)
    by_visitor = next(f for f in said if f["speaker"]["id"] == visitor_id)
    by_knight = next(f for f in said if f["speaker"]["id"] == knight["id"])
    # Whom the knight's line was said to: the visitor, or everyone near when the visitor was not
    # among the nearest offered; the knight's model chose a label of that kind for one of its lines.
    to_visitor = by_knight["to"] is not None
    chosen = "say something to the visitor" if to_visitor else "say something to every"
    assert any(label.startswith(chosen) for label in transport.said_to), transport.said_to
    knight_to = (visitor_id, visitor_words) if to_visitor else (None, None)
    assert {key: value for key, value in by_visitor.items() if key != "tick"} == {
        "kind": "said",
        "speaker": {
            "id": visitor_id,
            "label": visitor_words,
            "mind": {"ai": False, "words": "A test bridge"},
        },
        "to": knight["id"],
        "to_label": knight_words,
        "line": VISITOR_LINE,
    }
    assert {key: value for key, value in by_knight.items() if key != "tick"} == {
        "kind": "said",
        "speaker": {
            "id": knight["id"],
            "label": knight_words,
            "mind": {"ai": True, "words": manifest.model_name(model_id)},
        },
        "to": knight_to[0],
        "to_label": knight_to[1],
        "line": KNIGHT_LINE,
    }
    # Every ask the visitor's bridge read stated which labels say a line, in the society of
    # things' own terms, and the bridge's answers were taken.
    asked = [frame for frame in bridge.frames if frame["kind"] == "asked"]
    assert asked and all(frame["instruction"] == _things_terms()["instruction"] for frame in asked)
    for frame in asked:
        says = [
            o["label"] for o in frame["context"]["options"] if o["kind"] in ("say_to", "say_all")
        ]
        assert frame["line_labels"] == says
        assert frame["line_characters_maximum"] == (_line_bound() if says else None)
    # An answer is taken, or comes after its turn was decided; none is refused.
    assert {status for _body, status, _answer in bridge.answers} <= {202, 409}
    # A bridge that says hello again reads on from there: lines said before it are not sent again.
    again = _hello(door, channel)
    assert again.status_code == 200, again.text
    assert _said(_read_all(door, channel, again.json()["cursor"])) == []

    # Another grant, whose visitor arrived after those lines were said, reads none of them.
    _other, other_channel = _grant(door, key="visitors-0002", may_carry_in=False)
    assert _hello(door, other_channel).status_code == 200
    _arrive(client, other_channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)
    assert _said(_read_all(door, other_channel, None)) == []

    # A name the account holder saves afterwards: every said frame read again leaves it out.
    model_word = next(
        word
        for word in manifest.model_name(model_id).split()
        if sum(c.isalpha() for c in word) >= 4
    )
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    rename_entity(
        identity,
        AssertionWriter(connection, world["workspace"]),
        entity_id=identity.entities.create(entity_class="person"),
        display_name=f"Afar Knight {model_word}",
        actor=world["session"].actor,
    )
    connection.commit()
    again = _said(_read_all(door, channel, start))
    by_visitor = next(f for f in again if f["speaker"]["id"] == visitor_id)
    by_knight = next(f for f in again if f["speaker"]["id"] == knight["id"])
    # The visitor's line names nobody saved; the knight it was said to now is a saved word.
    assert (by_visitor["line"], by_visitor["speaker"]["label"], by_visitor["to_label"]) == (
        VISITOR_LINE,
        visitor_words,
        None,
    )
    assert by_visitor["speaker"]["mind"] == {"ai": False, "words": "A test bridge"}
    # The knight's line ("from afar"), its words and its model's name each carry a saved word.
    assert (by_knight["line"], by_knight["speaker"]["label"], by_knight["to_label"]) == (
        None,
        None,
        knight_to[1],
    )
    assert by_knight["speaker"]["mind"] == {"ai": True, "words": None}
    assert _replayed(client, world)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_said_after_a_grant_s_visitor_left_never_reaches_that_grant(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    gone_grant, gone_channel = _grant(door, key="visitors-gone", may_carry_in=False)
    _staying_grant, staying_channel = _grant(door, key="visitors-staying", may_carry_in=False)
    gone_start = _hello(door, gone_channel).json()["cursor"]
    staying_start = _hello(door, staying_channel).json()["cursor"]
    gone = _arrive(client, gone_channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    staying = _arrive(client, staying_channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    sent = client.post(
        f"/door/grants/{gone_grant}/send-away", headers=OWNER, json={"thing_id": gone}
    )
    assert sent.status_code == 202, sent.text
    society = _step(client, world, society)
    assert [p["id"] for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"] == [
        staying
    ]
    bridges: list[_Bridge] = []

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        """Say the staying visitor's line by the first label that says one, until it is taken."""
        taken = any(
            body.get("line") == STAYING_LINE and status == 202
            for body, status, _answer in bridges[0].answers
        )
        if frame["line_labels"] and not taken:
            return {"label": frame["line_labels"][0], "line": STAYING_LINE}
        return {"label": frame["idle_label"]}

    with _Bridge(client, staying_channel, staying_start, choose) as bridge:
        bridges.append(bridge)
        for _ in range(12):
            society = _minute(door, host, world, society)
            if (staying, STAYING_LINE) in {
                (f["speaker"]["id"], f["line"]) for f in _said(bridge.frames)
            }:
                break
            time.sleep(1.5)  # a poll held one second reads what the minute said
        else:
            raise AssertionError("the staying visitor's line was not read in twelve minutes")
    # The grant whose visitor had gone reads nothing its visitor did not say or hear, though the
    # line was said in the society its visitor was in, by another grant's visitor.
    lines = {
        (f["speaker"]["id"], f["line"]) for f in _said(_read_all(door, gone_channel, gone_start))
    }
    assert (staying, STAYING_LINE) not in lines


def test_an_answer_says_a_line_exactly_where_its_label_does(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)
    bound = _line_bound()

    def choose(frame: dict[str, Any]) -> list[dict[str, Any]] | None:
        says = frame["line_labels"]
        idle = frame["idle_label"]
        if not says:
            return {"label": idle}
        return [
            {"label": says[0]},
            {"label": idle, "line": "Nothing to say."},
            {"label": says[0], "line": "x" * (bound + 1)},
            {"label": says[0], "line": "A bell\u0007 rings."},
            {"label": says[0], "line": "Ask [person MARIA] about it."},
            {"label": says[0], "line": "Hello there."},
        ]

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(8):
            society = _minute(door, host, world, society)
            if any(status == 202 for _body, status, _answer in bridge.answers):
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the visitor was never offered a line to say in eight minutes")
    # The first ask offering a line, answered five ways in turn until one was taken.
    first = next(f for f in bridge.frames if f["kind"] == "asked" and f["line_labels"])
    codes = [
        (status, answer.get("code"))
        for body, status, answer in bridge.answers
        if body["request_id"] == first["request_id"]
    ]
    assert codes == [
        (422, "line_missing"),
        (422, "line_not_offered"),
        (422, "line_refused"),
        (422, "line_refused"),
        (422, "line_refused"),
        (202, None),
    ]


def test_a_grant_whose_people_may_not_speak_takes_no_line(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False, may_speak=False)
    start = _hello(door, channel).json()["cursor"]
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)

    def choose(frame: dict[str, Any]) -> list[dict[str, Any]] | None:
        says = frame["line_labels"]
        idle = frame["idle_label"]
        if not says:
            return {"label": idle}
        return [{"label": says[0], "line": "Hello there."}, {"label": idle}]

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(8):
            society = _minute(door, host, world, society)
            if any(status == 202 for _body, status, _answer in bridge.answers):
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the visitor was never offered a line to say in eight minutes")
    first = next(f for f in bridge.frames if f["kind"] == "asked" and f["line_labels"])
    codes = [
        (status, answer.get("code"))
        for body, status, answer in bridge.answers
        if body["request_id"] == first["request_id"]
    ]
    assert codes == [(403, "speaking_not_allowed"), (202, None)]


def test_a_visitor_that_chooses_to_leave_departs_and_its_bridge_reads_why(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    visitor_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        leave = next(o for o in frame["context"]["options"] if o["kind"] == "leave")
        return {"label": leave["label"]}

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(6):
            society = _minute(door, host, world, society)
            departed = [f for f in bridge.frames if f["kind"] == "departed"]
            if departed:
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the visitor did not leave in six minutes")
    [left] = departed
    assert (left["thing_id"], left["why"], left["carried"]) == (visitor_id, "chose_to_leave", [])
    assert _replayed(client, world)


def test_a_visitor_whose_player_left_goes_home_after_its_quiet_minutes(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    visitor_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    gone = client.post("/door/channel/gone", headers=channel, json={"thing_id": visitor_id})
    assert gone.status_code == 202, gone.text
    visitor = json.loads((ROOT / "assets/catalogs/things/kinds/visitor.v1.json").read_text())
    quiet = next(a for a in visitor["abilities"] if a["key"] == "leave")["parameters"]
    for _ in range(quiet["quiet_minutes"] + 3):
        society = _minute(door, host, world, society)
        if not [p for p in society["state"]["inhabitants"] if p["id"] == visitor_id]:
            break
    else:
        raise AssertionError("a visitor nobody is behind stayed past its quiet minutes")
    departed = [f for f in _read_all(door, channel, start) if f["kind"] == "departed"]
    assert [(f["thing_id"], f["why"]) for f in departed] == [(visitor_id, "decider_lost")]


def _save_name(world, name: str) -> None:
    """A person's name the account holder saves."""
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    rename_entity(
        identity,
        AssertionWriter(connection, world["workspace"]),
        entity_id=identity.entities.create(entity_class="person"),
        display_name=name,
        actor=world["session"].actor,
    )
    connection.commit()


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_grant_s_first_line_carrying_a_saved_name_closes_its_lines(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)
    _save_name(world, "Marisol Vega")
    named: list[str] = []

    def choose(frame: dict[str, Any]) -> list[dict[str, Any]] | dict[str, Any]:
        says, idle = frame["line_labels"], frame["idle_label"]
        if not says:
            return {"label": idle}
        if not named:
            named.append(frame["request_id"])
            return {"label": says[0], "line": "Is Marisol about?"}
        return [{"label": says[0], "line": "Hello there."}, {"label": idle}]

    def refused_later(bridge: _Bridge) -> list[tuple[int, Any]]:
        return [
            (status, answer.get("code"))
            for body, status, answer in bridge.answers
            if body.get("line") == "Hello there."
        ]

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(12):
            society = _minute(door, host, world, society)
            if refused_later(bridge):
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the visitor was never offered a line again in twelve minutes")
    # The host refused the line carrying the saved name, and the bridge read why.
    [outcome] = [
        f for f in bridge.frames if f.get("request_id") == named[0] and f["kind"] == "outcome"
    ]
    assert (outcome["status"], outcome["reason"]) == ("rejected", "line_refused_by_rules")
    # Every later line is refused while the grant acts on: its idle answers are still taken.
    assert set(refused_later(bridge)) == {(403, "speaking_not_allowed")}
    assert any(status == 202 and "line" not in body for body, status, _answer in bridge.answers)
    view = client.get(f"/door/grants/{grant_id}", headers=OWNER).json()["grant"]
    assert view["lines_closed"] is True


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_grant_s_lines_of_the_minute_a_saved_name_is_refused_are_refused_together(
    door, crossings
):
    """Two visitors of one grant probe in one minute, one line carrying a saved name and one
    carrying none: both are refused alike, so the program cannot tell which carried it."""
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False, visitors_maximum=2)
    start = _hello(door, channel).json()["cursor"]
    naming = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    other = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    _save_name(world, "Marisol Vega")
    clean_lines: dict[int, str] = {}
    probe: dict[str, str] = {}

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        says, idle = frame["line_labels"], frame["idle_label"]
        if not says or probe:
            return {"label": idle}
        if frame["subject_id"] == other:
            clean_lines[frame["minute"]] = frame["request_id"]
            return {"label": says[0], "line": "Hello there."}
        assert frame["subject_id"] == naming
        if frame["minute"] not in clean_lines:
            return {"label": says[0], "line": "Good day."}
        # The other visitor's clean line of this minute is stored already: this one names.
        probe.update(named=frame["request_id"], clean=clean_lines[frame["minute"]])
        return {"label": says[0], "line": "Is Marisol about?"}

    def outcomes(bridge: _Bridge) -> dict[str, tuple[str, str]]:
        return {
            f["request_id"]: (f["status"], f["reason"])
            for f in bridge.frames
            if f["kind"] == "outcome" and f["request_id"] in probe.values()
        }

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(24):
            society = _minute(door, host, world, society)
            if probe and len(outcomes(bridge)) == 2:
                break
            time.sleep(1.5)
        else:
            raise AssertionError("no minute asked both visitors for a line in twenty-four minutes")
    refused = ("rejected", "line_refused_by_rules")
    assert outcomes(bridge) == {probe["named"]: refused, probe["clean"]: refused}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_more_lines_than_a_poll_holds_are_each_told_once_and_in_order(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    host, _manifest, _model_id = _host(door, _Knight())
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    visitor = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    numbers = iter(range(1, 1000))

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        says = frame["line_labels"]
        if says:
            return {"label": says[0], "line": f"Line {next(numbers)}."}
        return {"label": frame["idle_label"]}

    def own(frames: list[dict[str, Any]]) -> list[str]:
        return [f["line"] for f in _said(frames) if f["speaker"]["id"] == visitor]

    with _Bridge(client, channel, start, choose) as bridge:
        for _ in range(60):
            society = _minute(door, host, world, society)
            if len(own(bridge.frames)) > 33:
                break
            time.sleep(1.2)
        else:
            raise AssertionError("the visitor said fewer than 34 lines in sixty minutes")
        told = own(bridge.frames)

    # Each line told once, in the order said, as it was said and read again from the first cursor,
    # more than one poll's 32 frames at a time; the read again may hold a last line or two the
    # bridge had not yet read when it stopped.
    def each_once_in_order(lines: list[str]) -> bool:
        numbers = [int(line.removeprefix("Line ").rstrip(".")) for line in lines]
        return numbers == sorted(numbers) and len(set(numbers)) == len(numbers)

    replayed = own(_read_all(door, channel, start))
    assert each_once_in_order(told) and each_once_in_order(replayed)
    assert replayed[: len(told)] == told and len(replayed) > 32


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_poll_with_nothing_to_tell_moves_its_line_place_past_the_minutes_it_read(door, crossings):
    world, society = _world_with_a_knight(door)
    client = door["client"]
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    hello = _hello(door, channel).json()["cursor"]
    # A hello starts after every line said so far: at the end of the minute the society reached.
    assert Cursor.decode(hello).said == (society["current_tick"] + 1) * PLACES_A_MINUTE - 1
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    for _ in range(3):
        society = _step(client, world, society)

    def end_of(snapshot: dict[str, Any]) -> int:
        return (snapshot["current_tick"] + 1) * PLACES_A_MINUTE - 1

    # With nobody asked, nobody says a line. A poll that tells something (the arrival) and finds
    # no line moves its place past the minutes it read ...
    told = _frames(door, channel, hello)
    assert told.status_code == 200 and told.json()["frames"], told.text
    assert Cursor.decode(told.json()["cursor"]).said == end_of(society)
    # ... and so does a poll with nothing to tell, once the society has played on.
    society = _step(client, world, society)
    quiet = _frames(door, channel, told.json()["cursor"])
    assert (quiet.status_code, quiet.json()["frames"]) == (200, [])
    assert Cursor.decode(quiet.json()["cursor"]).said == end_of(society)


def test_a_poll_whose_read_moves_nothing_is_held_for_its_whole_hold(door):
    """A revoked grant whose ask waits for its outcome has news at its head, since it ended with no
    visitor left to depart, yet a read tells nothing and moves nothing: the end waits for the
    outcome, and with no visitor there is no line place to move. Such a poll is held for its
    bridge's whole hold, as an idle one is, so a bridge that polls again on every answer does not
    loop until the outcome is recorded."""
    request, person = _person_request(door)
    grant_id = _grant_for(door, person)
    channel = _credential(door, grant_id)
    _hello(door, channel)
    external = _store_external(door, request, grant_id)
    # The host wrote the ask; no answer has come and no receipt is recorded.
    door["runtime"].asker()._write_ask(
        door["world"]["workspace"], grant_id, uuid.UUID(external["request_id"])
    )
    door["client"].post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    read = _frames(door, channel).json()
    assert [frame["kind"] for frame in read["frames"]] == ["grant", "asked"]
    started = time.monotonic()
    held = _frames(door, channel, read["cursor"])
    seconds = time.monotonic() - started
    assert (held.status_code, held.json()["frames"]) == (200, [])
    assert held.json()["cursor"] == read["cursor"]
    assert seconds >= 1  # the test bridge's hold


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_poll_reads_its_grant_s_departures_before_its_lines(door, crossings, monkeypatch):
    """A visitor's lines all come before its departure, so a poll that reads departures first never
    tells a departure, and then the end, ahead of a line of its last minute committed between the
    two reads."""
    world, society = _world_with_a_knight(door)
    client = door["client"]
    _grant_id, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    hello = _hello(door, channel).json()["cursor"]
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)
    read: list[str] = []
    for name in ("departures", "said"):
        original = getattr(ChannelRepository, name)

        def recording(self, *args, _name=name, _original=original, **kwargs):
            read.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(ChannelRepository, name, recording)
    polled = _frames(door, channel, hello)
    assert polled.status_code == 200, polled.text
    assert read[:2] == ["departures", "said"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_thing_s_asks_under_a_later_grant_hold_no_line_it_heard_before_that_grant(
    door, crossings
):
    """A knight heard one grant's visitor; a later grant handing the knight to a program is sent
    its asks without what the knight heard before that grant's first ask, though the knight holds
    the line still."""
    world, society = _world_with_a_knight(door)
    client = door["client"]
    knight = _person(society, placed="knight")
    host, _manifest, _model_id = _host(door, _Knight())
    _visitors_grant, channel = _grant(door, may_carry_in=False, may_carry_out=False)
    start = _hello(door, channel).json()["cursor"]
    _arrive(client, channel, str(uuid.uuid4()), carried=[])
    society = _step(client, world, society)

    def to_the_knight(frame: dict[str, Any]) -> dict[str, Any]:
        option = next(
            (
                o
                for o in frame["context"]["options"]
                if o["kind"] == "say_to" and o["addressee_id"] == knight["id"]
            ),
            None,
        )
        if option is None:
            return {"label": frame["idle_label"]}
        return {"label": option["label"], "line": VISITOR_LINE}

    def heard_by_the_knight(snapshot: dict[str, Any]) -> list[str]:
        return [line["line"] for line in _person(snapshot, placed="knight").get("heard", ())]

    with _Bridge(client, channel, start, to_the_knight):
        for _ in range(20):
            society = _minute(door, host, world, society)
            if VISITOR_LINE in heard_by_the_knight(society):
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the knight never heard the visitor in twenty minutes")
    _named_grant, named = _grant(
        door,
        key="the-knight-0001",
        visitors_maximum=0,
        kinds=[],
        gate=None,
        may_carry_in=False,
        may_carry_out=False,
        things=[knight["id"]],
    )
    begun = _hello(door, named).json()["cursor"]
    with _Bridge(client, named, begun, lambda frame: {"label": frame["idle_label"]}) as program:
        for _ in range(10):
            society = _minute(door, host, world, society)
            asked = [f for f in program.frames if f["kind"] == "asked"]
            if asked:
                break
            time.sleep(1.5)
        else:
            raise AssertionError("the knight's new program was never asked in ten minutes")
    assert VISITOR_LINE in heard_by_the_knight(society)
    assert VISITOR_LINE not in [line["line"] for line in asked[0]["context"].get("heard", [])]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_said_out_of_hearing_by_another_grant_s_visitor_never_reaches_a_grant(
    door, crossings
):
    """Two grants' visitors in one society at once, through gates thirty metres apart, beyond
    hearing: a line one far visitor says to the other reaches its own grant only, though the near
    grant's visitor was in the society the whole time (its range of minutes holds the line; only
    who said or heard it keeps it out)."""
    world, client = door["world"], door["client"]
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "gate", "gate", 1, 0, 6_000)
    _place(client, world, "far-gate", "gate", 1, 30_000, 6_000)
    society = _make_society(client, world)
    host, _manifest, _model_id = _host(door, _Knight())
    _near_grant, near = _grant(door, key="visitors-near", may_carry_in=False)
    _far_grant, far = _grant(
        door, key="visitors-far", may_carry_in=False, gate="far-gate", visitors_maximum=2
    )
    near_start = _hello(door, near).json()["cursor"]
    far_start = _hello(door, far).json()["cursor"]
    near_visitor = _arrive(client, near, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    far_visitors = {
        _arrive(client, far, str(uuid.uuid4()), carried=[]).json()["thing_id"] for _ in range(2)
    }
    society = _step(client, world, society)
    bridges: list[_Bridge] = []

    def choose(frame: dict[str, Any]) -> dict[str, Any]:
        """Say the line to the other far visitor by the first label that says one, until taken."""
        taken = any(
            body.get("line") == STAYING_LINE and status == 202
            for body, status, _answer in bridges[0].answers
        )
        if frame["line_labels"] and not taken:
            return {"label": frame["line_labels"][0], "line": STAYING_LINE}
        return {"label": frame["idle_label"]}

    def said_far(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            f
            for f in _said(frames)
            if f["line"] == STAYING_LINE and f["speaker"]["id"] in far_visitors
        ]

    with (
        _Bridge(client, far, far_start, choose) as bridge,
        _Bridge(client, near, near_start, lambda frame: {"label": frame["idle_label"]}),
    ):
        bridges.append(bridge)
        for _ in range(12):
            society = _minute(door, host, world, society)
            if said_far(bridge.frames):
                break
            time.sleep(1.5)  # a poll held one second reads what the minute said
        else:
            raise AssertionError("the far visitors' line was not read in twelve minutes")
    crossed = {p["id"] for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"}
    assert crossed == {near_visitor, *far_visitors}
    assert said_far(_read_all(door, near, near_start)) == []
