"""Names keep their capitals in what a model is told and in its choices, from action catalog v9.

A request asked under the ninth action catalog names a being as the page names it, capitals kept:
in its options, in what the being notices and in what it remembers, each read from the request's own
contract. One asked under the eighth names it in lowercase words, as every stored request was asked,
so a stored request rebuilds to the byte. The names expected here come from the page's own naming
(page_name) and the state this file writes; the eighth request's digest was taken on the code
before the ninth catalog.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.models.choice import ChoiceRequest
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.role_decisions import role_request
from exulanica.world.society_decision_contract import choice_options, page_name, person_role
from exulanica.world.society_recollection import remembered
from exulanica.world.society_surroundings import surroundings
from exulanica.world.society_things import THINGS_PROFILE

import test_society_recollection as recollection
import test_society_surroundings as noticing
from things_society_support import SEED

EIGHTH = {"society-decision-action": 8, "society-decision-policy": 8}
NINTH = {"society-decision-action": 9, "society-decision-policy": 8}
#: The eighth catalog's request for the knight of :func:`_named_square`, as the code before the
#: ninth catalog sealed it.
EIGHTH_REQUEST_SHA256 = "6a68dbad97b7992199b1b53a734f2f14647b3608020d366b3605caa2660e330b"


def _named_square():
    """The square, its nearest villager named Ivo Reed as a person would write it."""
    state, document, knight, _spirit, villagers = noticing._square()
    villagers[0]["display_name"] = "Ivo Reed"
    return state, document, knight, villagers[0]


def _request(versions, prompt):
    state, document, knight, ivo = _named_square()
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
    )
    assert status == "in_progress"
    return request, page_name(ivo, state)


def test_a_new_request_is_asked_under_the_ninth_catalog_with_both_label_rules():
    role = person_role()
    terms = role.terms(THINGS_PROFILE)
    assert (terms.versions, terms.prompt_version) == (NINTH, "society-person-choice/v8")
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


def test_a_choice_takes_a_name_with_its_capitals_and_nothing_more():
    written = "say something to Ivo Reed (a villager), 3 m away"
    choice = ChoiceRequest(description="d", options=(written, "wait here a minute"))
    assert choice.options[0] == written
    for refused in ('say "hello" to Ivo Reed', "say something to Ivo\nReed", "follow [Ivo Reed]"):
        with pytest.raises(ValueError, match="is not a label"):
            ChoiceRequest(description="d", options=(refused, "wait here a minute"))
