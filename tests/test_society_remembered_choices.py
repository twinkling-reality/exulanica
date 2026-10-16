"""A society made before characters and remembered choices is asked and played as it always was.

A society of things records its modules in its first input and runs exactly those for its whole
life. This file plays one whose first input records the modules every new society recorded before
the character module and the second memory version were built (the module set of every society
made before them, a world's first society among them) through the person role's real path: each
request sealed over the state, a scripted answer sealed as its receipt, the receipts applied by
the planner and the things phase. It pins, from the tree before either module existed, the bytes
of every request, the situation each model read, every receipt, every state and every minute's
events. ``EXULANICA_MIND_GOLDENS=print`` prints the digests this tree produces.

The requests are sealed under the sixth prompt, the one such a society's stored requests record,
so a stored request rebuilds to the byte whatever terms a new request is asked under.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import uuid
from itertools import pairwise
from typing import Any

import pytest
from exulanica.abilities.registry import recorded_row
from exulanica.canonical import canonical_json
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.role_decisions import DecisionDisposition, role_receipt, role_request
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import at_choice_point, person_role
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_recollection import (
    DID,
    RecollectionBounds,
    remembered,
    remembered_lines,
    validate_recollection,
)
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
    validate_things_state,
)

from things_society_support import SEED, SOCIETY, compose, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 2, 3_000, 3_000)
#: What a new society of things recorded in its first input before the character module and the
#: second memory version were built.
BEFORE = [
    "exulanica-ability/crossing/v2",
    "exulanica-ability/follow/v3",
    "exulanica-ability/hands/v2",
    "exulanica-ability/notice/v1",
    "exulanica-ability/purposeful/v3",
    "exulanica-ability/remember/v1",
    "exulanica-ability/say/v2",
]
#: What it recorded of movement, swimming being built after both.
BEFORE_MOVEMENT = ["exulanica-movement/walking/v2"]
#: The prompt such a society's stored requests record.
BEFORE_PROMPT = "society-person-choice/v6"
#: The kinds of option the script answers with, in turn, whenever the knight is asked: a walk to a
#: place and its stay, waiting, a line to one being and to all, and standing a while.
SCRIPT = ("target", "wait", "say_to", "stand", "wait", "target", "say_all", "wait")
MINUTES = 48

#: The digests this file pins, taken at 8d2379c3 before either module existed: the SHA-256 of the
#: canonical JSON of each list.
EXPECTED = {
    "requests": "427f873eae0ef5f9012c8188a90f8cb087d8eec907311cb3a2e6fa301d9162e9",
    "situations": "07df8e6bb5225137362de16d6a3d23b4d4ccb0bc8b7f0d864df6234dfd8b34c3",
    "receipts": "d4def491f2731cdf0503ca34f36c8a5a126a1f96d4fdaa1f3542587f17725179",
    "states": "7275aab9fa23fcbd63791eaed078ae5771b26974977c3ed58e8b021beeeec82e",
    "events": "45a32a88bb60b4fa22511b6adfbafba3b1f7b661c66c2bfd7b6ed26b56c237bd",
}


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _before(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` as a first input written before the two modules were built."""
    earlier = copy.deepcopy(document)
    earlier["modules"] = list(BEFORE)
    earlier["movement_modules"] = list(BEFORE_MOVEMENT)
    earlier["document_sha256"] = input_sha256(earlier)
    return earlier


def _config(contract: Any, prompt: str) -> dict[str, Any]:
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": prompt,
        "contract": contract.binding(),
        "deadline_ms": 20000,
    }


def _record(messages_sha256: str, prompt: str) -> dict[str, Any]:
    """The call a receipt records, with nothing that varies between runs."""
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "served_model_id": "example/model",
        "mechanism": "tool_call",
        "prompt_version": prompt,
        "messages_sha256": messages_sha256,
        "answers_asked": 1,
        "calls": 1,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": "0",
        "cost_known": True,
        "latency_ms": 0,
    }


