"""The looks this repository authors are recipe documents, and no things code names one.

What is shown here, with no database:

*   every recipe in ``assets/catalogs/things/recipes`` reads, is named for what it states, and is
    either a look's recipe (every colour it reaches resolves) or a base another recipe builds on;
*   the two blocky figures are one stated body in two palettes: their joints and parts are equal
    and only their colours differ;
*   the reader refuses by name what a recipe may not state, each refusal against a positive control
    that the same document with the fault removed reads;
*   no module of the things package states a shipped kind's, look's or recipe's key as a string, so
    a new thing is data and never a line of code.

The containers the recipes write are held to the digests their look documents pin by
``tests/test_thing_looks_and_origins.py``, which writes each one again.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.things.authored import (
    AUTHORED_LOOKS,
    RECIPE_DIRECTORY,
    RecipeRefused,
    load_recipes,
    nodes_from,
    read_recipe,
)

ROOT = Path(__file__).resolve().parents[1]
THINGS_CODE = ROOT / "exulanica" / "things"
THINGS_DATA = ROOT / "assets" / "catalogs" / "things"


def _recipe_files() -> dict[str, dict[str, Any]]:
    """Every recipe document, read here as plain JSON apart from the reader under test."""
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RECIPE_DIRECTORY.glob("*.json"))
    }


def test_every_recipe_reads_and_is_a_look_s_or_a_base_another_builds_on():
    files = _recipe_files()
    assert files, "the recipes directory holds the authored looks' recipes"
    recipes = load_recipes()
    assert len(recipes) == len(files)
    built_on = {
        (doc["base"]["recipe"], doc["base"]["version"]) for doc in files.values() if doc["base"]
    }
    looks = {
        json.loads(path.read_text(encoding="utf-8"))["look"]
        for path in (THINGS_DATA / "looks").glob("*.json")
    }
    for key, version in recipes:
        written = True
        try:
            nodes_from(recipes, key, version)
        except RecipeRefused:
            written = False
        if written:
            assert key in looks, f"{key} writes a container no look document names"
            assert key in AUTHORED_LOOKS
        else:
            assert (key, version) in built_on, f"{key} is neither written nor built on"
            assert key not in AUTHORED_LOOKS


def test_recipes_built_on_one_base_are_one_stated_body_in_their_own_palettes():
    groups: dict[tuple[str, int], list[str]] = {}
    for doc in _by_key().values():
        if doc["base"] is not None and doc["recipe"] in AUTHORED_LOOKS:
            groups.setdefault((doc["base"]["recipe"], doc["base"]["version"]), []).append(
                doc["recipe"]
            )
    assert any(len(keys) >= 2 for keys in groups.values()), "the blocky figures share a base"
    for keys in groups.values():
        shapes = [
            [
                (n.name, n.at_mm, [(p.name, p.shape, p.size_mm, p.centre_mm) for p in n.parts])
                for n in AUTHORED_LOOKS[key]()
            ]
            for key in keys
        ]
        assert all(shape == shapes[0] for shape in shapes)
        colours = {tuple(p.colour for n in AUTHORED_LOOKS[key]() for p in n.parts) for key in keys}
        assert len(colours) == len(keys)


def _by_key() -> dict[str, dict[str, Any]]:
    return {doc["recipe"]: doc for doc in _recipe_files().values()}


def _a_prop() -> dict[str, Any]:
    """A recipe that states its own nodes and colours, from the directory."""
    for doc in _by_key().values():
        if doc["nodes"] is not None and all(
            part["colour"].startswith("#") for node in doc["nodes"] for part in node["parts"]
        ):
            return copy.deepcopy(doc)
    raise AssertionError("a recipe with literal colours ships")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(base={"recipe": "anything", "version": 1}), "one of the two"),
        (lambda d: d["nodes"][0]["parts"][0].update(shape="cone"), "shape"),
        (lambda d: d["nodes"][0]["parts"][0].update(size_mm=[0, 10, 10]), "positive"),
        (lambda d: d["nodes"][0]["parts"][0].update(colour="#FFFFFF"), "lowercase"),
        (lambda d: d["nodes"][0]["parts"][0].update(texture="stone"), "states exactly"),
        (lambda d: d["nodes"].append(copy.deepcopy(d["nodes"][0])), "each node once"),
        (lambda d: d.update(palette={}), "maps palette roles"),
        (lambda d: d["origin"]["licence"].update(spdx="not a licence!"), "origin"),
    ],
)
def test_a_recipe_is_refused_by_name_for_what_it_may_not_state(change, message):
    control = _a_prop()
    read_recipe(control)  # the positive control: the same document, unchanged, reads
    faulty = _a_prop()
    change(faulty)
    with pytest.raises(RecipeRefused, match=message):
        read_recipe(faulty)


def test_a_role_no_palette_colours_is_refused_when_written(tmp_path):
    docs = _by_key()
    painted = next(doc for doc in docs.values() if doc["base"] is not None)
    base = docs[painted["base"]["recipe"]]
    for doc in (painted, base):
        (tmp_path / f"{doc['recipe']}.v{doc['version']}.json").write_text(json.dumps(doc))
    recipes = load_recipes(tmp_path)
    nodes_from(recipes, painted["recipe"], painted["version"])  # the positive control
    role = sorted(painted["palette"])[0]
    del painted["palette"][role]
    (tmp_path / f"{painted['recipe']}.v{painted['version']}.json").write_text(json.dumps(painted))
    with pytest.raises(RecipeRefused, match=f"names the role '{role}'"):
        nodes_from(load_recipes(tmp_path), painted["recipe"], painted["version"])


def test_a_recipe_file_states_the_recipe_and_version_its_name_says(tmp_path):
    doc = _a_prop()
    (tmp_path / f"{doc['recipe']}.v{doc['version']}.json").write_text(json.dumps(doc))
    load_recipes(tmp_path)  # the positive control
    (tmp_path / f"{doc['recipe']}.v{doc['version']}.json").rename(
        tmp_path / f"{doc['recipe']}.v{doc['version'] + 1}.json"
    )
    with pytest.raises(RecipeRefused, match="its name says"):
        load_recipes(tmp_path)


def test_a_chain_of_bases_is_bounded(tmp_path):
    prop = _a_prop()
    (tmp_path / f"{prop['recipe']}.v1.json").write_text(json.dumps(prop))
    below = prop["recipe"]
    for depth in range(1, 7):
        layer = copy.deepcopy(prop)
        layer.update(recipe=f"layer-{depth}", nodes=None, base={"recipe": below, "version": 1})
        layer["palette"] = {"unused": "#000000"}
        (tmp_path / f"layer-{depth}.v1.json").write_text(json.dumps(layer))
        below = f"layer-{depth}"
    recipes = load_recipes(tmp_path)
    nodes_from(recipes, "layer-4", 1)  # the positive control: four bases are followed
    with pytest.raises(RecipeRefused, match="at most 4 bases"):
        nodes_from(recipes, "layer-6", 1)


def _shipped_keys() -> set[str]:
    keys: set[str] = set()
    for folder, field in (("kinds", "kind"), ("looks", "look"), ("recipes", "recipe")):
        for path in (THINGS_DATA / folder).glob("*.json"):
            keys.add(json.loads(path.read_text(encoding="utf-8"))[field])
    return keys


def _named_in(path: Path, keys: set[str]) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in keys
    ]


def test_no_things_module_names_a_shipped_kind_look_or_recipe():
    keys = _shipped_keys()
    assert len(keys) >= 10  # the scan reads the shipped kinds, looks and recipes
    named = {
        str(path.relative_to(ROOT)): found
        for path in sorted(THINGS_CODE.glob("*.py"))
        if (found := _named_in(path, keys))
    }
    assert named == {}


def test_the_scan_sees_a_key_stated_in_code(tmp_path):
    key = sorted(_shipped_keys())[0]
    module = tmp_path / "per_thing.py"
    module.write_text(f"PAINT = {{{key!r}: '#8d99a6'}}\n")
    assert _named_in(module, _shipped_keys()) == [(1, key)]
