"""Names keep their capitals in what a model is told and in its choices, from action catalog v9;
from v11 a noticed being's activity names whom it is with as written, and the minute is told as
the world's clock where the world keeps one.

A request asked under the ninth action catalog names a being as the page names it, capitals kept:
in its options, in what the being notices and in what it remembers, each read from the request's own
contract. One asked under the eighth names it in lowercase words, as every stored request was asked,
so a stored request rebuilds to the byte. The names expected here come from the page's own naming
(page_name) and the state this file writes; the eighth request's digest was taken on the code
before the ninth catalog, the ninth's on the code before the eleventh.
"""

from __future__ import annotations

import ast
import dataclasses
import uuid
from pathlib import Path

import pytest
from exulanica.models.choice import ChoiceRequest
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.role_decisions import role_request
from exulanica.world.society_decision_contract import choice_options, page_name, person_role
from exulanica.world.society_recollection import remembered
from exulanica.world.society_surroundings import surroundings

import test_society_recollection as recollection
import test_society_surroundings as noticing
from things_society_support import SEED

EIGHTH = {"society-decision-action": 8, "society-decision-policy": 8}
NINTH = {"society-decision-action": 9, "society-decision-policy": 8}
ELEVENTH = {"society-decision-action": 11, "society-decision-policy": 8}
#: The eighth catalog's request for the knight of :func:`_named_square`, as the code before the
#: ninth catalog sealed it.
EIGHTH_REQUEST_SHA256 = "6a68dbad97b7992199b1b53a734f2f14647b3608020d366b3605caa2660e330b"
#: The ninth catalog's request for the same knight, as the code before the eleventh sealed it.
NINTH_REQUEST_SHA256 = "ea182f1231d8e266665bba86bb06af7c1991fd99d7617945ca8b3ff524d914bd"
#: A people's first minute of the day: 18:00.
DUSK = 18 * 60
#: The calls that build a person's or junction's request, each of which states the day start.
REQUEST_BUILDERS = ("role_request", "person_request", "play_minutes")


def _named_square():
    """The square, its nearest villager named Ivo Reed as a person would write it."""
    state, document, knight, _spirit, villagers = noticing._square()
    villagers[0]["display_name"] = "Ivo Reed"
    return state, document, knight, villagers[0]


