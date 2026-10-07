"""The creature drafter: a form built from the body grammar and the things catalogs, filled by a
model once with one repair, assembled into a creature its checks decide, and told only a check's
code, place and sentence.

No test here sends a request anywhere: replies are scripted. The creatures are the hand-written
recipes in ``tests/fixtures/creatures/creatures.v1.json``, turned into the form a model would fill
by ``creature_support.form_of``, written independently of the reader under test.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.schema import response_format_for
from exulanica.models.transport import HttpResponse
from exulanica.selection.creature_drafting import (
    CHECK_SENTENCES,
    CreatureDraftRefusalCode,
    creature_drafting_prompt,
    draft_creature,
    draft_form,
    form_where,
    render_instructions,
)
from exulanica.things.bodies import body_grammar
from exulanica.things.catalogs import thing_catalogs
from exulanica.things.creatures import CREATURE_CODES

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from creature_support import FIXTURES, form_of
from form_shapes import arrays_followed_by_a_property
from model_fakes import FakeTransport, RecordingPolicy, chat_body

MODEL = "test/model"
#: The role the drafter is asked under until its own is measured and joins the manifest.
ROLE = Role.SPECIFICATION_DRAFTER
DESCRIPTION = "a creature with six legs, a long neck and a striped tail"


def _reply(value: dict[str, Any], *, finish_reason: str = "stop") -> HttpResponse:
    return HttpResponse(
        status_code=200,
        text=json.dumps(chat_body(json.dumps(value), finish_reason=finish_reason, model=MODEL)),
    )


def _client(*responses: HttpResponse) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    return client, transport


def _sent(transport: FakeTransport, index: int) -> list[dict[str, Any]]:
    return list(transport.requests[index]["payload"]["messages"])


# -- the form and the words -----------------------------------------------------------------------


def test_the_form_sends_every_object_s_arrays_last_and_its_choices_from_the_catalogs():
    form = draft_form()
    schema = response_format_for(form, arrays_last=True)["json_schema"]["schema"]
    assert arrays_followed_by_a_property(schema) == []
    # No list anywhere: nothing a reply could stop after before the field that follows.
    assert "array" not in json.dumps(schema)
    grammar = body_grammar()
    text = json.dumps(schema)
    for name in (*grammar.postures, *grammar.colours):
        assert f'"{name}"' in text
    # Each movement, ability and offer is a field of its own.
    for field in (
        *(f"moves_{movement}" for movement in grammar.movements),
        *(f"can_{ability}" for ability in thing_catalogs().abilities if ability != "leave"),
        *(f"offers_{offer}" for offer in ("talk_to", "hear", "receive", "let_take", "be_followed")),
    ):
        assert field in schema["properties"], field


def test_the_instructions_state_every_check_sentence_and_the_vocabulary():
    prompt = creature_drafting_prompt()
    instructions = render_instructions(prompt, body_grammar(), thing_catalogs(), ["old_kind"])
    assert instructions.startswith(prompt.instructions)
    for code, sentence in CHECK_SENTENCES.items():
        assert f"- {code}: {sentence}" in instructions
    for code, _sentence in CREATURE_CODES:
        assert code in CHECK_SENTENCES
    grammar = body_grammar()
    for spec in grammar.movements.values():
        if spec["module"] is None:
            assert spec["refusal"] in instructions
    assert "old_kind" in instructions
    # How bones are counted is stated, and the limit is the grammar's.
    assert f"at most {grammar.limits['bones_maximum']}" in instructions


def test_the_words_hold_no_name_of_a_creature_the_trial_holds_out():
    prompt = creature_drafting_prompt()
    instructions = render_instructions(prompt, body_grammar(), thing_catalogs())
    for word in FIXTURES["creature_words"]:
        found = [
            match.group(0) for match in re.finditer(rf"\b{word}s?\b", instructions, re.IGNORECASE)
        ]
        # "snake case" is a way of writing names, not a creature, and none is written here either.
        assert found == [], word


# -- drafting -------------------------------------------------------------------------------------


def test_a_creature_that_passes_is_drafted_once_with_its_provenance():
    form = form_of("horse", label="striped hill beast")
    client, transport = _client(_reply(form))
    outcome = draft_creature(client, DESCRIPTION, role=ROLE)
    assert outcome.creature is not None and outcome.refusal is None
    assert outcome.attempts == ("passed",)
    assert len(transport.requests) == 1
    kind = outcome.creature.kind
    assert kind.kind == "striped_hill_beast"
    by = kind.document["origin"]["by"]
    instructions = _sent(transport, 0)[0]["content"]
    assert by["model_id"] == MODEL
    assert by["prompt_version"] == "creature-drafting-1"
    assert by["prompt_sha256"] == hashlib.sha256(instructions.encode("utf-8")).hexdigest()
    assert by["words_sha256"] == hashlib.sha256(DESCRIPTION.encode("utf-8")).hexdigest()
    assert DESCRIPTION not in json.dumps(dict(kind.document))


def test_a_creature_the_checks_refuse_is_told_the_check_place_and_sentence_never_its_own_words():
    # Its body has wings, so flying is a movement it could have: this world has not built it.
    refused = form_of("dragon", label="striped hill beast", moves=["walking", "flight"])
    refused["summary"] = "A beast whose summary words must never come back in a repair."
    passing = form_of("horse", label="striped hill beast")
    client, transport = _client(_reply(refused), _reply(passing))
    outcome = draft_creature(client, DESCRIPTION, role=ROLE)
    assert outcome.creature is not None
    assert outcome.attempts == ("check:creature_movement_unbuilt", "passed")
    repair = _sent(transport, 1)[-1]["content"]
    assert "creature_movement_unbuilt" in repair
    assert "moves_flight" in repair
    assert "This world has no flying creatures yet." in repair
    assert CHECK_SENTENCES["creature_movement_unbuilt"] in repair
    assert "must never come back" not in repair


def test_two_refusals_are_refused_by_name_with_the_last_check():
    refused = form_of("three_heads", label="knight")
    client, _transport = _client(_reply(refused), _reply(refused))
    outcome = draft_creature(client, DESCRIPTION, role=ROLE)
    assert outcome.creature is None
    assert outcome.refusal is not None
    assert outcome.refusal.code is CreatureDraftRefusalCode.NOT_DRAFTED
    assert outcome.refusal.check is not None
    assert outcome.refusal.check[:2] == ("creature_name_taken", "label")
    assert outcome.attempts == ("check:creature_name_taken", "check:creature_name_taken")


def test_a_form_outside_the_schema_is_repaired_once():
    bad = form_of("horse", label="striped hill beast")
    bad["posture"] = "sideways"
    client, transport = _client(_reply(bad), _reply(form_of("horse", label="striped hill beast")))
    outcome = draft_creature(client, DESCRIPTION, role=ROLE)
    assert outcome.creature is not None
    assert outcome.attempts == ("form_refused", "passed")
    assert _sent(transport, 1)[-1]["content"] == creature_drafting_prompt().repair_refused


def test_a_reply_cut_off_in_blank_space_is_told_so():
    whole = json.dumps(form_of("horse", label="striped hill beast"))
    cut = HttpResponse(
        status_code=200,
        text=json.dumps(
            chat_body(whole[:300] + "\n" + " " * 4000, finish_reason="length", model=MODEL)
        ),
    )
    client, transport = _client(cut, _reply(form_of("horse", label="striped hill beast")))
    outcome = draft_creature(client, DESCRIPTION, role=ROLE)
    assert outcome.creature is not None
    assert outcome.attempts[0].startswith("truncated")
    assert _sent(transport, 1)[-1]["content"] == creature_drafting_prompt().repair_whitespace


@pytest.mark.parametrize(
    ("where", "field"),
    [
        ("extent_mm.span", "span_mm"),
        ("body.extent_mm.height", "height_mm"),
        ("routine.weights.say", "the weight_ fields"),
        ("abilities[1]", "can_stand"),
        ("limbs[0].count", "legs"),
        ("limbs[0].segments", "leg_segments"),
        ("moves[0]", "moves_walking"),
        ("colours[3]", "colour_eyes"),
        ("heads[2].jaw", "jaws"),
        ("bones", "the whole creature"),
    ],
)
def test_a_place_in_a_document_reads_as_the_field_of_the_form(where, field):
    assembled = {
        "limbs": [{"role": "leg", "count": 4, "segments": 3}],
        "colours": ["crimson", "gold", "ebony", "amber"],
        "moves": ["walking"],
        "abilities": ["wait", "stand"],
        "offers": ["hear"],
    }
    assert form_where(where, assembled) == field
