"""A line said before is no answer, and a line nobody answered is told so.

With a real model, a person speaking to routine villagers, who never say a line, was shown its own
last eight lines under "do not repeat them" and said one of them again word for word. From registry
version 14 a society of things' people are asked under the eleventh prompt, whose terms hold a line
to ``repeats_no_line`` beside ``names_no_listener``: a line that says again one its request told the
being it said lately or heard, compared on its letters and digits alone, case folded, is not an
answer and is asked once more, within the attempts the contract allows. From action catalog 14
(``answers_told``) each line the being said lately is told with whether the one it was said to
answered, and one nobody answered with "(no answer)". A request asked under the tenth prompt and
the twelfth catalog reads, replays and rebuilds as it did.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from exulanica.abilities import registry
from exulanica.abilities.registry import PURPOSEFUL_BY_KIND_WEIGHTS
from exulanica.things.lines import LINE_RULES, line_key, repeats_line
from exulanica.world.role_decisions import answer_outcome, role_request
from exulanica.world.society_decision_contract import person_role, situation
from exulanica.world.society_decisions import receipt_for, seal, validate_decision_receipt
from exulanica.world.society_play import PLAY_CATALOG_VERSION, play_contract
from exulanica.world.society_things import LINES_CONTRACT, THINGS_PROFILE

import test_society_lines as lines
import things_society_support as things_support
from things_society_support import SEED

PROMPT_V10 = "society-person-choice/v10"
TWELFTH = {"society-decision-action": 12, "society-decision-policy": 8}
#: The twelfth catalog's request for the knight of :func:`_spoken`, as the code before the
#: fourteenth catalog sealed it, its town composed as that code composed it (:func:`_as_sealed`).
TWELFTH_REQUEST_SHA256 = "0ef86553485323177e64e123a481cf733987631b2bbf824370fd443fd041f493"
#: What the knight said lately, and the minute it said each: one to the villager, who answered,
#: one to the villager, who did not, and one to everyone near, which nobody answered.
SAID = (
    (3, "villager", "Have you seen the old gate?"),
    (6, "villager", "The wind is up tonight."),
    (8, None, "Good evening, everyone."),
)


def _say_to(options):
    return next(option for option in options if option.kind == "say_to")


def _spoken(state, knight_id):
    """The knight said the lines of :data:`SAID` beside the villager, and heard the villager
    answer only the first; the minute is the tenth."""
    knight = next(p for p in state["inhabitants"] if p["id"] == knight_id)
    villager = next(p for p in state["inhabitants"] if p["came_by"] == "populated")
    state["tick"] = 10
    knight["said"] = [
        {
            "tick": tick,
            "to": None if to is None else villager["id"],
            "to_name": None if to is None else villager["display_name"],
            "to_kind": None if to is None else dict(villager["kind"]),
            "line": line,
        }
        for tick, to, line in SAID
    ]
    knight["heard"] = [
        {
            "tick": 4,
            "from": villager["id"],
            "from_kind": dict(villager["kind"]),
            "from_number": villager["ordinal"] + 1,
            "from_name": villager["display_name"],
            "to": knight_id,
            "line": "I have, it is leaning.",
        }
    ]
    return knight


def _told(versions=None, *, edit=None):
    """The knight's request after :func:`_spoken`, asked under ``versions`` (the newest left
    out), as the host builds it; ``edit`` changes the state first."""
    state, document, knight, _contract, _options = lines._asked()
    _spoken(state, knight["id"])
    if edit is not None:
        edit(next(p for p in state["inhabitants"] if p["id"] == knight["id"]))
    role = person_role()
    contract = role.contract(versions or role.terms(THINGS_PROFILE).versions)
    request, _status = role_request(
        role,
        state,
        document,
        knight["id"],
        request_id=uuid.UUID(int=14),
        contract=contract,
        seed=SEED,
        provider_config={
            "provider": "test",
            "model_id": "test",
            "mechanism": "tool_call",
            "choice_seq": 1,
            "manifest_sha256": "0" * 64,
            "prompt_version": PROMPT_V10 if versions else role.terms(THINGS_PROFILE).prompt_version,
            "contract": contract.binding(),
            "deadline_ms": contract.value("decision_deadline_ms"),
        },
        day_start=None,
        world_title=None,
    )
    return request


def test_a_line_says_another_again_by_its_letters_and_digits_case_folded():
    assert line_key("Have you seen the post? It's tilting.") == "haveyouseenthepostitstilting"
    assert repeats_line("have you seen the fence post", ["Have you seen the fence post?"])
    assert repeats_line("Have you seen the fence post?", ["Have  you seen the fence-post!"])
    assert not repeats_line(
        "Have you seen the fence post again?", ["Have you seen the fence post?"]
    )
    assert not repeats_line("Good evening.", [])
    assert "repeats_no_line" in LINE_RULES


def test_a_society_of_things_is_asked_under_the_eleventh_prompt_with_both_line_rules():
    person = person_role()
    things = person.terms(THINGS_PROFILE)
    assert things.prompt_version == "society-person-choice/v12"
    assert things.line_rules == frozenset({"names_no_listener", "repeats_no_line"})
    assert things.versions["society-decision-action"] == 16
    assert things.not_offered.endswith("nor says again a line already said.")
    # The tenth prompt's terms keep the one rule they stated.
    assert person.terms_with_prompt(PROMPT_V10).line_rules == frozenset({"names_no_listener"})


def test_a_line_the_being_said_or_heard_is_asked_once_more_and_a_new_one_taken():
    _state, _document, _knight, contract, options = lines._asked()
    say_to = _say_to(options)
    # A line it said, in other capitals and punctuation, and a line it heard.
    for told in ("the wind is up tonight", "I have, it is leaning!"):
        request, result, transport, _options = lines._ask(
            [
                {"action": say_to.label, "line": told},
                {"action": say_to.label, "line": "Shall we walk to the gate?"},
            ],
            prepare=_spoken,
        )
        assert (result["status"], result["proposal"]["line"]) == (
            "accepted",
            "Shall we walk to the gate?",
        )
        assert transport.call_count == 2
        second = transport.requests[1]["payload"]["messages"]
        assert second[-1]["content"] == lines._things_terms().not_offered
        validate_decision_receipt(receipt_for(request, 1, result), request)
    # Every attempt saying a told line again ends as any answer that is no answer does.
    attempts = contract.value("answer_attempts_maximum")
    _request, result, transport, _options = lines._ask(
        [{"action": say_to.label, "line": "Good evening, everyone."}] * attempts, prepare=_spoken
    )
    assert (result["status"], result["reason"], result["proposal"]) == (
        "rejected",
        "answer_not_offered",
        None,
    )
    assert transport.call_count == attempts


def test_a_runner_s_check_refuses_a_line_said_before_as_the_host_does():
    request = _told()
    context = request["context"]
    versions = request["provider_config"]["contract"]["catalog_versions"]
    label = next(o["label"] for o in context["options"] if o["kind"] == "say_to")
    role = person_role()
    for told in ("the wind is up tonight", "I have, it is leaning!"):
        assert answer_outcome(role, context, versions, label, told) == "line_said_before"
    assert answer_outcome(role, context, versions, label, "Shall we walk?") == "offered_label"


def test_a_receipt_s_line_is_held_to_the_rule_its_request_s_prompt_states():
    _state, _document, _knight, _contract, options = lines._asked()
    say_to = _say_to(options)
    request, result, _transport, _options = lines._ask(
        [{"action": say_to.label, "line": "Shall we walk?"}], prepare=_spoken
    )
    again = {**result, "proposal": {**result["proposal"], "line": "The wind is up tonight."}}
    with pytest.raises(ValueError, match="says again a line it was told"):
        validate_decision_receipt(receipt_for(request, 1, again), request)
    # A request asked under the tenth prompt, which held lines to no such rule, reads as it did.
    earlier = copy.deepcopy(request)
    earlier["provider_config"]["prompt_version"] = PROMPT_V10
    earlier = seal({key: value for key, value in earlier.items() if key != "document_sha256"})
    validate_decision_receipt(receipt_for(earlier, 1, again), earlier)


def test_each_line_said_lately_says_whether_it_was_answered():
    context = _told()["context"]
    assert [line.get("answered") for line in context["said"]] == [True, False, False]
    shown = [line for line in situation(context) if line.startswith("- ") and "you said" in line]
    assert [line.endswith(" (no answer)") for line in shown] == [False, True, True]
    assert shown[1].endswith(': "The wind is up tonight." (no answer)')
    # The twelfth catalog tells the lines as it always did.
    twelfth = _told(TWELFTH)["context"]
    assert all("answered" not in line for line in twelfth["said"])
    assert not any("(no answer)" in line for line in situation(twelfth))


def test_an_answer_a_full_heard_list_may_have_let_go_is_not_told():
    kept = person_role().contract(LINES_CONTRACT).value("lines_heard_maximum")

    def heard_from(speaker):
        def edit(knight):
            first = knight["heard"][0]
            who = first["from"] if speaker == "villager" else "someone else"
            knight["heard"] = [
                {**first, "from": who, "to": None, "tick": 9, "line": f"Line {n}."}
                for n in range(kept)
            ]

        return edit

    # The villager spoke after all three lines: each was answered, whatever was let go.
    told = _told(edit=heard_from("villager"))["context"]["said"]
    assert [line.get("answered", "unknown") for line in told] == [True, True, True]
    # Someone else filled the heard list after the villager's lines were said, so whether the
    # villager answered them is not known and not told; the line to everyone near was answered.
    told = _told(edit=heard_from("someone else"))["context"]["said"]
    assert [line.get("answered", "unknown") for line in told] == ["unknown", "unknown", True]


def test_a_person_playing_is_told_which_of_their_lines_went_unanswered():
    played = play_contract(person_role(), THINGS_PROFILE)
    assert PLAY_CATALOG_VERSION == 17 == played.versions["society-decision-action"]
    assert "answers_told" in played.label_rules


def _as_sealed(monkeypatch) -> None:
    """The town composed as the code that sealed the stored twelfth request composed it: its first
    input recording the purposeful planner's third version. A society made since records a later
    one, which changes nothing here but the module it names, so the request's bytes are the ones a
    society stored then rebuilds. Its people are the villager's second version, as the eighth
    ground catalog named them."""
    things_support.composed_under_ground(monkeypatch, 8)
    current = registry.current_modules
    monkeypatch.setattr(
        registry,
        "current_modules",
        lambda *, day=False: tuple(
            sorted(
                PURPOSEFUL_BY_KIND_WEIGHTS
                if module.startswith("exulanica-ability/purposeful/")
                else module
                for module in current(day=day)
            )
        ),
    )


def test_a_twelfth_request_rebuilds_to_the_byte(monkeypatch):
    _as_sealed(monkeypatch)
    assert _told(TWELFTH)["document_sha256"] == TWELFTH_REQUEST_SHA256
