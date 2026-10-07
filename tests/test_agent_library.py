"""The outside-agent library in ``bridges/agents``: standalone, faithful to the door, careful with
its key.

The library gives any AI agent a body in a world through the door's channel. What it must do: hand
a mind exactly what one of the world's own models is shown, send back one offered action as the
door contract states an answer, and report what became of it. What it must not do matters as much:
need anything beyond the standard library, send the agent's key anywhere but the world it was given,
or show the key in any message. Expected values come from the door contract's shapes, the product's
own person role, choice function and model manifest, and the packaged mapping file read directly,
never from the library under test.
"""

from __future__ import annotations

import ast
import http.server
import json
import runpy
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator

import pytest
from exulanica.models.choice import ChoiceRequest
from exulanica.world.deciders import ADAPTER_VERSION

from agent_support import (
    AGENTS_ROOT,
    GRANT_ID,
    KEY,
    PACKAGE,
    AgentError,
    Body,
    Door,
    DoorRefusal,
    FakeDoor,
    person_ask,
    served,
    with_a_line,
)

MAPPING_FILE = PACKAGE / "outside-agents.v1.json"
QUICKSTART = AGENTS_ROOT / "examples" / "quickstart.py"


def until(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def door() -> FakeDoor:
    return FakeDoor()


@pytest.fixture
def body(door: FakeDoor) -> Iterator[Body]:
    connected = Body.connect(
        "http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=door.opener
    )
    try:
        yield connected
    finally:
        connected.close(wait_seconds=5)


# -- what the library is made of -------------------------------------------------------------------


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_library_imports_only_the_standard_library_and_itself():
    allowed = set(sys.stdlib_module_names) | {"exulanica_agent"}
    sources = sorted(PACKAGE.glob("*.py"))
    assert len(sources) >= 8, sources
    outside = {}
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        found = _imports(tree)
        if source.name == "mcp_server.py":
            # The MCP facade loads the MCP SDK inside the functions that serve, so importing the
            # package never needs it; at module level it imports what every other module may.
            top = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
            found = _imports(ast.Module(body=top, type_ignores=[]))
        if found - allowed:
            outside[source.name] = sorted(found - allowed)
    assert outside == {}, f"imports outside the standard library: {outside}"


def test_the_library_runs_with_no_site_packages():
    run = subprocess.run(
        [
            sys.executable,
            "-S",
            "-s",
            "-E",
            "-c",
            "import exulanica_agent; print(exulanica_agent.VERSION); "
            "print(exulanica_agent.mapping()['key'])",
        ],
        cwd=AGENTS_ROOT,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    version, key = run.stdout.split()
    assert ADAPTER_VERSION.fullmatch(version)
    assert key == json.loads(MAPPING_FILE.read_text())["key"]


# -- hello ---------------------------------------------------------------------------------------


def test_hello_presents_the_adapter_its_mapping_and_what_the_agent_declares(door, body):
    hello = door.requests[0]
    assert (hello["method"], hello["path"], hello["keyed"]) == (
        "POST",
        "/door/channel/hello",
        True,
    )
    sent = hello["body"]
    assert set(sent) == {"adapter_version", "mapping", "reads", "declared"}
    assert ADAPTER_VERSION.fullmatch(sent["adapter_version"])
    packaged = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    assert sent["mapping"] == packaged
    # The door refuses an adapter that reads a field its mapping does not account for.
    accounted = (
        {visitor["game_type"] for visitor in packaged["visitors"]}
        | {item["game_item"] for item in packaged["items"]}
        | {action["game_action"] for action in packaged["actions"]}
        | {entry["field"] for entry in packaged["never_crosses"]}
    )
    assert set(sent["reads"]) <= accounted
    assert sent["declared"] == {"name": "Scout", "maker": "Acme"}
    assert body.permission == {
        "things": ["person-4"],
        "visitors_maximum": 0,
        "may_speak": True,
        "ends_at": "2026-10-07T02:00:00.000000+00:00",
        "ended": None,
    }


def test_the_poll_reads_frames_after_the_cursor_the_door_returned(door, body):
    assert until(lambda: len(door.requests_to("/door/channel/frames")) >= 2)
    polls = door.requests_to("/door/channel/frames")
    assert polls[0]["query"] == {"after": "c0"}
    assert all(poll["method"] == "GET" and poll["keyed"] for poll in polls)


@pytest.mark.parametrize(
    ("status", "code", "words"),
    [
        (401, "unauthenticated", "does not accept this agent key"),
        (422, "mapping_not_admitted", "update exulanica-agent"),
        (422, "adapter_version_not_admitted", "does not admit this version"),
        (422, "declared_refused", "a declared maker holds no host name"),
        (409, "grant_ended", "has ended"),
    ],
)
def test_a_refused_hello_says_what_to_do(door, status, code, words):
    door.refuse("/door/channel/hello", status, code, detail="a declared maker holds no host name")
    with pytest.raises(AgentError) as refused:
        Body.connect("http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=door.opener)
    assert words in str(refused.value)
    assert KEY not in str(refused.value)


def test_a_body_needs_a_name_and_a_maker_for_its_card(door):
    with pytest.raises(AgentError, match="name and a maker"):
        Body.connect("http://127.0.0.1:9", KEY, name="Scout", opener=door.opener)
    assert door.requests == []


# -- turns ---------------------------------------------------------------------------------------


def test_a_turn_hands_a_mind_exactly_what_a_model_receives(door, body):
    frame = person_ask()
    door.push(frame)
    turn = body.next_turn(5)
    assert turn is not None
    assert turn.messages == frame["messages"]
    assert turn.tool == frame["act"]
    labels = [option["label"] for option in frame["context"]["options"]]
    assert turn.tool_choice == ChoiceRequest(frame["choice_description"], labels).tool_choice()
    assert [option.action for option in turn.options] == labels
    assert not any(option.says_line for option in turn.options)
    assert (turn.thing, turn.minute, turn.turn) == ("person-4", 41, frame["request_id"])
    assert 0 < turn.seconds_left <= 14.0


def test_an_answer_names_its_turn_and_one_offered_action(door, body):
    frame = person_ask()
    door.push(frame)
    turn = body.next_turn(5)
    answer = turn.act("wait a minute")
    assert answer.received, answer
    [sent] = door.requests_to("/door/channel/answers")
    assert sent["keyed"] and sent["method"] == "POST"
    assert sent["body"] == {
        "request_id": frame["request_id"],
        "request_sha256": frame["request_sha256"],
        "label": "wait a minute",
    }
    # An answered turn is not handed out again.
    assert body.next_turn(0) is None


def test_a_line_goes_with_an_action_that_says_one(door, body):
    says = "say something to everyone near you"
    frame = with_a_line(person_ask(), says, maximum=40)
    door.push(frame)
    turn = body.next_turn(5)
    assert [option.says_line for option in turn.options] == [False, False, False, True]
    assert turn.act(says).refusal == "line_missing"
    assert turn.act("wait a minute", "hello").refusal == "line_not_offered"
    assert turn.act(says, "x" * 41).refusal == "line_out_of_bounds"
    assert door.requests_to("/door/channel/answers") == []
    assert turn.act(says, "Hello, is the well water safe?").received
    [sent] = door.requests_to("/door/channel/answers")
    assert sent["body"]["label"] == says
    assert sent["body"]["line"] == "Hello, is the well water safe?"


def test_an_action_not_offered_is_refused_before_anything_is_sent(door, body):
    door.push(person_ask())
    turn = body.next_turn(5)
    answer = turn.act("fly away")
    assert (answer.received, answer.refusal) == (False, "answer_not_offered")
    assert "go to the bench; wait a minute; stand where you are" in answer.words
    assert door.requests_to("/door/channel/answers") == []


def test_a_door_refusal_of_an_answer_comes_back_in_words(door, body):
    frame = person_ask()
    door.push(frame)
    turn = body.next_turn(5)
    door.refuse("/door/channel/answers", 409, "answer_too_late")
    answer = turn.act("wait a minute")
    assert (answer.received, answer.refusal) == (False, "answer_too_late")
    assert "routine" in answer.words
    assert body.turn(frame["request_id"]) is None


def test_an_ask_from_a_door_without_the_models_packet_is_named_not_guessed(door, body):
    frame = person_ask()
    del frame["messages"], frame["act"]
    door.push(frame)
    assert until(lambda: any(h.what == "turn_unreadable" for h in body.recent()))
    assert body.next_turn(0) is None
    [unreadable] = [h for h in body.recent() if h.what == "turn_unreadable"]
    assert "older than the agent library needs" in unreadable.words


# -- what happened -------------------------------------------------------------------------------


def _outcome(frame: dict, status: str, reason: str) -> dict:
    return {
        "kind": "outcome",
        "ask_seq": frame["ask_seq"],
        "request_id": frame["request_id"],
        "status": status,
        "reason": reason,
    }


def test_what_became_of_each_turn_reads_as_words(door, body):
    answered, missed = person_ask(minute=41, ask_seq=1), person_ask(minute=42, ask_seq=2)
    door.push(answered, missed)
    assert until(lambda: body.waiting() == 2)
    body.turn(answered["request_id"]).act("go to the bench")
    door.push(
        _outcome(answered, "accepted", "validated_choice"),
        _outcome(missed, "unavailable", "no_answer_in_time"),
    )
    assert until(lambda: len([h for h in body.recent() if h.what.startswith("answer")]) == 2)
    taken, not_taken = [h for h in body.happened() if h.what.startswith("answer")]
    assert (taken.what, taken.minute, taken.thing) == ("answer_taken", 41, "person-4")
    assert "go to the bench" in taken.words
    assert (not_taken.what, not_taken.minute, not_taken.reason) == (
        "answer_not_taken",
        42,
        "no_answer_in_time",
    )
    assert "routine" in not_taken.words
    assert body.happened() == []


def test_an_outcome_before_the_answers_reply_still_names_the_answer(door, body):
    frame = person_ask()
    door.push(frame)
    turn = body.next_turn(5)

    def recorded_at_once(_sent: object) -> None:
        door.push(_outcome(frame, "accepted", "validated_choice"))
        assert until(lambda: any(h.what.startswith("answer") for h in body.recent()))

    door.on_answer = recorded_at_once
    assert turn.act("wait a minute").received
    [taken] = [h for h in body.recent() if h.what.startswith("answer")]
    assert taken.what == "answer_taken" and "wait a minute" in taken.words


def test_turns_end_when_the_owner_ends_the_permission(door, body):
    door.push({"kind": "grant_ended", "grant_id": GRANT_ID, "grant_seq": 1, "reason": "revoked"})
    assert until(door.delivered)
    door.refuse("/door/channel/frames", 410, "grant_ended")
    assert list(body.turns()) == []
    assert body.ended == "revoked"
    assert body.permission["ended"] == "revoked"
    ended = [h for h in body.recent() if h.what == "permission_ended"]
    assert ended and "owner ended it" in ended[0].words


def test_the_body_says_hello_again_when_the_door_asks_for_it(door, body):
    door.refuse("/door/channel/frames", 409, "hello_first")
    assert until(lambda: len(door.requests_to("/door/channel/hello")) == 2)
    assert until(lambda: len(door.requests_to("/door/channel/frames")) >= 3)


def test_a_key_the_door_stops_accepting_ends_the_body(door, body):
    door.refuse("/door/channel/frames", 401, "unauthenticated")
    assert until(lambda: body.ended is not None)
    assert body.ended == "unauthenticated"


# -- the key ---------------------------------------------------------------------------------------


def test_the_key_appears_in_no_message(door, body):
    door.push(person_ask())
    turn = body.next_turn(5)
    texts = [repr(body), repr(turn), body.rules(), repr(Door("https://world.example", KEY))]
    texts += [h.words for h in body.recent()]
    try:
        Door("http://127.0.0.1:9", KEY, opener=_unreachable).call("GET", "/door/channel/frames")
    except AgentError as error:
        texts.append(str(error))
    door.refuse("/door/channel/answers", 404, "unknown_reference")
    texts.append(turn.act("wait a minute").words)
    assert all(KEY not in text for text in texts), texts


def _unreachable(_request: urllib.request.Request, _timeout: float) -> None:
    raise urllib.error.URLError(ConnectionRefusedError("refused"))


@pytest.mark.parametrize(
    "url",
    ["http://world.example", "ftp://127.0.0.1", "https://user:pass@world.example", "world.example"],
)
def test_the_key_goes_only_to_an_encrypted_or_local_address(url):
    with pytest.raises(AgentError):
        Door(url, KEY)


def test_a_redirect_is_never_followed_with_the_key():
    heard: list[str | None] = []

    class Redirecting(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            heard.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/x")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        door = Door(f"http://127.0.0.1:{server.server_address[1]}", KEY)
        with pytest.raises(AgentError, match="redirect"):
            door.call("GET", "/door/channel/frames")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert len(heard) == 1, "the redirect's target was asked"


def test_a_door_refusal_keeps_the_doors_own_code_and_wait():
    door = FakeDoor()
    door.refuse("/door/channel/frames", 503, "door_busy", retry_after_ms=1000)
    with pytest.raises(DoorRefusal) as refused:
        Door("http://127.0.0.1:9", KEY, opener=door.opener).call("GET", "/door/channel/frames")
    assert (refused.value.status, refused.value.code, refused.value.retry_after_s) == (
        503,
        "door_busy",
        1.0,
    )


# -- the quickstart --------------------------------------------------------------------------------


def test_the_quickstart_answers_a_turn_with_its_minds_choice(monkeypatch):
    from exulanica.models.manifest import load_manifest

    manifest = load_manifest()
    source = QUICKSTART.read_text(encoding="utf-8")
    model = next(line.split('"')[1] for line in source.splitlines() if line.startswith("MODEL = "))
    nemotron = next(
        line.split('"')[1] for line in source.splitlines() if line.startswith("# MODEL = ")
    )
    # Both minds the quickstart names are ones the product's probe verified to answer this choice
    # by a tool call, on Nebius Token Factory.
    for mind in (model, nemotron):
        spec = manifest.models[mind]
        assert spec.provider == "nebius_token_factory"
        assert "tool_call" in {mechanism.value for mechanism in spec.answering}
    asked_mind: list[dict] = []

    class Reply:
        def __init__(self, document: dict) -> None:
            self._data = json.dumps(document).encode()

        def read(self, *_size: int) -> bytes:
            return self._data

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def mind(request: urllib.request.Request, timeout: float) -> Reply:
        asked_mind.append(
            {
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data),
                "timeout": timeout,
            }
        )
        call = {"function": {"name": "act", "arguments": json.dumps({"action": "go to the bench"})}}
        return Reply({"choices": [{"message": {"tool_calls": [call]}}]})

    door = FakeDoor()
    frame = person_ask()
    door.push(frame)
    with served(door) as url:
        monkeypatch.setenv("EXULANICA_URL", url)
        monkeypatch.setenv("EXULANICA_AGENT_KEY", KEY)
        monkeypatch.setenv("NEBIUS_API_KEY", "test-mind-key")
        monkeypatch.setattr(urllib.request, "urlopen", mind)
        run = threading.Thread(target=runpy.run_path, args=(str(QUICKSTART),), daemon=True)
        run.start()
        assert until(lambda: door.requests_to("/door/channel/answers"), 15)
        door.push(
            {"kind": "grant_ended", "grant_id": GRANT_ID, "grant_seq": 1, "reason": "expired"}
        )
        assert until(door.delivered)
        door.refuse("/door/channel/frames", 410, "grant_ended")
        run.join(15)
        assert not run.is_alive(), "the quickstart did not stop when its permission ended"
    [sent] = door.requests_to("/door/channel/answers")
    assert sent["body"]["label"] == "go to the bench"
    [asked] = asked_mind
    assert asked["url"] == manifest.providers["nebius_token_factory"].base_url + "/chat/completions"
    assert asked["authorization"] == "Bearer test-mind-key"
    assert asked["body"]["model"] == model
    assert asked["body"]["messages"] == frame["messages"]
    assert asked["body"]["tools"] == [frame["act"]]
    assert asked["body"]["tool_choice"] == {"type": "function", "function": {"name": "act"}}
    hello = door.requests_to("/door/channel/hello")[0]["body"]
    assert hello["declared"] == {"name": "Scout", "maker": "Your name", "mind": model}
