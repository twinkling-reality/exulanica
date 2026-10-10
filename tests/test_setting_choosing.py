"""The setting chooser: a listed part for each axis and the description's own words, or none,
decided by rule.

The model is scripted; what is held is what the step sends (only the description and the parts),
what it accepts, and how it repairs once and then answers none. Expected values are written here
by hand.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.setting_choosing import (
    CHOOSER_ROLE,
    SettingAxis,
    SettingOption,
    choice_schema,
    choose_setting,
    chooser_prompt,
    render_request,
)

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body

AXES = (SettingAxis("sky", "Hour and sky"), SettingAxis("ground", "Ground and beyond"))
OPTIONS = (
    SettingOption("sky", "dusk", "Dusk", "Evening: a low orange sun."),
    SettingOption("sky", "night", "Night", "Night under a moon."),
    SettingOption("ground", "sea", "By the sea", "Open sea beyond the last street."),
)
DESCRIPTION = "A harbour town by the sea at dusk."


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


def test_a_part_is_chosen_for_each_axis_the_words_speak_of_with_the_descriptions_own_words():
    client, transport = _client(
        _reply({"sky": "dusk", "ground": "sea", "words": ["at dusk", "by the sea"]})
    )
    choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS)
    assert (dict(choice.parts), choice.words, choice.refused) == (
        {"sky": "dusk", "ground": "sea"},
        ("at dusk", "by the sea"),
        None,
    )
    # Where the words are in the description, counted by hand.
    assert choice.words_at == ((26, 33), (15, 25))
    assert list(choice.parts) == ["sky", "ground"]
    assert transport.call_count == 1


def test_an_axis_the_words_do_not_speak_of_is_left_out():
    client, _ = _client(_reply({"sky": None, "ground": "sea", "words": ["by the sea"]}))
    choice = choose_setting(client, "A town by the sea.", AXES, OPTIONS)
    assert dict(choice.parts) == {"ground": "sea"}


def test_the_step_asks_its_own_role_with_the_ceiling_the_role_declares():
    client, transport = _client(_reply({"sky": None, "ground": None, "words": []}))
    choose_setting(client, DESCRIPTION, AXES, OPTIONS)
    binding = load_manifest()[CHOOSER_ROLE]
    assert binding.max_tokens is not None
    [request] = transport.requests
    assert request["payload"]["model"] == binding.primary.model_id
    assert request["payload"]["max_tokens"] == binding.max_tokens.value == 1024


def test_the_chooser_sees_only_the_description_and_the_parts():
    client, transport = _client(_reply({"sky": None, "ground": None, "words": []}))
    choose_setting(client, DESCRIPTION, AXES, OPTIONS)
    [request] = transport.requests
    messages = request["payload"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == chooser_prompt().instructions
    assert messages[1]["content"] == (
        "The person's description:\nA harbour town by the sea at dusk.\n\n"
        "The parts of a setting, by axis:\n"
        "sky (Hour and sky):\n"
        "- dusk: Dusk. Evening: a low orange sun.\n"
        "- night: Night. Night under a moon.\n\n"
        "ground (Ground and beyond):\n"
        "- sea: By the sea. Open sea beyond the last street."
    )
    assert messages[1]["content"] == render_request(DESCRIPTION, AXES, OPTIONS)


def test_the_answers_form_states_each_axis_then_the_words_last():
    schema = choice_schema(AXES, OPTIONS, chooser_prompt()).model_json_schema()
    assert list(schema["properties"]) == ["sky", "ground", "words"]
    assert schema["additionalProperties"] is False
    with pytest.raises(ValueError, match="words"):
        choice_schema((SettingAxis("words", "Words"),), OPTIONS, chooser_prompt())


def test_no_setting_is_an_answer():
    client, _ = _client(_reply({"sky": None, "ground": None, "words": []}))
    choice = choose_setting(client, "A town with two cafes.", AXES, OPTIONS)
    assert (dict(choice.parts), choice.words, choice.refused) == ({}, (), None)


def test_words_not_in_the_description_are_repaired_once():
    client, transport = _client(
        _reply({"sky": "dusk", "ground": None, "words": ["sunset"]}),
        _reply({"sky": "dusk", "ground": None, "words": ["at dusk"]}),
    )
    choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS)
    assert (dict(choice.parts), choice.words) == ({"sky": "dusk"}, ("at dusk",))
    assert transport.call_count == 2
    repair = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert '"sunset"' in repair


def test_a_part_without_words_or_words_without_a_part_is_refused():
    for first in (
        {"sky": "night", "ground": None, "words": []},
        {"sky": None, "ground": None, "words": ["at dusk"]},
    ):
        client, transport = _client(_reply(first), _reply(first))
        choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS)
        assert (dict(choice.parts), choice.words) == ({}, ())
        assert choice.refused is not None and transport.call_count == 2


def test_a_part_that_is_not_listed_or_is_another_axiss_is_refused_by_the_form():
    for unlisted in (
        {"sky": "aurora", "ground": None, "words": ["at dusk"]},
        {"sky": "sea", "ground": None, "words": ["by the sea"]},
    ):
        client, transport = _client(_reply(unlisted), _reply(unlisted))
        choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS)
        assert dict(choice.parts) == {} and choice.refused is not None
        assert transport.call_count == 2


def test_no_parts_means_no_call():
    client, transport = _client()
    choice = choose_setting(client, DESCRIPTION, AXES, ())
    assert (dict(choice.parts), transport.call_count) == ({}, 0)


def test_the_placeholders_the_description_was_sent_with_reach_the_boundary():
    """The description arrives with its saved names already replaced; the boundary is handed the
    same replacements, so a name it withholds is written as the placeholder already given."""
    placeholders = {uuid.uuid4(): "[place A]"}
    policy = RecordingPolicy()
    client, _ = _client(
        _reply({"sky": "dusk", "ground": None, "words": ["dusk near [place A]"]}),
        policy=policy,
    )
    sent = "A town at dusk near [place A]."
    choice = choose_setting(client, sent, AXES, OPTIONS, placeholders=placeholders)
    assert choice.words == ("dusk near [place A]",)
    assert dict(policy.requests[0].placeholders) == placeholders


class _Timed(FakeTransport):
    """A scripted transport that keeps how long each request was given."""

    def __init__(self, responses: list[HttpResponse]) -> None:
        super().__init__(responses)
        self.timeouts: list[float] = []

    def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
        self.timeouts.append(timeout)
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def _ticks(*seconds: float):
    readings = iter(seconds)
    return lambda: next(readings)


def test_the_call_and_its_repair_share_one_deadline_the_roles_timeout():
    timeout = load_manifest()[CHOOSER_ROLE].timeout_seconds
    assert timeout == 15
    transport = _Timed(
        [
            _reply({"sky": "dusk", "ground": None, "words": ["sunset"]}),
            _reply({"sky": "dusk", "ground": None, "words": ["at dusk"]}),
        ]
    )
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    # The deadline is set at 0; the first call is sent at 0 and the repair at 11 s.
    choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS, clock=_ticks(0.0, 0.0, 11.0))
    assert dict(choice.parts) == {"sky": "dusk"}
    first, repair = transport.timeouts
    assert 14.5 < first <= 15
    assert 3.5 < repair <= 4


def test_no_repair_is_asked_once_the_deadline_has_passed():
    transport = _Timed([_reply({"sky": "dusk", "ground": None, "words": ["sunset"]})])
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    choice = choose_setting(client, DESCRIPTION, AXES, OPTIONS, clock=_ticks(0.0, 0.0, 15.5))
    assert (dict(choice.parts), choice.words) == ({}, ())
    assert choice.refused is not None and "no time was left" in choice.refused
    assert transport.call_count == 1
