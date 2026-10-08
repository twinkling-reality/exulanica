"""The look chooser: a listed look and the description's own words, or none, decided by rule.

The model is scripted; what is held is what the step sends (only the description and the looks),
what it accepts, and how it repairs once and then answers none. Expected values are written here
by hand.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.look_choosing import (
    CHOOSER_ROLE,
    LookOption,
    choose_look,
    chooser_prompt,
    render_request,
)

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body

OPTIONS = (
    LookOption("exulanica.cozy-town", "Cozy town", "Warm light, soft colours, lit windows."),
    LookOption("exulanica.toon-town", "Toon town", "Bright flat colours and inked edges."),
)
DESCRIPTION = "A cozy little market town in warm evening light."


def _reply(value: Any) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(json.dumps(value))))


def _client(
    *responses: HttpResponse, policy: RecordingPolicy | None = None
) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy() if policy is None else policy,
    )
    return client, transport


def test_a_listed_look_is_chosen_with_the_descriptions_own_words():
    client, transport = _client(
        _reply({"look": "exulanica.cozy-town", "look_words": ["cozy", "warm evening light"]})
    )
    choice = choose_look(client, DESCRIPTION, OPTIONS)
    assert (choice.look, choice.look_words, choice.refused) == (
        "exulanica.cozy-town",
        ("cozy", "warm evening light"),
        None,
    )
    assert choice.look_words_at == ((2, 6), (29, 47))
    assert transport.call_count == 1


def test_the_step_asks_its_own_role_with_the_ceiling_the_role_declares():
    client, transport = _client(_reply({"look": None, "look_words": []}))
    choose_look(client, DESCRIPTION, OPTIONS)
    binding = load_manifest()[CHOOSER_ROLE]
    assert binding.max_tokens is not None
    [request] = transport.requests
    assert request["payload"]["model"] == binding.primary.model_id
    assert request["payload"]["max_tokens"] == binding.max_tokens.value == 1024


def test_the_chooser_sees_only_the_description_and_the_looks():
    client, transport = _client(_reply({"look": None, "look_words": []}))
    choose_look(client, DESCRIPTION, OPTIONS)
    [request] = transport.requests
    messages = request["payload"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == chooser_prompt().instructions
    assert messages[1]["content"] == (
        "The person's description:\nA cozy little market town in warm evening light.\n\n"
        "The looks:\n"
        "- exulanica.cozy-town: Cozy town. Warm light, soft colours, lit windows.\n"
        "- exulanica.toon-town: Toon town. Bright flat colours and inked edges."
    )
    assert messages[1]["content"] == render_request(DESCRIPTION, OPTIONS)


def test_no_look_is_an_answer():
    client, _ = _client(_reply({"look": None, "look_words": []}))
    choice = choose_look(client, "A river town with two bridges.", OPTIONS)
    assert (choice.look, choice.look_words, choice.refused) == (None, (), None)


def test_words_not_in_the_description_are_repaired_once():
    client, transport = _client(
        _reply({"look": "exulanica.cozy-town", "look_words": ["snug"]}),
        _reply({"look": "exulanica.cozy-town", "look_words": ["cozy"]}),
    )
    choice = choose_look(client, DESCRIPTION, OPTIONS)
    assert (choice.look, choice.look_words) == ("exulanica.cozy-town", ("cozy",))
    assert transport.call_count == 2
    repair = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert '"snug"' in repair


def test_a_look_without_words_or_words_without_a_look_is_refused():
    for first in (
        {"look": "exulanica.toon-town", "look_words": []},
        {"look": None, "look_words": ["cozy"]},
    ):
        client, transport = _client(_reply(first), _reply(first))
        choice = choose_look(client, DESCRIPTION, OPTIONS)
        assert (choice.look, choice.look_words) == (None, ())
        assert choice.refused is not None and transport.call_count == 2


def test_a_look_that_is_not_listed_is_refused_by_the_form():
    unlisted = {"look": "exulanica.finished-town", "look_words": ["realistic"]}
    client, transport = _client(_reply(unlisted), _reply(unlisted))
    choice = choose_look(client, DESCRIPTION, OPTIONS)
    assert choice.look is None and choice.refused is not None
    assert transport.call_count == 2


def test_no_looks_means_no_call():
    client, transport = _client()
    choice = choose_look(client, DESCRIPTION, ())
    assert (choice.look, transport.call_count) == (None, 0)


def test_the_placeholders_the_description_was_sent_with_reach_the_boundary():
    """The description arrives with its saved names already replaced; the boundary is handed the
    same replacements, so a name it withholds is written as the placeholder already given."""
    placeholders = {uuid.uuid4(): "[place A]"}
    policy = RecordingPolicy()
    client, _ = _client(
        _reply({"look": "exulanica.cozy-town", "look_words": ["cozy town like [place A]"]}),
        policy=policy,
    )
    sent = "A cozy town like [place A] in warm evening light."
    choice = choose_look(client, sent, OPTIONS, placeholders=placeholders)
    assert choice.look_words == ("cozy town like [place A]",)
    assert dict(policy.requests[0].placeholders) == placeholders
