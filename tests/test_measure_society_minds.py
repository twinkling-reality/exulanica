"""The minds measurement judges by the rule its pre-registration states, builds every family's case
on this tree with the two arms differing only in what the being notices and remembers, and asks no
model unless the tree, the script and the contexts are the ones its pre-registration binds."""

from __future__ import annotations

import dataclasses
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_society_minds as minds
import measure_society_person_models as person_models

SCRIPT = Path(minds.__file__).read_bytes()
BLOCKS = ("surroundings", "remembers")


def _asked(model: str, arm: str, facts_correct: int, gives_correct: int) -> list[dict]:
    """Twenty fact answers and twenty give_asked answers of ``model`` in ``arm``, all valid."""
    facts = [
        {
            "model_id": model,
            "arm": arm,
            "family": minds.FACT_FAMILIES[index % len(minds.FACT_FAMILIES)],
            "correct": index < facts_correct,
            "valid": True,
        }
        for index in range(20)
    ]
    gives = [
        {
            "model_id": model,
            "arm": arm,
            "family": "give_asked",
            "correct": index < gives_correct,
            "valid": True,
        }
        for index in range(20)
    ]
    return facts + gives


def test_an_answer_is_judged_by_the_rule_both_sets_were_preregistered_under():
    # The rule's figures as both pre-registrations state them; shares move in twentieths below.
    assert Decimal("0.15") == minds.HELPS_BY
    assert Decimal("0.05") == minds.NO_HARM_SLACK
    calls = [
        # Fact 0.25 against 0.10, no variation: exactly the margin, which is not more than it.
        # Give 0.95 against 1.00: exactly the slack, which is no harm.
        *_asked("at", "with", 5, 19),
        *_asked("at", "without", 2, 20),
        *_asked("at", "without_again", 2, 20),
        # One more fact answer right helps; one more give answer wrong harms.
        *_asked("past", "with", 6, 18),
        *_asked("past", "without", 2, 20),
        *_asked("past", "without_again", 2, 20),
        # 0.35 against 0.10 would help with no variation; the control varies by 0.10, which
        # raises the margin to 0.25, so it does not.
        *_asked("varies", "with", 7, 20),
        *_asked("varies", "without", 2, 20),
        *_asked("varies", "without_again", 4, 20),
    ]
    found = minds.verdicts(calls)["models"]
    assert {model: (v["helps"], v["does_no_harm"]) for model, v in found.items()} == {
        "at": (False, True),
        "past": (True, False),
        "varies": (False, True),
    }
    assert minds.verdicts(calls)["overall_helps"] is False
    fact = {"family": "who_gave", "words": ["café", "knight"], "asker_id": "a"}
    assert minds.correct(fact, {"line": "The KNIGHT gave it to me."})
    assert minds.correct(fact, {"line": "By the café table."})
    assert not minds.correct(fact, {"line": "I do not recall."})
    give = {"family": "give_asked", "words": [], "asker_id": "a"}
    assert minds.correct(give, {"option": {"kind": "give", "addressee_id": "a"}})
    assert not minds.correct(give, {"option": {"kind": "say_to"}, "line": "Here you go."})


def test_every_family_builds_a_case_whose_arms_differ_only_by_what_the_being_notices_and_remembers(
    monkeypatch,
):
    monkeypatch.setattr(minds, "ACTIVE", minds.SETS["held-out"])
    for family, build in minds.BUILDERS.items():
        case = build(0)
        with_blocks, without = case["contexts"]["with"], case["contexts"]["without"]
        assert set(BLOCKS) <= set(with_blocks), family
        assert {key: value for key, value in with_blocks.items() if key not in BLOCKS} == without
        assert family == "give_asked" or minds._shown(case["words"], with_blocks), family
        assert not minds._shown(case["words"], minds._question(with_blocks)), family


@pytest.fixture(name="registered")
def _registered(tmp_path, monkeypatch):
    """A set whose records go under ``tmp_path``, pre-registered on a tree, this script and its
    contexts as ``preregister`` binds them."""
    for module in (minds, person_models):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(minds, "ACTIVE", dataclasses.replace(minds.SETS["held-out"], output="sets"))
    tree = {"head": "a" * 40, "files_sha256": {"scripts/measure_society_minds.py": "b" * 64}}
    monkeypatch.setattr(minds, "_tree", lambda: json.loads(json.dumps(tree)))
    paths = minds._paths()
    (tmp_path / "sets").mkdir()
    (tmp_path / paths["contexts"]).write_bytes(b'{"cases": []}')
    person_models._write_new(
        paths["preregistration"],
        {
            "tree": tree,
            "script_sha256": minds._sha256(SCRIPT),
            "contexts_sha256": minds._sha256(b'{"cases": []}'),
        },
    )
    return tree, paths


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (None, None),
        ("head", "the tree is not the pre-registered one"),
        ("file", "the tree is not the pre-registered one"),
        ("script", "the bytes running are not the pre-registered script"),
        ("contexts", "the contexts are not the ones the pre-registration binds"),
        ("record", "record.json exists"),
    ],
)
def test_no_model_is_asked_unless_the_tree_script_and_contexts_are_the_registered_ones(
    registered, tmp_path, monkeypatch, change, refusal
):
    tree, paths = registered
    running = SCRIPT
    if change == "head":
        monkeypatch.setattr(minds, "_tree", lambda: {**tree, "head": "c" * 40})
    elif change == "file":
        changed = {**tree["files_sha256"], "exulanica/world/society_things.py": "d" * 64}
        monkeypatch.setattr(minds, "_tree", lambda: {**tree, "files_sha256": changed})
    elif change == "script":
        running = SCRIPT + b"\n"
    elif change == "contexts":
        (tmp_path / paths["contexts"]).write_bytes(b'{"cases": [{}]}')
    elif change == "record":
        (tmp_path / paths["record"]).write_text("{}", encoding="utf-8")
    if refusal is None:
        found, measured, contexts = minds.admitted(running)
        assert (found["tree"], measured, contexts) == (tree, tree, b'{"cases": []}')
    else:
        with pytest.raises(SystemExit, match=refusal):
            minds.admitted(running)
