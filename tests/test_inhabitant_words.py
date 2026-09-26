"""A simulated person in words: one data file, two readers, one set of cases.

The inspector (``web/packages/app/src/society-inhabitant-words.ts``) and the Companion
(``exulanica/selection/inhabitant_words.py``) read
``assets/catalogs/society-words/society-inhabitant-words.v1.json`` and choose among its words by
the same rule. Both run ``tests/fixtures/society-inhabitant-words/cases.json``; this file runs it
for the server, and ``web/packages/app/test/society-inhabitant-words.test.ts`` for the page. A
change to either side's choice, or to the words, fails one of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from exulanica.selection.inhabitant_words import (
    CATALOG_PATH,
    WordsCatalogRefused,
    inhabitant_words,
    inhabitant_words_catalog,
)
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_planner import (
    REASON_CODES,
    advance_purposeful_society,
    initial_purposeful_society,
)

from living_square_support import DEVELOPMENT_SEEDS, SOCIETY, compose, square_objects

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "society-inhabitant-words" / "cases.json").read_text(
        encoding="utf-8"
    )
)
#: Minutes of the small square run to collect the outcomes it records: long enough that people
#: arrive, rest, visit, stand, talk and leave, measured on the development seeds below.
SQUARE_MINUTES = 90


def _said(case: dict) -> dict:
    words = inhabitant_words(case["person"], CASES["places"].get, CASES["people"].get)
    return {"who": words.who, "what": words.what, "doing": words.doing, "why": words.why}


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["case"] for case in CASES["cases"]])
def test_the_server_says_what_every_shared_case_expects(case):
    assert _said(case) == case["expected"]


def test_the_cases_reach_every_sentence_of_what_a_person_is_doing():
    """A positive control on the cases: each doing sentence is one some case expects."""
    catalog = inhabitant_words_catalog()
    expected = [case["expected"]["doing"] for case in CASES["cases"]]
    for code, template in catalog.tables["doing"].items():
        pattern = re.escape(template)
        for name in ("place", "partner", "still"):
            pattern = pattern.replace(re.escape("{" + name + "}"), ".*")
        assert any(re.fullmatch(pattern, said) for said in expected), code


def test_there_are_words_for_exactly_the_reasons_the_planner_records():
    catalog = inhabitant_words_catalog()
    assert set(catalog.tables["reason"]) == set(REASON_CODES)
    # And the ones an event records that are not a planner's choice are not among them.
    assert not set(catalog.tables["event_reason"]) & set(REASON_CODES)


def test_every_outcome_the_small_square_records_has_words():
    """Read from the society as it runs, so an outcome the planner starts to record fails here."""
    catalog = inhabitant_words_catalog()
    document = compose(square_objects())
    seen: set[str] = set()
    for seed in DEVELOPMENT_SEEDS[:2]:
        state = initial_purposeful_society(
            SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
        )
        for _ in range(SQUARE_MINUTES):
            state, events = advance_purposeful_society(state, seed, [document])
            seen |= {event.document["outcome"] for event in events}
    # A positive control: the run reached the talk the words must never give content to.
    assert {"goal_selected", "talk_started"} <= seen, sorted(seen)
    assert seen <= set(catalog.tables["outcome"]), sorted(seen - set(catalog.tables["outcome"]))


def test_a_reason_with_no_words_is_named_rather_than_guessed():
    catalog = inhabitant_words_catalog()
    assert catalog.reason("nobody_wrote_this") == (
        "of a reason this page has no words for (nobody_wrote_this)"
    )
    assert catalog.reason("sent_away") == "the world's owner sent everyone away"


def test_the_catalog_refuses_an_entry_it_would_misread(tmp_path):
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    unknown = json.loads(json.dumps(document))
    unknown["entries"].append({**unknown["entries"][0], "kind": "mood", "key": "mood.restore_need"})
    twice = json.loads(json.dumps(document))
    twice["entries"].append(twice["entries"][0])
    for name, broken, message in (
        ("unknown.json", unknown, "unknown kind"),
        ("twice.json", twice, "stated twice"),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(WordsCatalogRefused, match=message):
            inhabitant_words_catalog(path)
