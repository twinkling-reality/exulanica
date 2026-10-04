"""The Companion's drafters against a reply that runs on, with a scripted model and no database.

Measured on the live endpoint, a world-edit draft that ran to its token limit was the form
written correctly as far as a list naming something, then a line break where the comma belonged,
then whitespace to the limit: at that point the strict schema admits only a comma or whitespace.
The fixtures here have that shape. What is held: the form never lets a list be followed by a field,
a reply that runs on ends at the drafter's own ceiling rather than the role's, the repair says how
it ran on, and a cut reply is classified only when it plainly is one shape.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import TruncatedResponseError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.response import (
    RUNAWAY_REPEATS,
    RUNAWAY_WHITESPACE_CHARS,
    Runaway,
    runaway_shape,
)
from exulanica.models.schema import response_format_for
from exulanica.models.transport import HttpResponse
from exulanica.selection import action_plan as plan
from exulanica.selection.calls import CallLog

from form_shapes import arrays_followed_by_a_property
from model_fakes import RecordingPolicy, chat_body

EXTRACTOR = load_manifest()[Role.STRUCTURED_EXTRACTION].primary.model_id

#: The opening of a measured runaway: the form written indented, correct as far as a list that
#: names something, then a line break where the comma belonged.
_WHITESPACE_OPENING = (
    '{\n  "steps": [\n    {\n      "operation": "place_object",\n      "options": ["cc0.bench"]'
)
_REPEATING_OPENING = '{"steps":[{"operation":"place_object","options":["cc0.bench"'


def _world() -> plan._World:
    return plan._World(
        world_id="world:authored:test",
        version_id=uuid.UUID(int=7),
        state_sha256="a" * 64,
        edit_seq=3,
        assets=(
            plan._Choice("cc0.bench", "cc0.bench", "Bench", "A wooden bench."),
            plan._Choice("cc0.lamp-post", "cc0.lamp-post", "Lamp post", "A lamp."),
        ),
        objects=(plan._Choice("object-1", "object:bench", "Bench"),),
        arrangements=(plan._Choice("small_square", "small_square", "Small square", "Seats."),),
        arrangement_versions={"small_square": 1},
        descriptors={},
        object_ids=frozenset({"object:bench"}),
    )


def _ran_on(opening: str, filler: str):
    """A reply that runs on: ``opening``, then ``filler`` to whatever ceiling it was asked."""

    def reply(payload: Mapping[str, Any]) -> HttpResponse:
        ceiling = int(payload["max_tokens"])
        content = opening + filler * ceiling
        body = chat_body(
            content,
            model=EXTRACTOR,
            finish_reason="length",
            completion_tokens=ceiling,
            reasoning_tokens=0,
        )
        return HttpResponse(status_code=200, text=json.dumps(body))

    return reply


def _filled(form: Mapping[str, Any]):
    def reply(_payload: Mapping[str, Any]) -> HttpResponse:
        body = chat_body(json.dumps(form), model=EXTRACTOR, completion_tokens=40)
        return HttpResponse(status_code=200, text=json.dumps(body))

    return reply


class _Endpoint:
    """Answers each request with the next scripted reply, which may read what was asked."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
        self.requests.append(dict(payload))
        return self.replies.pop(0)(payload)

    def get_json(self, url, *, headers, timeout):  # type: ignore[no-untyped-def]
        raise AssertionError("the drafter reads nothing")


def _client(endpoint: _Endpoint) -> tuple[ModelClient, BudgetGuard]:
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10)
    client = ModelClient(
        api_key="test-key-not-real", transport=endpoint, budget=budget, policy=RecordingPolicy()
    )
    return client, budget


def _draft(endpoint: _Endpoint):
    client, budget = _client(endpoint)
    drafted = plan._draft_world_edit(
        client, "Put a bench here.", _world(), log=CallLog(), placeholders=None
    )
    return drafted, budget


# -- the form --------------------------------------------------------------------------------------


def test_no_list_on_the_world_edit_form_is_followed_by_a_field():
    schema = response_format_for(plan._world_edit_form(_world()))["json_schema"]["schema"]
    assert arrays_followed_by_a_property(schema) == []
    step = schema["$defs"]["WorldEditStep"]["properties"]
    assert list(step) == ["operation", "options"]


