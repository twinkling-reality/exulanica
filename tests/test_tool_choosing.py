"""The tool chooser: a listed tool and the description's own words, or none, decided by rule.

The model is scripted; what is held is what the step sends (only the description and the tools),
what it accepts, and how it repairs once and then answers none. Expected values are written here
by hand.
"""

from __future__ import annotations

import json
from typing import Any

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.tool_choosing import (
    CHOOSER_ROLE,
    choice_schema,
    choose_tool,
    chooser_prompt,
    render_request,
)
from exulanica.world.world_tools import WorldTool

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body

TOOLS = (
    WorldTool("place", "site-plan", 1, "kind", "Any other place.", "Streets with traffic.", True),
    WorldTool("town", "city-grammar-town", 2, "specification", "A town.", "One building.", False),
)
DESCRIPTION = "A castle with a keep, a courtyard and stables."


def _reply(value: Any) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(json.dumps(value))))


def _client(*responses: HttpResponse) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    return client, transport


def test_a_listed_tool_is_chosen_with_the_description_s_own_words():
    client, transport = _client(_reply({"tool": "place", "tool_words": ["A castle"]}))
    choice = choose_tool(client, DESCRIPTION, TOOLS)
    assert (choice.tool, choice.tool_words, choice.refused) == ("place", ("A castle",), None)
    # Where the words are in the description, counted by hand.
    assert choice.tool_words_at == ((0, 8),)
    assert transport.call_count == 1 and len(choice.calls) == 1


def test_the_step_asks_its_own_role_with_the_ceiling_the_role_declares():
    client, transport = _client(_reply({"tool": None, "tool_words": []}))
    choose_tool(client, DESCRIPTION, TOOLS)
    binding = load_manifest()[CHOOSER_ROLE]
    assert binding.max_tokens is not None
    [request] = transport.requests
    assert request["payload"]["model"] == binding.primary.model_id
    assert request["payload"]["max_tokens"] == binding.max_tokens.value


def test_the_chooser_sees_only_the_description_and_each_tool_s_own_words():
    client, transport = _client(_reply({"tool": None, "tool_words": []}))
    choose_tool(client, DESCRIPTION, TOOLS)
    [request] = transport.requests
    messages = request["payload"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == chooser_prompt().instructions
    assert messages[1]["content"] == "\n".join(
        [
            "The person's description:",
            "A castle with a keep, a courtyard and stables.",
            "",
            "The tools:",
            "- place: It can make: Any other place. It cannot make: Streets with traffic.",
            "- town: It can make: A town. It cannot make: One building.",
        ]
    )
    assert messages[1]["content"] == render_request(DESCRIPTION, TOOLS)


def test_the_answer_s_form_admits_only_a_listed_key_or_none():
    schema = choice_schema(TOOLS, chooser_prompt()).model_json_schema()
    assert list(schema["properties"]) == ["tool", "tool_words"]
    assert schema["additionalProperties"] is False
    listed = json.dumps(schema["properties"]["tool"])
    assert '"place"' in listed and '"town"' in listed


def test_none_is_an_answer_and_is_not_repaired():
    client, transport = _client(_reply({"tool": None, "tool_words": []}))
    choice = choose_tool(client, "Something nice.", TOOLS)
    assert (choice.tool, choice.tool_words, choice.refused) == (None, (), None)
    assert transport.call_count == 1


def test_words_not_in_the_description_are_repaired_once_and_named_in_the_repair():
    client, transport = _client(
        _reply({"tool": "place", "tool_words": ["a fortress"]}),
        _reply({"tool": "place", "tool_words": ["a keep"]}),
    )
    choice = choose_tool(client, DESCRIPTION, TOOLS)
    assert (choice.tool, choice.tool_words) == ("place", ("a keep",))
    assert transport.call_count == 2
    assert '"a fortress"' in transport.requests[1]["payload"]["messages"][-1]["content"]


def test_a_tool_without_words_words_without_a_tool_or_an_unlisted_tool_end_as_none():
    for first in (
        {"tool": "town", "tool_words": []},
        {"tool": None, "tool_words": ["A castle"]},
        {"tool": "island", "tool_words": ["A castle"]},
    ):
        client, transport = _client(_reply(first), _reply(first))
        choice = choose_tool(client, DESCRIPTION, TOOLS)
        assert choice.tool is None and choice.tool_words == () and choice.refused, first
        assert transport.call_count == 2


def test_no_tools_listed_asks_nothing():
    client, transport = _client()
    choice = choose_tool(client, DESCRIPTION, ())
    assert (choice.tool, choice.refused, transport.call_count) == (None, None, 0)