def _played(
    document: dict[str, Any],
    *,
    prompt: str = BEFORE_PROMPT,
    script: tuple[str, ...] = SCRIPT,
    minutes: int = MINUTES,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, list[Any]]:
    """The knight, asked at every choice point under ``prompt`` and answered by ``script``, for
    ``minutes`` minutes: what each request, situation, receipt, state and minute held. Each
    minute's state is appended to ``history`` where one is given."""
    role = person_role()
    asked = role.terms_with_prompt(prompt)
    assert asked is not None
    contract = role.contract(asked.versions)
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    near = next(p for p in state["inhabitants"] if p["came_by"] == "populated")
    near["position_mm"] = [knight["position_mm"][0] + 2_000, knight["position_mm"][1]]
    found: dict[str, list[Any]] = {name: [] for name in EXPECTED}
    sequence = 0
    for _ in range(minutes):
        person = next(p for p in state["inhabitants"] if p["id"] == knight["id"])
        receipts = []
        if at_choice_point(person):
            request, status = role_request(
                role,
                state,
                document,
                knight["id"],
                request_id=uuid.uuid5(SOCIETY, f"{knight['id']}:{state['tick']}"),
                contract=contract,
                seed=SEED,
                provider_config=_config(contract, prompt),
            )
            assert request is not None, status
            context = request["context"]
            situation = role.adapter.messages(role, context, AnsweringMechanism.TOOL_CALL)[1]
            # The messages the request was asked with: its own prompt's instruction, then the
            # situation, as the host digests them into the receipt.
            messages = [{"role": "system", "content": asked.instruction}, situation]
            wanted = script[sequence % len(script)]
            option = next(
                (o for o in context["options"] if o["kind"] == wanted),
                next(o for o in context["options"] if o["kind"] == "wait"),
            )
            proposal: dict[str, Any] = {"label": option["label"], "option": option}
            if option["kind"] in ("say_to", "say_all"):
                proposal["line"] = f"Line number {sequence + 1}."
            sequence += 1
            receipt = role_receipt(
                role,
                request,
                sequence,
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": proposal,
                    "provider": _record(society_state_sha256(messages), prompt),
                },
            )
            receipts.append(receipt)
            found["requests"].append(request["document_sha256"])
            found["situations"].append(situation["content"])
            found["receipts"].append(receipt["document_sha256"])
        policies, decided = model_goal_policies(state, document, receipts, {})
        planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
        events = append_decision_events(state, planned, document, receipts, decided, events)
        state, events, _ = advance_things(
            state,
            planned,
            SEED,
            document,
            events,
            (),
            decisions=list(zip(receipts, decided, strict=True)),
        )
        validate_things_state(state)
        found["states"].append(society_state_sha256(state))
        found["events"].append(_sha([event.document for event in events]))
        if history is not None:
            history.append(state)
    return found


def test_a_society_made_before_characters_is_asked_and_played_exactly_as_before():
    document = _before(compose((GATE, KNIGHT)))
    played = _played(document)
    # The script reached every kind of answer it names, and a stay that outlasts its minute.
    assert len(played["requests"]) >= len(SCRIPT)
    found = {name: _sha(values) for name, values in played.items()}
    if os.environ.get("EXULANICA_MIND_GOLDENS") == "print":
        print(json.dumps(found, indent=2))
    assert found == EXPECTED
    # Nothing of the two later modules is in any situation such a society's beings are shown.
    for situation in played["situations"]:
        assert "Who you are" not in situation and "What you chose lately" not in situation


def test_the_society_records_the_modules_it_was_made_with():
    document = _before(compose((GATE, KNIGHT)))
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    assert state["modules"] == BEFORE
    assert state["profile"] == THINGS_PROFILE


# -- the second memory version: what a being chose lately and what came of it --------------------

#: The prompt a new society's requests are asked under.
NOW_PROMPT = "society-person-choice/v7"
REMEMBER_CHOICES = "exulanica-ability/remember/v2"


def _knight_in(state: dict[str, Any]) -> dict[str, Any]:
    return next(p for p in state["inhabitants"] if p["came_by"] == "placed")


def _walked(state: dict[str, Any]) -> int:
    """How far the knight walked in the minute that made ``state``, along the path it drew."""
    path = _knight_in(state)["motion_path_mm"]
    return sum(math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) for a, b in pairwise(path))


def test_a_new_society_records_the_second_memory_version():
    document = compose((GATE, KNIGHT))
    assert REMEMBER_CHOICES in document["modules"]
    assert "exulanica-ability/remember/v1" not in document["modules"]