def test_the_shape_check_finds_a_list_with_a_field_after_it():
    # The check itself, on the form the drafter sent before: three lists, each but the last
    # followed by a field.
    earlier = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string"},
                        "kinds": {"type": "array", "items": {"type": "string"}},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "arrangements": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    }
    assert arrays_followed_by_a_property(earlier) == [
        "$.steps[].kinds (followed by objects)",
        "$.steps[].objects (followed by arrangements)",
    ]


def test_an_option_is_read_in_the_list_its_operation_takes_options_from():
    world = _world()
    removed = plan._typed_from_draft(
        [{"operation": "remove_object", "options": ["cc0.bench", "object-1"]}], world
    )
    assert removed.actions == [
        plan._Action(plan.WorldEditOperation.REMOVE_OBJECT, object_id="object:bench")
    ]
    placed = plan._typed_from_draft(
        [{"operation": "place_object", "options": ["object-1", "small_square"]}], world
    )
    assert placed.refusal is not None and placed.refusal["code"] == "not_in_catalogue"


# -- the ceiling -----------------------------------------------------------------------------------


def test_a_reply_that_runs_on_ends_at_the_drafters_ceiling_not_the_roles():
    manifest = load_manifest()
    binding = manifest[Role.STRUCTURED_EXTRACTION]
    assert binding.min_max_tokens <= plan.DRAFT_MAX_TOKENS < binding.default_max_tokens

    endpoint = _Endpoint(
        _ran_on(_WHITESPACE_OPENING, "\n   "), _ran_on(_WHITESPACE_OPENING, "\n   ")
    )
    drafted, budget = _draft(endpoint)

    assert drafted is None
    assert [r["max_tokens"] for r in endpoint.requests] == [plan.DRAFT_MAX_TOKENS] * 2
    spent = sum(call.completion_tokens for call in budget.ledger.calls)
    assert spent == 2 * plan.DRAFT_MAX_TOKENS


def test_the_simulation_drafter_has_the_same_ceiling():
    endpoint = _Endpoint(
        _ran_on('{"action": "play"', "\n   "),
        _filled({"action": "play", "speed": None, "minutes": None}),
    )
    client, _budget = _client(endpoint)
    drafted = plan._draft_simulation(
        client, "Play.", {"society": None}, log=CallLog(), placeholders=None
    )
    assert drafted == {"action": "play", "speed": None, "minutes": None}
    assert [r["max_tokens"] for r in endpoint.requests] == [plan.DRAFT_MAX_TOKENS] * 2


# -- the repair ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "shape"),
    [
        (_ran_on(_WHITESPACE_OPENING, "\n   "), Runaway.WHITESPACE),
        (_ran_on(_REPEATING_OPENING, ',"cc0.bench"'), Runaway.REPETITION),
        (_ran_on(_REPEATING_OPENING, ',"cc0.bench","cc0.lamp-post"'), None),
    ],
)
def test_the_repair_says_how_the_reply_ran_on_and_never_repeats_it(reply, shape):
    form = {"steps": [{"operation": "place_object", "options": ["cc0.bench"]}]}
    endpoint = _Endpoint(reply, _filled(form))
    drafted, _budget = _draft(endpoint)

    assert drafted == form["steps"]
    first, second = (r["messages"] for r in endpoint.requests)
    assert second[: len(first)] == first
    (repair,) = second[len(first) :]
    assert repair == {"role": "user", "content": plan._RUNAWAY_REPAIRS[shape]}
    # The model is told what went wrong, never shown what it wrote.
    assert all(message["role"] != "assistant" for message in second)
    for opening in (_WHITESPACE_OPENING, _REPEATING_OPENING):
        assert all(opening not in message["content"] for message in second)


def test_each_shape_has_its_own_repair():
    repairs = plan._RUNAWAY_REPAIRS
    assert set(repairs) == {Runaway.WHITESPACE, Runaway.REPETITION, None}
    assert len(set(repairs.values())) == 3
    assert "line break" in repairs[Runaway.WHITESPACE]
    assert "each option once" in repairs[Runaway.REPETITION]


