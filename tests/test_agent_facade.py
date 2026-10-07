"""The MCP facade's tools, as data and as behaviour, without the MCP library.

What an agent's MCP client is offered is fixed: five tools in one order, four resources and one
prompt, the same whoever asks (MCP 2026-07-28: a tool list never varies per connection). Each
tool's structured answer is held to the output schema the client is shown, with an independent
JSON Schema validator, and each failure a mind can put right comes back as an error result in
words. The expected names and order are the design root approved (deliveries/AGENTS/design.md,
section 4.3), and the turns are built from the product's own person role.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator

import jsonschema
import pytest
from exulanica.world.roles.person import person_role

from agent_support import (
    GRANT_ID,
    KEY,
    PACKAGE,
    Body,
    FakeDoor,
    facade,
    grant_view,
    person_ask,
)

#: MCP 2026-07-28's tool name rule: 1 to 128 of letters, digits, underscore, hyphen and dot.
TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")


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
def tools(door: FakeDoor) -> Iterator[facade.Facade]:
    body = Body.connect("http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=door.opener)
    try:
        yield facade.Facade(body)
    finally:
        door.release()
        body.close(wait_seconds=5)


def _valid(name: str, structured: object) -> None:
    spec = next(tool for tool in facade.TOOLS if tool.name == name)
    jsonschema.Draft202012Validator(dict(spec.output_schema)).validate(structured)


# -- what a client is offered ----------------------------------------------------------------------


def test_the_tool_list_is_fixed_and_in_one_order():
    assert [tool.name for tool in facade.TOOLS] == [
        "wait_for_turn",
        "act",
        "what_happened",
        "enter_world",
        "world_rules",
    ]
    for tool in facade.TOOLS:
        assert TOOL_NAME.fullmatch(tool.name)
        for schema in (tool.input_schema, tool.output_schema):
            jsonschema.Draft202012Validator.check_schema(dict(schema))
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
        assert tool.description and tool.title
    hints = {tool.name: (tool.read_only, tool.open_world) for tool in facade.TOOLS}
    assert hints["act"] == (False, True)
    assert hints["wait_for_turn"] == (True, False)


def test_the_resources_and_prompt_are_fixed():
    assert [resource.uri for resource in facade.RESOURCES] == [
        "exulanica://agent/rules",
        "exulanica://agent/turn",
        "exulanica://agent/happened",
        "exulanica://agent/permission",
    ]
    assert facade.PROMPT["name"] == "live_in_this_world"
    assert facade.Facade.prompt("live_in_this_world", "Scout").startswith("You are Scout")
    with pytest.raises(LookupError):
        facade.Facade.prompt("something_else", "Scout")


def test_an_unknown_tool_is_a_protocol_error_not_a_tools_failure(tools):
    with pytest.raises(facade.UnknownTool):
        tools.call("teleport", {})


@pytest.mark.parametrize(
    ("name", "arguments", "words"),
    [
        ("wait_for_turn", {"wait_seconds": 51}, "from 0 to 50"),
        ("wait_for_turn", {"seconds": 5}, "takes no seconds"),
        ("act", {"action": "wait a minute"}, "needs turn"),
        ("act", {"turn": "x", "action": 3}, "text"),
        ("world_rules", {"verbose": True}, "takes no verbose"),
    ],
)
def test_a_malformed_call_is_refused_in_words_before_anything_is_sent(
    door, tools, name, arguments, words
):
    sent = len(door.requests)
    result = tools.call(name, arguments)
    assert result.is_error and words in result.text
    assert [r for r in door.requests[sent:] if r["path"] != "/door/channel/frames"] == []


# -- the tools -------------------------------------------------------------------------------------


def test_wait_for_turn_hands_over_the_situation_a_model_reads(door, tools):
    frame = person_ask()
    door.push(frame)
    result = tools.call("wait_for_turn", {"wait_seconds": 5})
    assert not result.is_error
    _valid("wait_for_turn", result.structured)
    turn = result.structured["turn"]
    situation = next(m["content"] for m in frame["messages"] if m["role"] == "user")
    assert turn["situation"] == situation
    assert turn["instruction"] == person_role().instruction
    assert turn["turn"] == frame["request_id"]
    assert [option["action"] for option in turn["options"]] == [
        option["label"] for option in frame["context"]["options"]
    ]
    assert situation in result.text and frame["request_id"] in result.text
    assert result.structured["permission"]["things"] == ["person-4"]


def test_wait_for_turn_with_nothing_to_do_says_so(tools):
    result = tools.call("wait_for_turn", {"wait_seconds": 0})
    _valid("wait_for_turn", result.structured)
    assert result.structured["turn"] is None
    assert "No turn yet" in result.text


def test_a_second_wait_while_one_waits_answers_at_once(door, tools):
    first: dict = {}
    waiting = threading.Thread(
        target=lambda: first.update(result=tools.call("wait_for_turn", {"wait_seconds": 2}))
    )
    waiting.start()
    time.sleep(0.2)
    started = time.monotonic()
    second = tools.call("wait_for_turn", {"wait_seconds": 20})
    assert time.monotonic() - started < 1.0
    assert second.structured["turn"] is None
    waiting.join(5)


def test_act_answers_the_turn_it_names(door, tools):
    frame = person_ask()
    door.push(frame)
    handle = tools.call("wait_for_turn", {"wait_seconds": 5}).structured["turn"]["turn"]
    result = tools.call("act", {"turn": handle, "action": "stand where you are"})
    assert not result.is_error, result.text
    _valid("act", result.structured)
    [sent] = door.requests_to("/door/channel/answers")
    assert sent["body"]["label"] == "stand where you are"
    assert sent["body"]["request_id"] == frame["request_id"]


def test_act_refusals_say_how_to_put_them_right(door, tools):
    frame = person_ask()
    door.push(frame)
    handle = tools.call("wait_for_turn", {"wait_seconds": 5}).structured["turn"]["turn"]
    not_offered = tools.call("act", {"turn": handle, "action": "fly away"})
    assert not_offered.is_error and "go to the bench" in not_offered.text
    unknown = tools.call("act", {"turn": "no-such-turn", "action": "wait a minute"})
    assert unknown.is_error and "wait_for_turn" in unknown.text
    door.refuse("/door/channel/answers", 409, "answer_too_late")
    late = tools.call("act", {"turn": handle, "action": "wait a minute"})
    assert late.is_error and "routine" in late.text


def test_after_an_answer_act_sends_the_agent_to_its_next_turn(door, tools):
    door.push(person_ask())
    handle = tools.call("wait_for_turn", {"wait_seconds": 5}).structured["turn"]["turn"]
    first = tools.call("act", {"turn": handle, "action": "wait a minute"})
    assert not first.is_error and "call wait_for_turn" in first.text
    second = tools.call("act", {"turn": handle, "action": "go to the bench"})
    assert second.is_error and "wait_for_turn" in second.text
    assert len(door.requests_to("/door/channel/answers")) == 1


def test_what_happened_reports_each_turns_outcome_once(door, tools):
    frame = person_ask()
    door.push(frame)
    handle = tools.call("wait_for_turn", {"wait_seconds": 5}).structured["turn"]["turn"]
    tools.call("act", {"turn": handle, "action": "go to the bench"})
    door.push(
        {
            "kind": "outcome",
            "ask_seq": frame["ask_seq"],
            "request_id": frame["request_id"],
            "status": "accepted",
            "reason": "validated_choice",
        }
    )
    assert until(lambda: any(h.what == "answer_taken" for h in tools.body.recent()))
    result = tools.call("what_happened", {})
    _valid("what_happened", result.structured)
    [taken] = [h for h in result.structured["happened"] if h["what"] == "answer_taken"]
    assert taken["minute"] == 41 and "go to the bench" in taken["words"]
    assert tools.call("what_happened", {}).structured["happened"] == []


def test_world_rules_carry_the_worlds_own_instruction_and_the_turns_time(door, tools):
    door.push(person_ask(deadline_ms=15_000))
    tools.call("wait_for_turn", {"wait_seconds": 5})
    result = tools.call("world_rules", {})
    _valid("world_rules", result.structured)
    rules = result.structured["rules"]
    assert person_role().instruction in rules
    assert "15 seconds" in rules
    assert "until 2026-10-07T02:00:00.000000+00:00" in rules
    assert "Nothing you send is run" in rules


def test_enter_world_is_offered_only_when_the_grant_allows_a_body_of_its_own(door, tools):
    # A grant to decide for things only: no tool a mind would be refused, so none is listed.
    assert [tool.name for tool in tools.tools] == [
        "wait_for_turn",
        "act",
        "what_happened",
        "world_rules",
    ]
    with pytest.raises(facade.UnknownTool):
        tools.call("enter_world", {})
    assert door.requests_to("/door/channel/arrivals") == []
    visitor = FakeDoor(grant=grant_view(visitors=1))
    body = Body.connect(
        "http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=visitor.opener
    )
    try:
        assert [tool.name for tool in facade.Facade(body).tools] == [
            tool.name for tool in facade.TOOLS
        ]
    finally:
        visitor.release()
        body.close(wait_seconds=5)


def test_enter_world_asks_the_door_to_let_the_agents_body_in():
    door = FakeDoor(grant=grant_view(visitors=1))
    body = Body.connect("http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=door.opener)
    try:
        tools = facade.Facade(body)
        result = tools.call("enter_world", {})
        assert not result.is_error, result.text
        _valid("enter_world", result.structured)
        [arrival] = door.requests_to("/door/channel/arrivals")
        mapping = json.loads((PACKAGE / "outside-agents.v1.json").read_text(encoding="utf-8"))
        visitor = mapping["visitors"][0]
        assert set(arrival["body"]) == {"arrival_id", "game_type", "look_key", "carried"}
        assert arrival["body"]["game_type"] == visitor["game_type"]
        assert arrival["body"]["look_key"] == visitor["looks"][0]["look_key"]
        assert arrival["body"]["carried"] == []
        again = tools.call("enter_world", {})
        assert again.is_error and "already on its way" in again.text
        door2 = FakeDoor(grant=grant_view(visitors=1))
        door2.refusals["/door/channel/arrivals"] = [(404, {"detail": "Not Found"})]
        other = Body.connect(
            "http://127.0.0.1:9", KEY, name="Scout", maker="Acme", opener=door2.opener
        )
        try:
            refused = facade.Facade(other).call("enter_world", {})
            assert refused.is_error and "does not take visitors yet" in refused.text
        finally:
            door2.release()
            other.close(wait_seconds=5)
    finally:
        door.release()
        body.close(wait_seconds=5)


def test_the_resources_mirror_the_tools(door, tools):
    door.push(person_ask())
    assert until(lambda: tools.body.waiting() == 1)
    kind, rules = tools.read("exulanica://agent/rules")
    assert kind == "text/markdown" and "How turns work" in rules
    kind, turn = tools.read("exulanica://agent/turn")
    assert kind == "application/json" and json.loads(turn)["thing"] == "person-4"
    kind, permission = tools.read("exulanica://agent/permission")
    assert json.loads(permission)["may_speak"] is True
    with pytest.raises(LookupError):
        tools.read("exulanica://agent/secrets")


def test_after_the_permission_ends_no_turn_comes(door, tools):
    door.push({"kind": "grant_ended", "grant_id": GRANT_ID, "grant_seq": 1, "reason": "expired"})
    assert until(lambda: tools.body.ended is not None)
    result = tools.call("wait_for_turn", {"wait_seconds": 1})
    assert result.structured["turn"] is None
    assert result.structured["permission"]["ended"] == "expired"
    assert "has ended" in result.text
