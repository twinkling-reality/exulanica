"""No words a person reads from the server call a person, a day or a minute simulated, or what
happens a simulation.

People are invented for this world, and a moment is the world's own, said by its clock or its
minute. This reads the Companion's own sentences, the playback refusals the page shows and the
summaries the engines write: every string constant of their modules but docstrings, holding the
prose among them to that. A code is not prose. Text only a model reads is kept as its prompts were
written. A summary an engine records stays as its version wrote it (a record is never rewritten),
granted only while its module still runs that version, so a new version's words are checked. The
actions catalog's newest version, the one the readers serve, is held here too: its labels, hints and
reasons. The words catalog has its own check (``tests/test_inhabitant_words.py``).
"""

from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path

import pytest
from exulanica.world import action_catalog
from exulanica.world.society_engines import society_engine

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "exulanica/selection/society_question.py",
    "exulanica/selection/question.py",
    "exulanica/api/society_control_worker.py",
    "exulanica/api/services.py",
)
#: Text only a model reads: the planner's line of the people in view, the composer's packet header.
MODEL_TEXT = frozenset({"simulated people are in view.", "SIMULATION EVENTS"})
#: The summaries each engine records into a society's state and events, by module: the version it
#: runs (the module's own constant), and the exact words that version writes.
RECORDED = {
    "exulanica/world/society_planner.py": (
        ("exulanica.world.society_planner", "PURPOSEFUL_PROFILE", "exulanica-society/v2"),
        {"Simulated inhabitant awaiting its first goal."},
    ),
    "exulanica/world/society_model_decisions.py": (
        ("exulanica.world.society_planner", "PURPOSEFUL_PROFILE", "exulanica-society/v2"),
        {"Someone no longer here (simulated)"},
    ),
    "exulanica/world/society_social.py": (
        ("exulanica.world.society_social", "SOCIAL_PROFILE", "exulanica-society/v3"),
        {"{} (simulated): {}."},
    ),
    "exulanica/world/society_living.py": (
        ("exulanica.world.society_living", "LIVING_TOWN_PROFILE", "exulanica-society/v5"),
        {"Simulated inhabitant awaiting its first choice.", "A {} (simulated): {}; {}."},
    ),
    "exulanica/world/society_living_decisions.py": (
        ("exulanica.world.society_living", "LIVING_TOWN_PROFILE", "exulanica-society/v5"),
        {"A {} (simulated): the {}'s decision was {}; {}."},
    ),
    "exulanica/world/society_presence.py": (
        (
            "exulanica.world.society_presence",
            "PRESENCE_REQUEST_PROFILE",
            "exulanica.society-presence/v1",
        ),
        {
            "{} (simulated) left: the world's owner sent everyone away.",
            "{} (simulated) arrived: the world's owner brought everyone back.",
        },
    ),
    "exulanica/world/society_things.py": (
        ("exulanica.world.society_things", "THINGS_PROFILE", "exulanica-society/v7"),
        {"Simulated inhabitant awaiting its first goal."},
    ),
    # The legacy engine plays no more minutes, so it writes no new words while it stays refused.
    "exulanica/world/society_legacy.py": (None, {"{} departed for {} on the simulated schedule."}),
}
#: The words themselves, never part of a code's name ("SIMULATED_PLACEHOLDER", "not_simulated").
SAYS = re.compile(r"(?<![-\w])simulat(?:ed|ion)(?![-\w])", re.IGNORECASE)
PROSE = re.compile(r"[A-Za-z]+[ ,:()·]+[A-Za-z]")


def _strings(source: str) -> list[str]:
    """The strings a module writes, its docstrings left out; an f-string with its holes as {}."""
    tree = ast.parse(source)
    skipped = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    # An f-string's own words are read whole, with its holes, not again piece by piece.
    skipped |= {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            found.append(
                "".join(p.value if isinstance(p, ast.Constant) else "{}" for p in node.values)
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            found.append(node.value)
    return found


def _said(source: str) -> list[str]:
    """The prose that says either word; a hole reads as a word ("{} (simulated): {}.")."""
    return [
        text
        for text in _strings(source)
        if PROSE.search(text.replace("{}", "x")) and SAYS.search(text)
    ]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_no_words_the_server_says_to_a_person_call_anyone_simulated():
    written = {name: _strings(_read(name)) for name in MODULES}
    # The positive control: the scan reads the refusals and the Companion's sentences as written.
    assert (
        "This server does not advance worlds on their own. Advance one minute at a time."
        in written["exulanica/api/society_control_worker.py"]
    )
    assert any("invented for this world" in text for text in written[MODULES[0]])
    said = [
        (name, text) for name in MODULES for text in _said(_read(name)) if text not in MODEL_TEXT
    ]
    assert said == []


def test_the_newest_actions_catalog_calls_no_one_simulated():
    # Versions run 1 to N with none missing (the loader refuses a gap), so N is the newest.
    count = len(list(action_catalog.DIRECTORY.glob("actions.v*.json")))
    newest = json.loads(
        (action_catalog.DIRECTORY / f"actions.v{count}.json").read_text(encoding="utf-8")
    )
    entries = newest["entries"]
    # The positive control: the file read is the version the readers serve, its hints among it.
    served = {(action.id, action.label, action.hint) for action in action_catalog.actions()}
    assert served == {(e["id"], e["words"]["label"], e["words"]["hint"]) for e in entries}
    texts = [t for e in entries for t in (e["words"]["label"], e["words"]["hint"], e["reason"])]
    assert "Bring people into this world" in texts
    assert [text for text in texts if SAYS.search(text)] == []


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_an_engine_writes_no_new_simulated_words_and_keeps_what_its_version_recorded(name):
    version, recorded = RECORDED[name]
    if version is None:
        assert society_engine("exulanica-society/v1").playback_refusal is not None
    else:
        module, constant, profile = version
        assert getattr(importlib.import_module(module), constant) == profile, (
            "this engine's version moved, so its words are checked: write J34's forms "
            '("Ada waits.") and keep the earlier words only where that version still records them'
        )
    said = set(_said(_read(name)))
    # The positive control: every recorded summary named here is still what the module writes.
    assert recorded <= said
    assert said - recorded == set()


def test_the_scan_sees_a_sentence_that_says_it_and_never_a_code_or_a_docstring():
    source = (
        '"""A simulated person in a docstring."""\n'
        'LINE = f"At simulated minute {tick}, they rested."\n'
        'SUMMARY = f"{name} (simulated): {doing}."\n'
        'KEY = "SIMULATED_PLACEHOLDER"\n'
        'HEADER = "Living world simulation"\n'
    )
    assert sorted(_said(source)) == sorted(
        ["At simulated minute {}, they rested.", "{} (simulated): {}.", "Living world simulation"]
    )