def _request(versions, prompt, *, day_start=None, change=None):
    state, document, knight, ivo = _named_square()
    if change is not None:
        change(state, ivo)
    role = person_role()
    contract = role.contract(versions)
    config = {
        "provider": "test",
        "model_id": "test",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "0" * 64,
        "prompt_version": prompt,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    request, status = role_request(
        role,
        state,
        document,
        knight["id"],
        request_id=uuid.UUID(int=9),
        contract=contract,
        seed=SEED,
        provider_config=config,
        day_start=day_start,
    )
    assert status == "in_progress"
    return request, page_name(ivo, state)


def test_the_eleventh_catalog_holds_every_label_rule_before_the_places_named():
    role = person_role()
    terms = role.terms_with_prompt("society-person-choice/v9")
    assert terms is not None and terms.versions == ELEVENTH
    assert role.contract(ELEVENTH).label_rules == {
        "names_as_written",
        "straight_line_distances",
        "activity_names_as_written",
        "clock_told",
    }
    assert role.contract(NINTH).label_rules == {"names_as_written", "straight_line_distances"}
    assert role.contract(EIGHTH).label_rules == frozenset()
    # The prompt before it stays readable with the catalogs its requests recorded.
    seventh = role.terms_with_prompt("society-person-choice/v7")
    assert seventh is not None and seventh.versions == EIGHTH


def test_options_name_a_being_as_the_page_does_from_the_ninth_catalog():
    state, document, knight, ivo = _named_square()
    written = page_name(ivo, state)
    assert written.startswith("Ivo Reed")
    role = person_role()

    def labels(versions):
        options = choice_options(state, document, knight["id"], role.contract(versions), seed=SEED)
        return [option.label for option in options if option.addressee_id == ivo["id"]]

    ninth, eighth = labels(NINTH), labels(EIGHTH)
    assert ninth and all(written in label for label in ninth)
    assert eighth and all(written.lower() in label and written not in label for label in eighth)


def test_what_a_being_notices_names_it_as_its_options_do():
    state, document, knight, ivo = _named_square()
    written = page_name(ivo, state)

    def who(as_written):
        terms = dataclasses.replace(noticing.TERMS, names_as_written=as_written)
        block = surroundings(state, document, knight["id"], terms)
        return {being["who"] for being in block["beings"]}

    assert written in who(True)
    assert written.lower() in who(False) and written not in who(False)


def test_what_a_being_remembers_names_it_as_its_options_do_here_or_gone():
    state, knight, bela = recollection._shown_state()
    person = recollection._person(state, knight["id"])
    written = page_name(bela, state)

    def who(as_written):
        bounds = dataclasses.replace(recollection.BOUNDS, names_as_written=as_written)
        return remembered(state, person, bounds)["beings"][0]["who"]

    assert (who(True), who(False)) == (written, written.lower())
    # Gone, it is named by what the meeting kept, the same way.
    state["inhabitants"] = [one for one in state["inhabitants"] if one["id"] != bela["id"]]
    assert (who(True), who(False)) == (written, written.lower())


def test_a_request_is_told_names_by_its_own_catalog_and_the_eighth_rebuilds_to_the_byte():
    ninth, written = _request(NINTH, "society-person-choice/v8")
    eighth, _written = _request(EIGHTH, "society-person-choice/v7")

    def near(request):
        return {being["who"] for being in request["context"]["surroundings"]["beings"]}

    assert written in near(ninth)
    assert written.lower() in near(eighth) and written not in near(eighth)
    role = person_role()

    def told(request):
        return role.adapter.messages(role, request["context"], AnsweringMechanism.TOOL_CALL)[-1]

    assert written in told(ninth)["content"]
    assert written not in told(eighth)["content"]
    # The eighth catalog's request is sealed as the code before the ninth sealed it.
    assert eighth["document_sha256"] == EIGHTH_REQUEST_SHA256
    assert _request(EIGHTH, "society-person-choice/v7")[0] == eighth


def _talking_with_ivo(state, ivo):
    """The square's second villager talking with Ivo Reed."""
    other = next(p for p in state["inhabitants"] if p["came_by"] == "populated" and p is not ivo)
    other["action"] = {**other["action"], "kind": "talk", "status": "active", "target_id": None}
    other["action"].update(remaining_ticks=3, reason="test")
    other["goal"] = {"kind": "talk", "partner_id": ivo["id"]}


def test_a_noticed_being_s_activity_names_whom_it_is_with_as_written_from_the_eleventh():
    def doing(versions, prompt):
        request, written = _request(versions, prompt, change=_talking_with_ivo)
        beings = request["context"]["surroundings"]["beings"]
        return written, {being["doing"] for being in beings}

    written, eleventh = doing(ELEVENTH, "society-person-choice/v9")
    _written, ninth = doing(NINTH, "society-person-choice/v8")
    assert f"talking with {written}" in eleventh
    assert f"talking with {written.lower()}" in ninth and f"talking with {written}" not in ninth


def _told(request):
    role = person_role()
    messages = role.adapter.messages(role, request["context"], AnsweringMechanism.TOOL_CALL)
    return messages[-1]["content"]


def test_the_minute_is_told_as_the_world_s_clock_from_the_eleventh_catalog():
    eleventh, _written = _request(ELEVENTH, "society-person-choice/v9", day_start=DUSK)
    tick = eleventh["context"]["tick"]
    # The minute the choice is made for: the one after the state's, which its row will name.
    hours, minutes = divmod(DUSK + tick + 1, 60)
    assert eleventh["context"]["world_clock"] == {"minute_of_day": DUSK + tick + 1, "day": 0}
    assert f"It is {hours:02d}:{minutes:02d} on day 1 in the world, and " in _told(eleventh)
    # A world that keeps no clock is told the minute's number, as before.
    plain, _written = _request(ELEVENTH, "society-person-choice/v9")
    assert "world_clock" not in plain["context"]
    assert f"It is minute {tick} in the world, and " in _told(plain)
    # A society that keeps its own clock (a resident day) is told it, whatever the day start.

    def own_clock(state, _ivo):
        state["clock"] = {"start_minute_of_day": 360, "minute_of_day": 1439, "day": 2}

    kept, _written = _request(
        ELEVENTH, "society-person-choice/v9", day_start=DUSK, change=own_clock
    )
    assert kept["context"]["world_clock"] == {"minute_of_day": 0, "day": 3}
    assert "It is 00:00 on day 4 in the world, and " in _told(kept)


def test_the_ninth_catalog_s_request_rebuilds_to_the_byte_whatever_the_day_start():
    ninth, _written = _request(NINTH, "society-person-choice/v8", day_start=DUSK)
    assert "world_clock" not in ninth["context"]
    assert f"It is minute {ninth['context']['tick']} in the world" in _told(ninth)
    assert ninth["document_sha256"] == NINTH_REQUEST_SHA256
    assert _request(NINTH, "society-person-choice/v8")[0] == ninth


def test_every_request_path_states_the_people_s_day_start():
    """A request a path builds without the day start would be told no clock where its rebuild is, so
    every call in the tree states it, the scripts' too, which no suite runs."""
    root = Path(__file__).resolve().parent.parent
    missing = []
    for folder in ("exulanica", "scripts", "tests"):
        for path in sorted((root / folder).rglob("*.py")):
            text = path.read_text()
            if not any(f"{name}(" in text for name in REQUEST_BUILDERS):
                continue
            for node in ast.walk(ast.parse(text)):
                func = node.func if isinstance(node, ast.Call) else None
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name in REQUEST_BUILDERS and not any(
                    keyword.arg in ("day_start", None) for keyword in node.keywords
                ):
                    missing.append(f"{path.relative_to(root)}:{node.lineno}")
    assert missing == []


def test_a_choice_takes_a_name_with_its_capitals_and_nothing_more():
    written = "say something to Ivo Reed (a villager), 3 m away"
    choice = ChoiceRequest(description="d", options=(written, "wait here a minute"))
    assert choice.options[0] == written
    # A placeholder inside a label is refused as one at its end is.
    for refused in (
        'say "hello" to Ivo Reed',
        "say something to Ivo\nReed",
        "follow [Ivo Reed]",
        "say something to [person A], 3 m away",
    ):
        with pytest.raises(ValueError, match="is not a label"):
            ChoiceRequest(description="d", options=(refused, "wait here a minute"))
