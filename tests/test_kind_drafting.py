"""The kind drafter: a brief built from the kind catalogs, filled by a model with two repairs at
most, compiled into a kind document the server's checks decide, and told only a check's code,
place and sentence.

No test here sends a request anywhere: replies are scripted. The kinds are the hand-written test
fixtures in ``tests/fixtures/world-kinds``, turned into the brief a model would fill by the
converter in ``tests/kind_briefs.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.models.schema import response_format_for
from exulanica.models.transport import HttpResponse
from exulanica.selection.kind_brief import brief_form, compile_brief
from exulanica.selection.kind_drafting import (
    DRAFT_ATTEMPTS,
    KindDraftRefusalCode,
    KindVerdict,
    draft_kind,
    kind_drafting_prompt,
    render_instructions,
)
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.samples import check_samples
from exulanica.world.society_living import town_routine

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from form_shapes import properties_after_an_array
from kind_briefs import PROVENANCE, brief_of, fixture_kind, held_to_form
from model_fakes import FakeTransport, RecordingPolicy, chat_body

#: The scripted transport's model, as every reply names it.
MODEL = "test/model"
ROLE = Role.KIND_DRAFTER
DESCRIPTION = "A small farm with a farmhouse, a barn, fields and a duck pond."


def _farm() -> dict[str, Any]:
    return held_to_form(brief_of(fixture_kind("farm")))


def _reply(value: object, *, finish_reason: str = "stop") -> HttpResponse:
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


def _checked(document: dict[str, Any]) -> KindVerdict:
    """Both stages, in this process, as a measurement runs them."""
    try:
        kind = read_kind(document)
        return KindVerdict(True, kind, check_samples(kind))
    except KindRefused as refused:
        return KindVerdict(False, code=refused.code, where=refused.where, detail=refused.detail)


def _zone(brief: dict[str, Any], label: str) -> dict[str, Any]:
    return next(zone for zone in brief["zones"] if zone["label"] == label)


def _thing(zone: dict[str, Any], label: str) -> dict[str, Any]:
    listed = [*zone["structures"], *zone["areas"], *zone["fixtures"]]
    return next(thing for thing in listed if thing["label"] == label)


def _crowded(brief: dict[str, Any]) -> None:
    """Three cottages for sixty-four people each: more than a world houses."""
    farmyard = _zone(brief, "farmyard")
    cottage = copy.deepcopy(_thing(farmyard, "farmhouse"))
    cottage.update(label="cottage", count={"from": 3, "to": 3}, residents=64, rooms=[])
    farmyard["structures"].append(cottage)


def test_the_brief_has_no_union_and_its_arrays_last():
    schema = response_format_for(brief_form(), arrays_last=True)["json_schema"]["schema"]
    text = json.dumps(schema)
    assert "anyOf" not in text and "oneOf" not in text
    assert properties_after_an_array(schema) == []
    # Nothing in the brief is a key or names one: the compiler makes every key and reference.
    assert '"key"' not in text and "use_class" not in text and '"part"' not in text


def test_a_kind_that_passes_is_drafted_once_with_its_provenance():
    client, transport = _client(_reply(_farm()))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.refusal is None and outcome.attempts == ("passed",)
    assert transport.call_count == 1
    instructions = transport.requests[0]["payload"]["messages"][0]["content"]
    provenance = outcome.document["provenance"]
    assert provenance["words_sha256"] == hashlib.sha256(DESCRIPTION.encode()).hexdigest()
    assert provenance["prompt_sha256"] == hashlib.sha256(instructions.encode()).hexdigest()
    assert provenance["prompt_version"] == "kind-drafting-4"
    assert (outcome.document["origin"], provenance["model"]) == ("drafted", MODEL)
    assert outcome.report["verdict"] == "passed"
    assert [(step["outcome"], step["sizing"]) for step in outcome.trail] == [("passed", [])]
    assert outcome.trail[0]["brief"] == _farm()
    # The description is the user message, as sent; the instructions carry the catalogs' words.
    assert DESCRIPTION in transport.requests[0]["payload"]["messages"][1]["content"]
    assert "workplace (structure, area, fixture, room)" in instructions


def test_a_kind_the_checks_refuse_is_told_the_check_and_place_and_never_its_own_words():
    crowded = _farm()
    _crowded(crowded)
    crowded["summary"] = "A WORD ONLY THE REPLY HOLDS"
    client, transport = _client(_reply(crowded), _reply(_farm()))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.refusal is None
    assert outcome.attempts == ("check:kind_population_out_of_bounds", "passed")
    repair = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert "kind_population_out_of_bounds at a sample world of the kind" in repair
    # The check's own sentence is repeated, the server's words about the kind.
    assert "houses" in outcome.trail[0]["detail"] and outcome.trail[0]["detail"] in repair
    assert outcome.trail[0]["brief"]["summary"] == "A WORD ONLY THE REPLY HOLDS"
    assert "A WORD ONLY THE REPLY HOLDS" not in json.dumps(transport.requests[1]["payload"])


def test_three_refusals_are_refused_by_name_with_the_last_check():
    crowded = _farm()
    _crowded(crowded)
    client, transport = _client(*(_reply(crowded) for _ in range(DRAFT_ATTEMPTS)))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert DRAFT_ATTEMPTS == 3
    assert outcome.document is None and transport.call_count == DRAFT_ATTEMPTS
    assert outcome.refusal.code == KindDraftRefusalCode.NOT_DRAFTED
    assert outcome.refusal.check == (
        "kind_population_out_of_bounds",
        "a sample world of the kind",
    )


def test_a_brief_outside_the_schema_or_cut_short_is_repaired():
    farm = _farm()
    missing = {key: value for key, value in farm.items() if key != "zones"}
    client, _transport = _client(_reply(missing), _reply(farm))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.attempts == ("form_refused", "passed")
    client, transport = _client(_reply(farm, finish_reason="length"), _reply(farm))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.attempts == ("truncated", "passed")
    repair = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert repair == kind_drafting_prompt().repair_truncated


@pytest.mark.parametrize(
    ("tail", "outcome", "words"),
    [
        (" \n" * 200, "truncated:whitespace", "repair_whitespace"),
        (',"a lot"' * 12, "truncated:repetition", "repair_repetition"),
    ],
)
def test_a_brief_cut_off_running_on_is_told_how_it_ran_on(tail, outcome, words):
    farm = _farm()
    cut = json.dumps(chat_body(json.dumps(farm)[:600] + tail, finish_reason="length", model=MODEL))
    client, transport = _client(HttpResponse(status_code=200, text=cut), _reply(farm))
    drafted = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert drafted.attempts == (outcome, "passed")
    repair = transport.requests[1]["payload"]["messages"][-1]["content"]
    assert repair == getattr(kind_drafting_prompt(), words)


def test_the_instructions_are_the_prompt_file_s_words_and_the_catalogs_vocabulary():
    prompt = kind_drafting_prompt()
    catalogs = load_kind_catalogs()
    rendered = render_instructions(prompt, catalogs, town_routine())
    assert rendered.startswith(prompt.instructions)
    for key in ("zones", "holdings", "parts", "use_classes", "placed_things", "residents"):
        low, high = catalogs.bound(key)
        assert f"- {key}: {low} to {high}" in rendered
    # Every role a brief may name, and none of those the compiler gives the spine and boundary.
    for role in catalogs.role_forms:
        assert (f"- {role} (" in rendered) == (role not in ("path", "road", "boundary"))
    for rule in prompt.rules:
        assert f"- {rule.rule} ({rule.code})" in rendered
    assert "\u2014" not in rendered  # the em dash


def _many(zone: dict[str, Any], thing: dict[str, Any], labels: list[str]) -> None:
    for label in labels:
        zone["fixtures"].append({**copy.deepcopy(thing), "label": label})


def _new_zone(brief: dict[str, Any], label: str) -> dict[str, Any]:
    zone = {**copy.deepcopy(_zone(brief, "pond corner")), "label": label}
    zone.update(placement="middle", share=100, structures=[], areas=[], fixtures=[])
    brief["zones"].append(zone)
    return zone


def _zone_holds_too_many(brief: dict[str, Any]) -> None:
    farmyard = _zone(brief, "farmyard")
    _many(farmyard, _thing(farmyard, "hay bale"), [f"bale {n}" for n in range(1, 10)])


def _too_many_parts(brief: dict[str, Any]) -> None:
    bale = _thing(_zone(brief, "farmyard"), "hay bale")
    for number in range(1, 5):
        _many(_new_zone(brief, f"yard {number}"), bale, [f"bale {number}{n}" for n in range(9)])


def _too_many_uses(brief: dict[str, Any]) -> None:
    stall = copy.deepcopy(_thing(_zone(brief, "farmyard"), "hay bale"))
    stall.update(roles=[], use_role="workplace")
    stall["work"] = [
        {
            "role_label": "stallholder",
            "staff_per_unit": 1,
            "opening_minute": 480,
            "closing_minute": 1020,
            "shifts": ["day"],
        }
    ]
    for number in range(1, 3):
        _many(_new_zone(brief, f"market {number}"), stall, [f"stall {number}{n}" for n in range(6)])


def _too_many_things(brief: dict[str, Any]) -> None:
    bale = {**copy.deepcopy(_thing(_zone(brief, "farmyard"), "hay bale")), "label": "stone"}
    bale.update(count={"from": 64, "to": 64}, width_mm=200, depth_mm=200)
    for number in range(1, 10):
        _new_zone(brief, f"stones {number}")["fixtures"].append(copy.deepcopy(bale))


#: How each rule the drafter is told is broken, on the hand-written farm as a brief: the change
#: that breaks the rule and nothing else.
RULE_CASES: dict[str, Callable[[dict[str, Any]], None]] = {
    "zone_holds_too_many": _zone_holds_too_many,
    "too_many_parts": _too_many_parts,
    "too_many_uses": _too_many_uses,
    "too_many_things": _too_many_things,
    "too_many_people": _crowded,
}


@pytest.mark.parametrize("rule", kind_drafting_prompt().rules, ids=lambda rule: rule.case)
def test_every_rule_the_drafter_is_told_is_one_the_checks_hold(rule):
    """The drafter is told the rules the compiler cannot keep for it: each, broken alone in a
    brief, is refused by the check the instructions name once the brief is compiled. A check that
    changes its code or stops refusing fails here, and so does a rule told with no case."""
    brief = _farm()
    assert _checked(compile_brief(brief, provenance=PROVENANCE).document).passed
    RULE_CASES[rule.case](brief)
    verdict = _checked(compile_brief(held_to_form(brief), provenance=PROVENANCE).document)
    assert not verdict.passed and verdict.code == rule.code, verdict


def test_every_case_breaks_a_rule_the_drafter_is_told():
    assert set(RULE_CASES) == {rule.case for rule in kind_drafting_prompt().rules}


def test_a_draft_s_attempts_are_kept_when_a_later_call_raises():
    """A provider that times out on a repair raises out of the draft; the attempts before it stay
    in the caller's trail, with the refused kind's check and brief."""
    from exulanica.models.errors import TransportError

    crowded = _farm()
    _crowded(crowded)
    timeout = TransportError("timed out", timed_out=True, retryable=False)
    client, _transport = _client(_reply(crowded), timeout)
    kept: list[dict[str, Any]] = []
    with pytest.raises(TransportError):
        draft_kind(client, DESCRIPTION, role=ROLE, check=_checked, trail=kept)
    assert [step["outcome"] for step in kept] == ["check:kind_population_out_of_bounds"]
    assert kept[0]["brief"] == crowded
