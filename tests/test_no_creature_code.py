"""No code is written for any particular creature: creatures are data.

A creature a person imagines becomes a body recipe, a body plan, a sketch and a kind, all data
the code written once for every creature reads (``exulanica/things/bodies.py``,
``exulanica/things/creatures.py``, the drafter, the drawing). This guard makes that a fact of the
tree rather than a rule to remember: no source file of the product, the shared piece formats, the
GPU tooling or the web packages may name a creature from the list in
``tests/fixtures/creatures/creatures.v1.json``. Data may (catalogs, prompt words held to their own
test, fixtures, documents): only code is scanned. Snake is not on the list (code writes snake
case, a way of writing names), and "snake case" is skipped where a list names it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS: Sequence[str] = json.loads(
    (Path(__file__).parent / "fixtures" / "creatures" / "creatures.v1.json").read_text("utf-8")
)["creature_words"]
#: What is scanned: code, by its suffix, under each root; a test directory inside a root is data.
SCANNED = (
    ("exulanica", (".py",)),
    ("exulanica_pieces", (".py",)),
    ("ml", (".py",)),
    ("web/packages", (".ts", ".tsx")),
)
#: Words as code writes them: a run of letters, split at underscores, digits and a capital that
#: starts a camelCase word, so ``make_dragon``, ``makeDragon`` and ``DRAGON`` all read as words.
_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")


def _sources() -> Iterable[Path]:
    for root, suffixes in SCANNED:
        for path in sorted((ROOT / root).rglob("*")):
            parts = set(path.relative_to(ROOT).parts)
            if path.suffix not in suffixes or not path.is_file():
                continue
            if parts & {"tests", "test", "node_modules", "dist", ".venv", "__pycache__"}:
                continue
            yield path


def creature_words_in(paths: Iterable[Path], words: Sequence[str]) -> list[str]:
    """Every place a source names one of ``words`` (or its plural) as a word of an identifier, a
    string or a comment, by file and line."""
    wanted = {word.lower() for word in words}
    found = []
    for path in paths:
        where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        for number, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
            tokens = _TOKEN.findall(line)
            for index, token in enumerate(tokens):
                word = token.lower()
                following = tokens[index + 1].lower() if index + 1 < len(tokens) else ""
                if word == "snake" and following == "case":
                    continue
                if word in wanted or (word.endswith("s") and word[:-1] in wanted):
                    found.append(f"{where}:{number}: {token}")
    return found


def test_no_source_names_a_creature():
    sources = list(_sources())
    # The scan reaches the code written once for every creature, so an empty answer means
    # something.
    names = {path.relative_to(ROOT).as_posix() for path in sources}
    assert {"exulanica/things/bodies.py", "exulanica/things/creatures.py"} <= names
    assert "exulanica/selection/creature_drafting.py" in names
    assert creature_words_in(sources, WORDS) == []


def test_the_scan_finds_a_creature_named_in_code(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def make_dragon():\n    return makeSpider('Dragons')\n\n"
        "NAME = 'snake_case'  # writes names\n",
        "utf-8",
    )
    assert creature_words_in([planted], WORDS) == [
        f"{planted}:1: dragon",
        f"{planted}:2: Spider",
        f"{planted}:2: Dragons",
    ]
