"""A line said to one being never names or describes it, under the terms that hold lines to that.

A being of a society of things is offered "say something to <name> (a villager), 2 m away", and a
model copied the listener's description into its line ("The night deepens, a villager."). From
registry version 7 a society of things' people are asked under the fourth prompt, whose
instruction asks them to speak to the one they address without naming or describing them, and
whose terms hold a line to ``names_no_listener``: a line said to one being that ends with that
being's name or description, as the option's words name them, is not an answer to the choice and
is asked once more, within the attempts the contract allows. A receipt is held to the rule its
request's prompt states, so a request asked under an earlier prompt reads as it did.
"""

from __future__ import annotations

import copy

import pytest
from exulanica.things.lines import LINE_RULES, listener_forms, names_listener
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_contract import line_listener, person_role
from exulanica.world.society_decisions import receipt_for, seal, validate_decision_receipt
from exulanica.world.society_things import THINGS_PROFILE

import test_society_lines as lines

PROMPT_V3 = "society-person-choice/v3"


def _say_to(options):
    return next(option for option in options if option.kind == "say_to")


@pytest.mark.parametrize(
    ("line", "listener", "names"),
    [
        ("The night deepens, a villager.", "bela ash 2 (a villager)", True),
        ("Good evening, Bela Ash 2!", "bela ash 2 (a villager)", True),
        ("Fine weather, villager", "bela ash 2 (a villager)", True),
        ("Shall we walk, the villager?", "bela ash 2 (a villager)", True),
        ("Hold fast, knight!", "the knight", True),
        ("Onward, Knight 2.", "knight 2", True),
        ("The villager's cart is full.", "bela ash 2 (a villager)", False),
        ("Stand with me.", "the knight", False),
        ("Meet my grandvillager.", "bela ash 2 (a villager)", False),
    ],
)
def test_a_line_names_its_listener_by_its_name_or_description(line, listener, names):
    assert names_listener(line, listener) is names


def test_a_listener_is_named_by_its_name_and_its_kind_with_and_without_an_article():
    assert listener_forms("Bela Ash 2 (a villager)") == (
        "bela ash 2 (a villager)",
        "bela ash 2",
        "a villager",
        "the villager",
        "villager",
    )
    assert listener_forms("the knight") == ("the knight", "a knight", "knight")
    assert listener_forms("ash 1 (an owl)")[2:] == ("an owl", "the owl", "owl")
    assert listener_forms("knight 2") == ("knight 2",)


def test_a_say_option_names_its_listener_in_its_own_words():
    _state, _document, _knight, contract, options = lines._asked()
    say_to = _say_to(options).as_record()
    listener = line_listener(say_to, contract)
    assert listener is not None and "(a villager)" in listener
    assert say_to["label"].startswith(f"say something to {listener}, ")
    say_all = next(option for option in options if option.kind == "say_all").as_record()
    assert line_listener(say_all, contract) is None
    # The third contract's words name the listener by kind and number.
    earlier = person_role().contract({"society-decision-action": 3, "society-decision-policy": 3})
    label = earlier.words["say_to"].format(who="villager", number=2, metres=2)
    assert line_listener({"kind": "say_to", "label": label}, earlier) == "villager"
    assert line_listener({"kind": "say_to", "label": "say hello"}, contract) is None


def test_a_society_of_things_is_asked_under_the_fourth_prompt_with_the_listener_rule():
    person = decision_roles().role("society_decision")
    things = person.terms(THINGS_PROFILE)
    assert decision_roles().version >= 7
    assert things.prompt_version == "society-person-choice/v4"
    assert things.line_rules == frozenset({"names_no_listener"}) <= LINE_RULES
    assert "without naming or describing them" in things.instruction
    assert "(the knight, a villager)" not in things.instruction
    assert things.not_offered.endswith("never names or describes the one it is said to.")
    # Every other engine's people are asked as before, with no rule beside the line rule.
    assert person.terms().line_rules == frozenset()
    assert person.terms_with_prompt(things.prompt_version) == things
    assert person.terms_with_prompt(PROMPT_V3) is None


def test_a_line_naming_its_listener_is_asked_once_more_and_a_clean_one_taken():
    _state, _document, _knight, contract, options = lines._asked()
    say_to = _say_to(options)
    request, result, transport, _options = lines._ask(
        [
            {"action": say_to.label, "line": "The night deepens, a villager."},
            {"action": say_to.label, "line": "The night deepens."},
        ]
    )
    assert (result["status"], result["proposal"]["line"]) == ("accepted", "The night deepens.")
    assert transport.call_count == 2
    second = transport.requests[1]["payload"]["messages"]
    assert second[-1]["content"] == lines._things_terms().not_offered
    validate_decision_receipt(receipt_for(request, 1, result), request)
    # Every attempt naming its listener ends as any answer that is no answer does, within the
    # attempts the contract allows.
    attempts = contract.value("answer_attempts_maximum")
    _request, result, transport, _options = lines._ask(
        [{"action": say_to.label, "line": "Hold on, a villager!"}] * attempts
    )
    assert (result["status"], result["reason"], result["proposal"]) == (
        "rejected",
        "answer_not_offered",
        None,
    )
    assert transport.call_count == attempts


def test_a_receipt_s_line_is_held_to_the_rule_its_request_s_prompt_states():
    _state, _document, _knight, _contract, options = lines._asked()
    say_to = _say_to(options)
    request, result, _transport, _options = lines._ask(
        [{"action": say_to.label, "line": "Fine evening."}]
    )
    naming = {**result, "proposal": {**result["proposal"], "line": "Fine evening, villager."}}
    with pytest.raises(ValueError, match="names or describes the one it is said to"):
        validate_decision_receipt(receipt_for(request, 1, naming), request)
    # A request asked under the third prompt, which held lines to no such rule, reads as it did.
    earlier = copy.deepcopy(request)
    earlier["provider_config"]["prompt_version"] = PROMPT_V3
    earlier = seal({key: value for key, value in earlier.items() if key != "document_sha256"})
    validate_decision_receipt(receipt_for(earlier, 1, naming), earlier)
    # A line said to everyone near has no one listener.
    say_all = next(option for option in options if option.kind == "say_all")
    everyone = {
        **result,
        "proposal": {
            "label": say_all.label,
            "option": say_all.as_record(),
            "line": "Hi, villager.",
        },
    }
    validate_decision_receipt(receipt_for(request, 1, everyone), request)
