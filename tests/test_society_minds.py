"""A society of things' minds notice what is around them and remember what happened, by rule.

A society records, in its first input, the modules it runs. One made since the notice and memory
modules shows each being a model or a program decides for what it notices and what it remembers,
and its minute keeps that memory; one whose first input records the earlier modules is asked and
played exactly as before. Real minutes of a society of things, in memory; expected values from
the options the decision contract builds and the receipts this file writes.
"""

from __future__ import annotations

import copy
import json
import uuid

from exulanica.abilities.registry import NOTICE, REMEMBER
from exulanica.world.role_decisions import DecisionDisposition
from exulanica.world.society_decision_contract import (
    choice_options,
    decision_context,
    person_role,
    situation,
)
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
    validate_things_state,
)

from things_society_support import SEED, SOCIETY, arrival, compose, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 2, 3_000, 3_000)
#: The modules a society of things recorded before the notice and memory modules were built.
EARLIER = [
    "exulanica-ability/crossing/v1",
    "exulanica-ability/hands/v1",
    "exulanica-ability/purposeful/v1",
    "exulanica-ability/say/v1",
]


def _contract():
    role = person_role()
    return role.contract(role.terms(THINGS_PROFILE).versions)


def _receipt(person, option, *, line=None):
    proposal = {"label": option.label, "option": option.as_record()}
    if line is not None:
        proposal["line"] = line
    receipt = {
        "subject_id": person["id"],
        "request_id": str(uuid.uuid4()),
        "status": "accepted",
        "reason": "validated_choice",
        "proposal": proposal,
        "provider": {"provider": "test", "model_id": "m"},
    }
    return receipt, DecisionDisposition(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=person["id"],
        disposition="applied",
        reason="validated_choice",
        decision_sha256="0" * 64,
    )


def _minute(state, document, decisions=(), crossings=()):
    planned, events = advance_purposeful_society(state, SEED, [document])
    after, events, _ = advance_things(
        state, planned, SEED, document, events, crossings, decisions=decisions
    )
    return after, events


def _earlier(document):
    """``document`` as a first input written before the notice and memory modules were built."""
    earlier = copy.deepcopy(document)
    earlier["modules"] = list(EARLIER)
    earlier["document_sha256"] = input_sha256(earlier)
    return earlier


def _spoken(document):
    """The knight, with a villager 2 m east, says a line to it in the first minute."""
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    near = next(p for p in state["inhabitants"] if p["came_by"] == "populated")
    near["position_mm"] = [knight["position_mm"][0] + 2_000, knight["position_mm"][1]]
    options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
    said = next(o for o in options if o.kind == "say_to" and o.addressee_id == near["id"])
    after, _ = _minute(state, document, [_receipt(knight, said, line="Well met.")])
    return after, knight, near, said


def test_a_new_society_records_the_notice_and_memory_modules():
    document = compose((GATE, KNIGHT))
    assert {NOTICE, REMEMBER} <= set(document["modules"])
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    assert {NOTICE, REMEMBER} <= set(state["modules"])


def test_a_being_a_model_decides_for_is_shown_what_it_notices_and_remembers():
    document = compose((GATE, KNIGHT))
    after, knight, near, said = _spoken(document)
    # The knight's model chose that line, so it remembers saying it to the villager; the villager,
    # whom only the routine decides for, keeps nothing.
    [met] = next(p for p in after["inhabitants"] if p["id"] == knight["id"])["recollection"]["met"]
    assert (met["id"], met["how"]) == (near["id"], ["you_spoke_to"])
    assert "recollection" not in next(p for p in after["inhabitants"] if p["id"] == near["id"])
    options = choice_options(after, document, knight["id"], _contract(), seed=SEED)
    context = decision_context(after, document, knight["id"], options)
    who = said.label.removeprefix("say something to ").rsplit(", ", 1)[0]
    assert who in [being["who"] for being in context["surroundings"]["beings"]]
    [remembered] = context["remembers"]["beings"]
    assert remembered["who"] == who
    # The line is already shown among the lines it said, so it is not shown twice.
    assert [line["line"] for line in context["said"]] == ["Well met."]
    assert "your_line" not in remembered
    lines = situation(context)
    assert "Around you now:" in lines
    heading = next(i for i, line in enumerate(lines) if line.startswith("You remember"))
    assert lines[heading + 1].startswith(f"- {who}: you met just now; you spoke to it")
    validate_things_state(after)