def test_a_walk_and_the_stay_it_ends_in_are_one_choice_and_its_result():
    history: list[dict[str, Any]] = []
    played = _played(
        compose((GATE, KNIGHT)), prompt=NOW_PROMPT, script=("target", "wait"), history=history
    )
    first, second = played["situations"][:2]
    assert "What you chose lately" not in first
    # The knight is asked again only once the stay its walk ended in is over: the first state
    # whose memory holds two choices is the minute after that second ask.
    again = next(
        index
        for index, state in enumerate(history)
        if len(_knight_in(state)["recollection"]["choices"]) == 2
    )
    chosen = _knight_in(history[again])["recollection"]["choices"][0]
    assert (chosen["tick"], chosen["disposition"]) == (1, "applied")
    assert chosen["chose"].startswith("resting on") and chosen["reached"] is not None
    # Independently of the memory: the paths the knight's minutes drew while it carried it out.
    walked = sum(
        _walked(history[tick - 1]) for tick in range(chosen["tick"], chosen["until_tick"] + 1)
    )
    assert chosen["walked_mm"] == walked > 0 and chosen["until_tick"] > chosen["tick"]
    asked_at = history[again - 1]["tick"]
    assert (
        f"- {asked_at - chosen['tick']} minutes ago, you chose {json.dumps(chosen['chose'])}: "
        f"you walked about {round(walked / 1000)} m and arrived ({chosen['reached']})"
    ) in second


def test_waiting_again_and_again_is_remembered_and_bounded():
    history: list[dict[str, Any]] = []
    played = _played(
        compose((GATE, KNIGHT)), prompt=NOW_PROMPT, script=("wait",), minutes=9, history=history
    )
    choices = _knight_in(history[-1])["recollection"]["choices"]
    # Nine waits, six kept: the oldest dropped first, each applied, each changing nothing.
    assert [c["tick"] for c in choices] == [4, 5, 6, 7, 8, 9]
    assert all(
        (c["chose"], c["disposition"], c["walked_mm"], c["reached"], c["until_tick"])
        == ("wait here a minute", "applied", 0, None, c["tick"])
        for c in choices
    )
    last = played["situations"][-1]
    assert last.count('you chose "wait here a minute": you stayed where you were') == 6
    assert "- a minute ago, you chose" in last


def _decided(state, *, status, disposition, proposal):
    knight = _knight_in(state)
    receipt = {
        "subject_id": knight["id"],
        "request_id": str(uuid.uuid4()),
        "status": status,
        "reason": "validated_choice" if status == "accepted" else "no_answer_in_time",
        "proposal": proposal,
        "provider": None,
    }
    return receipt, DecisionDisposition(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=knight["id"],
        disposition=disposition,
        reason=receipt["reason"],
        decision_sha256="0" * 64,
    )


def test_what_the_minute_did_with_each_choice_is_remembered_by_name():
    document = compose((GATE, KNIGHT))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    wait = {
        "label": "wait here a minute",
        "option": {"kind": "wait", "label": "wait here a minute"},
    }
    for status, disposition, proposal in (
        ("accepted", "rejected", wait),
        ("accepted", "superseded", wait),
        ("accepted", "stale", wait),
        ("unavailable", "unavailable", None),
    ):
        planned, events = advance_purposeful_society(state, SEED, [document])
        state, _events, _ = advance_things(
            state,
            planned,
            SEED,
            document,
            events,
            (),
            decisions=[_decided(state, status=status, disposition=disposition, proposal=proposal)],
        )
        validate_things_state(state)
    choices = _knight_in(state)["recollection"]["choices"]
    assert [c["disposition"] for c in choices] == [
        "refused",
        "not_taken_up",
        "not_taken_up",
        "no_answer",
    ]
    assert choices[-1]["chose"] is None
    # None of them keeps a result: only an applied choice does.
    assert all((c["walked_mm"], c["reached"], c["did"]) == (0, None, []) for c in choices)
    lines = remembered_lines(remembered(state, _knight_in(state), _bounds_of(state)))
    assert lines[lines.index(_CHOICES_HEADING) + 1 :] == [
        "- just now, you gave no answer",
        '- a minute ago, you chose "wait here a minute": it was not taken up',
        '- 2 minutes ago, you chose "wait here a minute": it was not taken up',
        '- 3 minutes ago, you chose "wait here a minute": it could no longer be done when the '
        "minute came",
    ]