def test_the_cut_reply_reaches_the_drafter_with_its_shape():
    client, _budget = _client(_Endpoint(_ran_on(_WHITESPACE_OPENING, "\n   ")))
    with pytest.raises(TruncatedResponseError) as cut:
        client.structured(
            Role.STRUCTURED_EXTRACTION,
            [{"role": "user", "content": "x"}],
            plan._world_edit_form(_world()),
            prompt_version=plan.ACTION_PROMPT_VERSION,
            max_tokens=plan.DRAFT_MAX_TOKENS,
        )
    assert cut.value.runaway == Runaway.WHITESPACE
    assert "\n   \n" not in str(cut.value)


# -- the prompt ------------------------------------------------------------------------------------


def test_the_drafter_is_asked_to_name_each_option_once_and_not_to_write_one_line():
    # Measured on the live endpoint: asked for the form on one line, the model padded an undo out to
    # the form's three steps, with `other` steps (which refuse the plan) or with more undos; written
    # as it chooses, the same requests were one step. With the list last, how the form is laid out
    # no longer decides whether a comma can be missed, so the layout is left to the model. A repair
    # after a reply that ran on in whitespace still asks for one line.
    system = plan._WORLD_EDIT_SYSTEM
    assert "Name each option once." in system
    assert "one line" not in system
    assert "one line" in plan._RUNAWAY_REPAIRS[Runaway.WHITESPACE]


def test_a_step_of_other_beside_one_that_can_be_prepared_refuses_the_plan():
    padded = plan._typed_from_draft(
        [
            {"operation": "undo_last_edit", "options": []},
            {"operation": "other", "options": []},
        ],
        _world(),
    )
    assert padded.refusal is not None and padded.refusal["step"] == 1


def test_a_draft_that_takes_back_more_than_one_change_is_refused():
    undo = {"operation": "undo_last_edit", "options": []}
    one = plan._typed_from_draft([undo], _world())
    assert one.refusal is None
    assert one.actions == [plan._Action(plan.WorldEditOperation.UNDO_LAST_EDIT)]
    padded = plan._typed_from_draft([undo, undo, undo], _world())
    assert padded.refusal is not None
    assert padded.refusal["code"] == "action_not_offered" and padded.refusal["step"] == 1
    assert padded.actions == []
    placed_then_undone = plan._typed_from_draft(
        [{"operation": "place_object", "options": ["cc0.bench"]}, undo], _world()
    )
    assert placed_then_undone.refusal is None


# -- classifying a cut reply -----------------------------------------------------------------------


def test_a_reply_ending_in_a_long_whitespace_run_ran_on_in_whitespace():
    assert runaway_shape(_WHITESPACE_OPENING + " " * RUNAWAY_WHITESPACE_CHARS) is Runaway.WHITESPACE
    assert runaway_shape(_WHITESPACE_OPENING + "\n\t " * 200) is Runaway.WHITESPACE


def test_a_whitespace_run_below_the_threshold_is_no_shape():
    assert runaway_shape(_WHITESPACE_OPENING + " " * (RUNAWAY_WHITESPACE_CHARS - 1)) is None


def test_one_item_repeated_to_the_threshold_ran_on_by_repetition():
    whole = ',"cc0.bench"' * RUNAWAY_REPEATS
    assert runaway_shape(_REPEATING_OPENING + whole + ',"cc0.be') is Runaway.REPETITION
    # The item the limit cut is not counted, so one fewer whole repeat is no shape.
    fewer = ',"cc0.bench"' * (RUNAWAY_REPEATS - 2)
    assert runaway_shape('{"options":["cc0.bench"' + fewer + ',"cc0.be') is None


def test_a_long_reply_that_is_neither_is_no_shape():
    varied = " ".join(f'"item-{index}",' for index in range(600))
    assert len(varied) > 4 * RUNAWAY_WHITESPACE_CHARS
    assert runaway_shape('{"options":[' + varied) is None
    prose = "The bench goes by the lamp, facing the square.\n" * 40
    assert runaway_shape(prose + "and then") is None


def test_a_whole_reply_is_no_shape():
    assert runaway_shape('{"steps":[{"operation":"undo_last_edit","options":[]}]}') is None
    assert runaway_shape("") is None