def test_a_society_whose_first_input_records_the_earlier_modules_is_asked_as_before():
    document = _earlier(compose((GATE, KNIGHT)))
    after, knight, _near, _said = _spoken(document)
    assert after["modules"] == EARLIER
    assert all("recollection" not in person for person in after["inhabitants"])
    options = choice_options(after, document, knight["id"], _contract(), seed=SEED)
    context = decision_context(after, document, knight["id"], options)
    assert "surroundings" not in context and "remembers" not in context
    # The positive control: the same scene in a society made since does show both.
    later, knight, _near, _said = _spoken(compose((GATE, KNIGHT)))
    options = choice_options(later, compose((GATE, KNIGHT)), knight["id"], _contract(), seed=SEED)
    shown = decision_context(later, compose((GATE, KNIGHT)), knight["id"], options)
    assert "surroundings" in shown and "remembers" in shown


def test_a_visitor_its_own_program_decides_for_remembers_from_its_arrival():
    document = compose((GATE, KNIGHT))
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    after, _ = _minute(state, document, crossings=[arrival(1)])
    visitor = next(p for p in after["inhabitants"] if p["came_by"] == "crossed")
    assert visitor["recollection"] == {"met": [], "places": [], "handed": []}


def test_a_being_only_the_routine_decides_for_keeps_no_memory_however_long_it_lives():
    document = compose((GATE, KNIGHT))
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    for _ in range(30):
        state, _ = _minute(state, document)
    assert all("recollection" not in person for person in state["inhabitants"])


def test_a_recollection_in_a_society_without_the_memory_module_is_refused_by_name():
    document = _earlier(compose((GATE, KNIGHT)))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    state["inhabitants"][0]["recollection"] = {"met": [], "places": [], "handed": []}
    try:
        validate_things_state(state)
    except ValueError as exc:
        assert "only a society running memory keeps a recollection" in str(exc)
    else:
        raise AssertionError("a recollection without the memory module was accepted")


def _two_lines(document):
    """The knight says a line to one villager, then to another, each placed beside it."""
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    first, second = [p for p in state["inhabitants"] if p["came_by"] == "populated"][:2]
    for listener, line in ((first, "Well met."), (second, "Good day.")):
        here = next(p for p in state["inhabitants"] if p["id"] == knight["id"])["position_mm"]
        near = next(p for p in state["inhabitants"] if p["id"] == listener["id"])
        near["position_mm"] = [here[0] + 2_000, here[1]]
        options = choice_options(state, document, knight["id"], _contract(), seed=SEED)
        said = next(o for o in options if o.kind == "say_to" and o.addressee_id == listener["id"])
        state, _ = _minute(state, document, [_receipt(knight, said, line=line)])
    return next(p for p in state["inhabitants"] if p["id"] == knight["id"])["recollection"]


def test_a_society_reads_the_figures_of_the_memory_version_it_recorded(monkeypatch, tmp_path):
    """A later row of a module never changes a society that recorded an earlier one: a society
    that recorded a second memory version keeping one being keeps one, and one that recorded the
    first keeps both."""
    from exulanica.abilities import registry

    # Both inputs are written before the second version exists, as a stored society's was; a new
    # input would record the newest version.
    recorded_first = compose((GATE, KNIGHT))
    recorded_second = copy.deepcopy(recorded_first)
    recorded_second["modules"] = sorted(
        "exulanica-ability/remember/v2" if module == REMEMBER else module
        for module in recorded_second["modules"]
    )
    recorded_second["document_sha256"] = input_sha256(recorded_second)
    table = json.loads(registry.MODULES_PATH.read_text(encoding="utf-8"))
    [first] = [row for row in table["modules"] if row["module"] == REMEMBER]
    second = copy.deepcopy(first)
    second["module"] = "exulanica-ability/remember/v2"
    for parameter in second["parameters"]:
        if parameter["name"] == "beings_maximum":
            parameter["value"] = 1
    table["modules"].append(second)
    path = tmp_path / "ability-modules.v1.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setattr(registry, "ability_modules", lambda: registry.load_ability_modules(path))
    assert len(_two_lines(recorded_first)["met"]) == 2
    assert len(_two_lines(recorded_second)["met"]) == 1
