"""A module that asks what a society engine can do asks the engine table, never an engine's name.

``exulanica/world/society-engines.v3.json`` states each engine's capabilities once. A comparison
of an engine's identity (``row["engine_version"] == PURPOSEFUL_PROFILE``, or the profile text
itself) where a capability decides is a second statement of that capability, and it silently
leaves out the next engine that has it: the model choices a world's owner makes were decided by
four such comparisons before ``owner_model_choice`` was a column.

The scan below finds every comparison under ``exulanica/`` whose one side is an engine identity:
the profile text, a module constant whose value is one, or a tuple holding either. The only
comparisons it admits are an engine's own implementation checking that the document it was given
is its own, and a dispatch to each engine's own initializer; each module that holds one is listed
with its count and why. A new comparison anywhere fails, and so does a count that falls: lower it
here, so the list only shrinks.
"""

from __future__ import annotations

import ast
from pathlib import Path

from exulanica.world.society_engines import ENGINES

ROOT = Path(__file__).resolve().parents[1]

#: Modules that compare an engine's identity, how many times, and why each is not a capability.
IDENTITY_COMPARISONS: dict[str, tuple[int, str]] = {
    "exulanica/world/society_actions.py": (
        1,
        "the purposeful engine's reference directed advance checks the state it was given is its "
        "own",
    ),
    "exulanica/world/society_experiments.py": (
        2,
        "an experiment runs the living engine's own genesis and minutes, and checks that the "
        "definition and the state it reads are that engine's",
    ),
    "exulanica/world/society_legacy.py": (1, "the first engine checks its own state"),
    "exulanica/world/society_presence.py": (
        1,
        "the purposeful engine's own presence transition checks its state and seed",
    ),
    "exulanica/world/society_repository.py": (
        6,
        "creation dispatches to the purposeful and social engines' own initializers (two), and "
        "the retired v3 engine's social block is read and advanced by that engine's own "
        "functions (four)",
    ),
    "exulanica/world/society_social.py": (1, "the social engine checks its own state"),
    "exulanica/world/society_things.py": (
        2,
        "the society of things checks that the state its things phase and its state check are "
        "given is its own",
    ),
}


def identity_comparisons(root: Path = ROOT) -> dict[str, int]:
    """Every module under ``root/exulanica`` comparing an engine identity, with how often."""
    engines = {engine.engine for engine in ENGINES}
    modules = sorted((root / "exulanica").rglob("*.py"))
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in modules}
    constants = {
        target.id
        for tree in trees.values()
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and isinstance(node.value, ast.Constant)
        and node.value.value in engines
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }

    def names_an_engine(node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value in engines
        if isinstance(node, ast.Name):
            return node.id in constants
        if isinstance(node, ast.Attribute):
            return node.attr in constants
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            return any(names_an_engine(element) for element in node.elts)
        return False

    found: dict[str, int] = {}
    for path, tree in trees.items():
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and any(names_an_engine(side) for side in (node.left, *node.comparators))
        )
        if count:
            found[path.relative_to(root).as_posix()] = count
    return found


def test_no_module_compares_an_engine_identity_where_a_capability_decides():
    found = identity_comparisons()
    assert found == {module: count for module, (count, _why) in IDENTITY_COMPARISONS.items()}, (
        "a module compares an engine's identity: ask the engine table's capability instead, or "
        "say in IDENTITY_COMPARISONS why this is the engine's own implementation"
    )


def test_the_scan_finds_a_comparison_by_constant_text_and_tuple(tmp_path):
    # The positive control: each form the guard names is found in a planted package, so an empty
    # result for a module means it holds none.
    package = tmp_path / "exulanica"
    package.mkdir()
    (package / "profiles.py").write_text('PLANTED = "exulanica-society/v2"\n', encoding="utf-8")
    (package / "asks.py").write_text(
        "from exulanica.profiles import PLANTED\n"
        "def choose(row, module):\n"
        "    if row['engine_version'] == PLANTED:\n"
        "        return 1\n"
        "    if row['engine_version'] != 'exulanica-society/v3':\n"
        "        return 2\n"
        "    if row['engine_version'] in (module.PLANTED, 'x'):\n"
        "        return 3\n"
        "    return row['engine_version'] == 'exulanica-society/v9'\n",
        encoding="utf-8",
    )
    assert identity_comparisons(tmp_path) == {"exulanica/asks.py": 3}


def test_every_listed_module_says_why():
    for module, (count, why) in IDENTITY_COMPARISONS.items():
        assert (ROOT / module).is_file(), module
        assert count > 0 and len(why.split()) >= 5, module
