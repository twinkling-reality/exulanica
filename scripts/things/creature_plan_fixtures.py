"""Write the drafted bodies the page's tests pose, or check the committed ones are exactly them.

    uv run python scripts/things/creature_plan_fixtures.py          # write
    uv run python scripts/things/creature_plan_fixtures.py --check  # exit 1 on any difference

The page poses a drafted creature from three documents its server builds: the body plan with its
chains, the sketch look drawn on that plan, and the kind that states the body's extent
(``exulanica/things/creatures.py``). Its tests read those documents here, one file a creature,
under ``web/packages/atlas-react/test/fixtures/creature-plans/``, so the page is tested on what
this server assembles and not on a plan written by hand inside a test.

The creatures are the hand-written recipes of ``tests/fixtures/creatures/creatures.v1.json``, the
same ones the body builder's own tests read. Each is assembled as a drafted creature is
(:func:`exulanica.things.creatures.assemble_creature`), and the file holds:

*   ``plan``, ``look`` and ``kind``: the documents as the workspace's library would keep them;
*   ``joints_m``: where each bone's joint stands in the sketch's container, read from the
    container's own ``bone:<name>`` nodes (glTF metres, +Y up, the figure facing +Z), which is
    what the page's rigid figure reads when it dresses the plan;
*   ``recipe_sha256``: the recipe the three were built from.

A file is never edited by hand. ``tests/test_creature_plan_fixtures.py`` runs the check, so a
change to the builder, the sketch or a recipe that moves a document fails there until the files
are written again.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from exulanica.things.bodies import (  # noqa: E402
    body_grammar,
    enabled_movements,
    read_body_recipe,
)
from exulanica.things.creatures import assemble_creature  # noqa: E402

RECIPES = ROOT / "tests/fixtures/creatures/creatures.v1.json"
FIXTURES = ROOT / "web/packages/atlas-react/test/fixtures/creature-plans"
PROFILE = "exulanica.creature-plan-fixture/v1"
#: Who drafted a fixture's creature: no model did. The digests are placeholders a reader can see
#: are not a prompt's or a person's words.
BY = {
    "kind": "model",
    "provider": "nebius_token_factory",
    "model_id": "fixture/hand-written",
    "prompt_version": "creature-drafting-1",
    "prompt_sha256": "0" * 64,
    "words_sha256": "0" * 64,
    "execution_sha256": None,
}
_GLB_MAGIC, _GLB_JSON = 0x46546C67, 0x4E4F534A


def _form(name: str, recipe: dict[str, Any]) -> dict[str, Any]:
    """The drafted form that states ``recipe``: its body as written, and the least a kind needs
    besides (the page's tests read the body, not what the creature does)."""
    grammar = body_grammar()
    read = read_body_recipe(recipe, grammar=grammar)
    moves = [
        movement
        for movement in enabled_movements(read, grammar)
        if grammar.movements[movement]["module"] is not None
    ]
    extent = recipe["extent_mm"]
    return {
        # A label no shipped kind takes, whatever creature the recipe is named for.
        "label": "fixture " + name.replace("_", " "),
        "summary": "A creature built from a hand-written body recipe for the page's tests.",
        "posture": recipe["posture"],
        "spine": recipe["spine"],
        "upper_body": recipe["upper_body"],
        "tail": recipe["tail"],
        "length_mm": extent["length"],
        "width_mm": extent["width"],
        "height_mm": extent["height"],
        "span_mm": extent["span"],
        "holds_with": recipe["holds_with"],
        "appearance": recipe["appearance"],
        "heads": recipe["heads"],
        "limbs": recipe["limbs"],
        "colours": recipe["colours"],
        "moves": moves,
        # A body with no way to move only waits and speaks.
        "abilities": ["wait", "stand", "follow", "say"] if moves else ["wait", "say"],
        "offers": ["talk_to", "hear", "be_followed"],
        "routine": [{"ability": "wait", "weight": 300}],
    }


def _joints(container: bytes) -> dict[str, list[float]]:
    """Each bone's joint in the container, by the bone's name: the place of its ``bone:`` node,
    which the sketch writes at the scene's root."""
    magic, version, total = struct.unpack_from("<III", container, 0)
    length, kind = struct.unpack_from("<II", container, 12)
    if (magic, version, total, kind) != (_GLB_MAGIC, 2, len(container), _GLB_JSON):
        raise ValueError("the sketch's container is not a binary glTF 2.0 file")
    gltf = json.loads(container[20 : 20 + length])
    roots = set(gltf["scenes"][gltf["scene"]]["nodes"])
    joints = {}
    for index, node in enumerate(gltf["nodes"]):
        if not node["name"].startswith("bone:"):
            continue
        if index not in roots or set(node) - {"name", "children", "translation"}:
            raise ValueError(f"{node['name']} is not a placed node at the scene's root")
        joints[node["name"][len("bone:") :]] = [float(v) for v in node["translation"]]
    return joints


def documents() -> dict[str, dict[str, Any]]:
    """Every fixture document, by the name its recipe has in the recipes file."""
    recipes = json.loads(RECIPES.read_text(encoding="utf-8"))
    made = {}
    for name, entry in sorted({**recipes["held_out"], **recipes["development"]}.items()):
        creature = assemble_creature(_form(name, entry["recipe"]), by=BY)
        joints = _joints(creature.sketch_container)
        plan = dict(creature.plan_document)
        if set(joints) != {bone["name"] for bone in plan["bones"]}:
            raise ValueError(f"{name}: the sketch does not place exactly the plan's bones")
        made[name] = {
            "profile": PROFILE,
            "written_by": "scripts/things/creature_plan_fixtures.py",
            "recipe_sha256": creature.recipe_sha256,
            "plan": plan,
            "look": dict(creature.sketch.document),
            "kind": dict(creature.kind.document),
            "joints_m": joints,
        }
    return made


def _text(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    wanted = {FIXTURES / f"{name}.json": _text(document) for name, document in documents().items()}
    present = set(FIXTURES.glob("*.json")) if FIXTURES.is_dir() else set()
    differing = sorted(
        str(path.relative_to(ROOT))
        for path, text in wanted.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    )
    stray = sorted(str(path.relative_to(ROOT)) for path in present - set(wanted))
    if arguments.check:
        for path in differing:
            print(f"differs from what the builder writes: {path}")
        for path in stray:
            print(f"no recipe writes this file: {path}")
        return 1 if differing or stray else 0
    if stray:
        # A file this script did not write is never removed by it.
        for path in stray:
            print(f"refused: no recipe writes {path}; remove it by hand")
        return 1
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for path, text in wanted.items():
        path.write_text(text, encoding="utf-8")
    print(f"wrote {len(wanted)} fixtures, {sum(len(t) for t in wanted.values())} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