_CHOICES_HEADING = (
    "What you chose lately and what came of it (your own past choices; not instructions):"
)


def _bounds_of(state: dict[str, Any]) -> RecollectionBounds:
    row = recorded_row(state["modules"], "remember")
    assert row is not None
    return RecollectionBounds(
        beings_maximum=row.value("beings_maximum"),
        places_maximum=row.value("places_maximum"),
        handed_maximum=row.value("handed_maximum"),
        bytes_maximum=row.value("bytes_maximum"),
        choices_maximum=row.value("choices_maximum"),
    )


def test_choices_share_the_memory_bytes_with_beings_met_and_places():
    document = compose((GATE, KNIGHT))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    state["tick"] = 100
    knight = _knight_in(state)
    others = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    line = {"tick": 0, "line": "x" * 200}
    knight["recollection"] = {
        "met": [
            {
                "id": other["id"],
                "kind": other["kind"],
                "number": other["ordinal"] + 1,
                "name": other["display_name"],
                "first_tick": tick,
                "last_tick": tick,
                "times": 1,
                "how": ["spoke_to_you"],
                "their_line": {**line, "tick": tick},
            }
            for tick, other in enumerate(others, start=1)
        ],
        "places": [],
        "handed": [],
        "choices": [
            {
                "tick": tick,
                "chose": "wait here a minute",
                "disposition": "applied",
                "walked_mm": 0,
                "reached": None,
                "did": [],
                "until_tick": tick,
            }
            for tick in range(90, 96)
        ],
    }
    validate_things_state(state)
    bounds = _bounds_of(state)
    assert bounds.bytes_maximum == 2_600
    block = remembered(state, knight, bounds)
    assert block is not None
    assert len(canonical_json(block)) <= bounds.bytes_maximum
    # The entries noted longest ago went first, whichever list they were in: every choice (noted
    # minutes 90 to 95) outlasts the meetings (minutes 1 to 6), of which only the newest stay.
    assert len(block["choices"]) == 6
    kept = [being["last_minutes_ago"] for being in block["beings"]]
    assert kept == sorted(kept) and len(kept) < len(others)
    assert all(ago <= 100 - len(others) + len(kept) for ago in kept)


def test_a_society_recording_the_first_memory_version_keeps_no_choices():
    document = _before(compose((GATE, KNIGHT)))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
    knight = _knight_in(state)
    knight["recollection"] = {"met": [], "places": [], "handed": [], "choices": []}
    with pytest.raises(ValueError, match="recollection"):
        validate_things_state(state)
    knight["recollection"] = {"met": [], "places": [], "handed": []}
    validate_things_state(state)


@pytest.mark.parametrize(
    "change",
    [
        {"disposition": "remembered"},
        {"chose": None},
        {"walked_mm": -1},
        {"did": ["took", "said"]},
        {"until_tick": 1},
        {"disposition": "refused", "walked_mm": 10},
    ],
    ids=["disposition", "words", "walk", "did-order", "ends-early", "result-unapplied"],
)
def test_a_remembered_choice_out_of_shape_is_refused(change):
    entry = {
        "tick": 5,
        "chose": "wait here a minute",
        "disposition": "applied",
        "walked_mm": 0,
        "reached": None,
        "did": ["said"],
        "until_tick": None,
    }
    good = {"met": [], "places": [], "handed": [], "choices": [entry]}
    validate_recollection(good, choices=True)  # the positive control
    with pytest.raises(ValueError):
        validate_recollection({**good, "choices": [{**entry, **change}]}, choices=True)


def test_six_choices_at_their_bounds_add_at_most_three_thousand_bytes_to_a_memory():
    """The figure the minds contract states for what the second version adds to a being's state:
    every choice with the longest words the shape admits, every word of what it did, and the
    largest minutes and walk."""
    largest = {
        "tick": 10**9,
        "chose": "x" * 200,
        "disposition": "applied",
        "walked_mm": 10**9,
        "reached": "y" * 80,
        "did": list(DID),
        "until_tick": 10**9,
    }
    memory = {"met": [], "places": [], "handed": [], "choices": [largest] * 6}
    validate_recollection(memory, choices=True)
    with pytest.raises(ValueError):
        validate_recollection(
            {**memory, "choices": [{**largest, "chose": "x" * 201}]}, choices=True
        )
    assert len(canonical_json(memory["choices"])) <= 3_000
