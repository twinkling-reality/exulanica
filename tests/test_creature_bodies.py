"""Creatures' bodies: a body recipe built into a body plan, its sketch, and the kind around them.

The recipes are the hand-written ones in ``tests/fixtures/creatures/creatures.v1.json``. What each
assertion expects comes from the recipe or from a reading written here, never from the builder: a
leg's foot stands on the ground, a nose is at the front of the stated length, a wingtip at half the
stated span, a left limb is the exact mirror of its right, the bone count is the recipe's own sum,
and the sketch's container is read back from its glTF bytes by a parser in this file.
"""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path
from typing import Any

import pytest
from exulanica.movement.registry import movement_module
from exulanica.things.bodies import (
    BODY_RECIPE_CODES,
    BodyRefused,
    body_grammar,
    build_body,
    enabled_movements,
    read_body_recipe,
)
from exulanica.things.catalogs import (
    ANY_PLAN_WITH_BONES,
    BODY_PLAN_PROFILE,
    BodyPlanRefused,
    read_body_plan,
    thing_catalogs,
)
from exulanica.things.creatures import CreatureRefused, assemble_creature
from exulanica.things.looks import read_look
from exulanica.world.static_glb import inspect_static_glb

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "creatures" / "creatures.v1.json").read_text("utf-8")
)
CREATURES = {**FIXTURES["held_out"], **FIXTURES["development"]}
BY = {
    "kind": "model",
    "provider": "nebius_token_factory",
    "model_id": "test/model",
    "prompt_version": "creature-drafting-1",
    "prompt_sha256": "a" * 64,
    "words_sha256": "b" * 64,
    "execution_sha256": None,
}
DRAFTED = {
    "profile": "exulanica.origin/v1",
    "class": "drafted",
    "by": BY,
    "sources": [],
    "licence": {
        "spdx": "Apache-2.0",
        "verdict": "SHIP",
        "attribution": None,
        "share_alike": False,
        "licence_url": None,
        "licence_text_sha256": None,
    },
    "authors": [],
    "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": None},
    "distribution": "private",
}
PAIRED = ("leg", "arm", "wing", "fin")


def _recipe(name: str) -> dict[str, Any]:
    return copy.deepcopy(CREATURES[name]["recipe"])


def _built(name: str) -> Any:
    recipe = read_body_recipe(_recipe(name))
    return recipe, build_body(recipe, key=name, version=1, title=f"{name} body", origin=DRAFTED)


def _expected_bones(recipe: dict[str, Any]) -> int:
    """The recipe's own count, as the drafter's words state it."""
    count = 1 + recipe["spine"] + (2 if recipe["upper_body"] == "upright" else 0) + recipe["tail"]
    count += sum(head["neck"] + 1 + (1 if head["jaw"] else 0) for head in recipe["heads"])
    count += sum(limb["count"] * limb["segments"] for limb in recipe["limbs"])
    return count


# -- the grammar --------------------------------------------------------------------------------


def test_every_movement_the_grammar_names_is_built_or_says_in_words_why_not():
    grammar = body_grammar()
    for key, spec in grammar.movements.items():
        if spec["module"] is None:
            assert spec["refusal"].startswith("This world has no "), key
        else:
            # A module the grammar names is one the movement registry states, by its identity.
            assert movement_module(spec["module"]).module == spec["module"]
            assert spec["refusal"] is None
        assert spec["needs"]
    assert grammar.movements["walking"]["module"] == "exulanica-movement/walking/v1"
    # Flight for beings is not built until its module lands: drafted plans state no flight yet.
    assert grammar.movements["flight"]["module"] is None


def test_the_grammar_bounds_bones_to_what_one_skinned_look_may_move():
    assert body_grammar().limits["bones_maximum"] == 128


# -- recipes to plans ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_every_fixture_builds_a_plan_its_reader_accepts(name):
    raw = _recipe(name)
    _recipe_read, built = _built(name)
    plan = read_body_plan(dict(built.plan))
    assert plan.name == f"{name}/v1"
    assert built.plan["profile"] == BODY_PLAN_PROFILE
    assert len(plan.bones) == _expected_bones(raw)
    assert set(built.joints) == plan.bone_names == set(built.ends)
    # Every chain is the plan's own bones, each in one chain at most, and a limb of each paired
    # role comes once per side per pair.
    for role in PAIRED:
        count = next((limb["count"] for limb in raw["limbs"] if limb["role"] == role), 0)
        assert sum(1 for limb in plan.limbs if limb.role == role) == count
    tentacles = next((limb["count"] for limb in raw["limbs"] if limb["role"] == "tentacle"), 0)
    assert sum(1 for limb in plan.limbs if limb.role == "tentacle") == tentacles
    assert sum(1 for limb in plan.limbs if limb.role == "jaw") == sum(
        1 for head in raw["heads"] if head["jaw"]
    )


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_a_body_stands_where_its_recipe_says(name):
    raw = _recipe(name)
    _recipe_read, built = _built(name)
    extent = raw["extent_mm"]
    points = [*built.joints.values(), *built.ends.values()]
    plan = built.plan
    # Nothing is below the ground, and nothing reaches past the stated extent by more than a
    # millimetre of rounding (the stated length is nose to tail tip, centred on the origin).
    assert min(z for _x, _y, z in points) >= 0
    assert max(abs(y) for _x, y, _z in points) <= extent["length"] // 2 + 1
    assert max(z for _x, _y, z in points) <= extent["height"] + 1
    for limb in plan["limbs"]:
        tip = built.ends[limb["bones"][-1]]
        if limb["role"] == "leg" and raw["posture"] != "floating":
            assert tip[2] == 0, f"{limb['key']} stands on the ground"
        if limb["role"] == "wing":
            assert abs(tip[0]) == extent["span"] // 2, f"{limb['key']} reaches half the span"
    if raw["posture"] in ("horizontal", "serpentine") and raw["upper_body"] == "none":
        # A body lying along y has its nose at the front of its stated length.
        noses = [built.ends[f"head{index + 1}"][1] for index in range(len(raw["heads"]))]
        assert max(noses) == extent["length"] // 2


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_every_left_limb_is_the_exact_mirror_of_its_right(name):
    _recipe_read, built = _built(name)
    for bone, joint in built.joints.items():
        if "Left" not in bone:
            continue
        twin = bone.replace("Left", "Right")
        x, y, z = built.joints[twin]
        assert joint == (-x, y, z), bone
        ex, ey, ez = built.ends[twin]
        assert built.ends[bone] == (-ex, ey, ez), bone


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_a_limb_along_a_lying_body_hangs_from_the_stretch_of_spine_beside_it(name):
    # A lying body's spine runs back to front along y from the hips; a limb hanging from it hangs
    # from the bone whose joint is the last not ahead of the limb's root, so bending the spine
    # carries each limb with its own stretch of body.
    recipe, built = _built(name)
    if recipe.posture not in ("horizontal", "serpentine"):
        return
    parents = {bone["name"]: bone["parent"] for bone in built.plan["bones"]}
    spine = next(chain for chain in built.plan["limbs"] if chain["key"] == "spine")
    carriers = ["hips", *spine["bones"]]
    hung = 0
    for chain in built.plan["limbs"]:
        root = chain["bones"][0]
        if chain["role"] == "spine" or parents[root] not in carriers or chain["role"] == "tail":
            continue
        y = built.joints[root][1]
        behind = [bone for bone in carriers if built.joints[bone][1] <= y]
        assert parents[root] == (behind[-1] if behind else carriers[0]), chain["key"]
        hung += 1
    assert hung > 0


def test_the_same_recipe_builds_the_same_bytes():
    first = _built("dragon")[1]
    second = _built("dragon")[1]
    assert json.dumps(dict(first.plan), sort_keys=True) == json.dumps(
        dict(second.plan), sort_keys=True
    )
    assert first.joints == second.joints and first.radii == second.radii


def test_a_body_moves_by_what_it_has_and_what_is_built():
    movers = {name for name in CREATURES if enabled_movements(read_body_recipe(_recipe(name)))}
    assert movers == set(CREATURES)
    assert "walking" not in enabled_movements(read_body_recipe(_recipe("floating_eight")))
    _r, floating = _built("floating_eight")
    assert floating.plan["moves"] == []  # it can only fly, and flight is not built yet
    _r, dragon = _built("dragon")
    assert dragon.plan["moves"] == ["exulanica-movement/walking/v1"]
    assert "flight" in enabled_movements(read_body_recipe(_recipe("dragon")))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda r: r["limbs"].__setitem__(0, {**r["limbs"][0], "count": 9}),
            "body_recipe_out_of_bounds",
        ),
        (lambda r: r["extent_mm"].__setitem__("span", 100), "body_span_unfit"),
        (lambda r: r.__setitem__("holds_with", "hands"), "body_holds_nothing"),
        (
            lambda r: r.__setitem__("appearance", "a beast with 10 eyes and a long tail"),
            "body_recipe_invalid",
        ),
        (lambda r: r.__setitem__("tail", 17), "body_recipe_out_of_bounds"),
        (lambda r: r.__setitem__("posture", "flying"), "body_recipe_invalid"),
        (lambda r: r.__setitem__("colours", ["crimson", "not a colour"]), "body_recipe_invalid"),
    ],
)
def test_a_recipe_out_of_its_grammar_is_refused_by_name(change, code):
    raw = _recipe("dragon")
    change(raw)
    with pytest.raises(BodyRefused) as refused:
        read_body_recipe(raw)
    assert refused.value.code == code
    assert code in dict(BODY_RECIPE_CODES)


def test_too_many_bones_and_unfit_parts_are_refused_by_name():
    raw = _recipe("floating_eight")
    raw["limbs"] = [{"role": "tentacle", "count": 12, "segments": 8}]
    raw["heads"] = [{"neck": 8, "jaw": True}] * 5
    with pytest.raises(BodyRefused) as refused:
        read_body_recipe(raw)
    assert refused.value.code == "body_too_many_bones"
    raw = _recipe("floating_eight")
    raw["upper_body"] = "upright"
    with pytest.raises(BodyRefused) as refused:
        read_body_recipe(raw)
    assert refused.value.code == "body_part_unfit"


def test_a_plan_document_whose_chain_is_not_the_plan_s_own_bones_is_refused():
    _r, built = _built("three_heads")
    plan = copy.deepcopy(dict(built.plan))
    chain = plan["limbs"][0]["bones"]
    plan["limbs"][0]["bones"] = list(reversed(chain))
    with pytest.raises(BodyPlanRefused) as refused:
        read_body_plan(plan)
    assert refused.value.code == "body_plan_invalid"
    plan = copy.deepcopy(dict(built.plan))
    plan["key"] = "humanoid"
    with pytest.raises(BodyPlanRefused) as refused:
        read_body_plan(plan)
    assert refused.value.code == "body_plan_name_taken"


# -- the sketch, read back from its bytes -------------------------------------------------------


def _gltf(container: bytes) -> dict[str, Any]:
    magic, version, total = struct.unpack_from("<III", container, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(container))
    length, kind = struct.unpack_from("<II", container, 12)
    assert kind == 0x4E4F534A
    return json.loads(container[20 : 20 + length])


@pytest.mark.parametrize("name", ["dragon", "ten_legs", "serpent", "floating_eight", "four_arms"])
def test_a_creature_s_sketch_is_a_node_per_bone_at_its_joint(name):
    raw = _recipe(name)
    label = name.replace("_", " ")
    # A floating body only flies, which is not built yet: it is drafted with no movement.
    form = _form(raw, label=label, moves=[] if raw["posture"] == "floating" else None)
    creature = assemble_creature(form, by=BY)
    document = _gltf(creature.sketch_container)
    nodes = {node["name"]: node for node in document["nodes"]}
    joints = _joints(creature)
    for bone in creature.plan.bone_names:
        node = nodes[f"bone:{bone}"]
        # A slot-frame joint (x, y, z) in millimetres is glTF (-x, z, y) in metres.
        x, y, z = joints[bone]
        assert node["translation"] == pytest.approx([-x / 1000, z / 1000, y / 1000], abs=1e-6)
        assert "rotation" not in node and "scale" not in node
    roots = set(document["scenes"][0]["nodes"])
    assert {document["nodes"][index]["name"] for index in roots} == {
        f"bone:{bone}" for bone in creature.plan.bone_names
    }
    # The product's own admission reads it as a static container.
    inspect_static_glb(creature.sketch_container)
    look = creature.sketch
    assert look.document["look_kind"] == "rigid_on_bones"
    assert look.document["label"] == "a sketch of its body"
    assert look.document["origin"]["class"] == "authored"
    assert look.document["origin"]["licence"]["spdx"] == "CC0-1.0"
    assert creature.plan.sha256 in look.document["origin"]["lineage"]["ingredients"]


def _joints(creature: Any) -> dict[str, tuple[int, int, int]]:
    recipe = read_body_recipe(dict(creature.recipe))
    built = build_body(
        recipe,
        key=creature.plan.key,
        version=creature.plan.version,
        title=creature.plan.title,
        origin=dict(creature.plan_document["origin"]),
    )
    return dict(built.joints)


def test_skinned_and_rigid_looks_fit_any_plan_with_bones_and_a_light_does_not():
    catalogs = thing_catalogs()
    assert ANY_PLAN_WITH_BONES in catalogs.look_kinds["skinned"].plans
    assert ANY_PLAN_WITH_BONES in catalogs.look_kinds["rigid_on_bones"].plans
    creature = assemble_creature(_form(_recipe("dragon"), label="dragon"), by=BY)
    assert catalogs.look_kinds["rigid_on_bones"].fits(creature.plan)
    assert catalogs.look_kinds["skinned"].fits(creature.plan)
    assert not catalogs.look_kinds["light"].fits(creature.plan)
    assert not catalogs.look_kinds["static"].fits(creature.plan)
    light = dict(creature.sketch.document)
    light["look_kind"] = "light"
    with pytest.raises(Exception) as refused:
        read_look(light, plan_of=lambda name: creature.plan if name == creature.plan.name else None)
    assert getattr(refused.value, "code", "") == "look_unfit"


# -- the kind around them -----------------------------------------------------------------------


def _form(recipe: dict[str, Any], *, label: str, moves: list[str] | None = None) -> dict[str, Any]:
    extent = recipe["extent_mm"]
    return {
        "label": label,
        "summary": "A creature drawn from a body recipe in the test fixtures.",
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
        "moves": ["walking"] if moves is None else moves,
        # A creature with no way to move only waits and speaks.
        "abilities": ["wait", "say"] if moves == [] else ["wait", "stand", "follow", "say"],
        "offers": ["talk_to", "hear", "be_followed"],
        "routine": [{"ability": "wait", "weight": 300}]
        + ([] if moves == [] else [{"ability": "follow", "weight": 500}]),
    }


def test_a_creature_is_a_kind_of_its_drafted_plan_wearing_its_sketch():
    creature = assemble_creature(_form(_recipe("ten_legs"), label="ten legged creature"), by=BY)
    kind = creature.kind
    assert kind.kind == "ten_legged_creature" and kind.klass == "being"
    body = kind.document["body"]
    assert body["plan"] == creature.plan.name and body["plan_sha256"] == creature.plan.sha256
    assert body["extent_mm"] == _recipe("ten_legs")["extent_mm"]
    assert kind.looks[0]["sha256"] == creature.sketch.sha256
    assert kind.document["deciders"] == {
        "default": "routine",
        "allowed": ["routine", "model", "person"],
    }
    origin = kind.document["origin"]
    assert origin["class"] == "drafted" and origin["by"] == BY
    assert origin["lineage"]["ingredients"] == [creature.recipe_sha256, creature.plan.sha256]
    # What a society reads of it pins the plan and never a look.
    semantics = kind.semantics()
    assert semantics["body"]["plan_sha256"] == creature.plan.sha256
    assert "looks" not in semantics


@pytest.mark.parametrize(
    ("name", "label", "moves", "code", "words"),
    [
        (
            "dragon",
            "red wyrm",
            ["walking", "flight"],
            "creature_movement_unbuilt",
            "This world has no flying creatures yet.",
        ),
        (
            "serpent",
            "long swimmer",
            ["walking", "swimming"],
            "creature_movement_unbuilt",
            "This world has no swimming yet.",
        ),
        (
            "three_heads",
            "winged hound",
            ["flight"],
            "creature_cannot_move_so",
            "a pair of wings, or a floating body",
        ),
        ("three_heads", "knight", ["walking"], "creature_name_taken", "already exists here"),
        ("three_heads", "ten-legged", ["walking"], "thing_kind_invalid", "lowercase words"),
    ],
)
def test_what_a_body_or_this_world_cannot_do_is_refused_in_words(name, label, moves, code, words):
    with pytest.raises(CreatureRefused) as refused:
        assemble_creature(_form(_recipe(name), label=label, moves=moves), by=BY)
    assert refused.value.code == code
    assert words in refused.value.detail


def test_abilities_a_body_cannot_serve_are_refused_by_the_kind_reader():
    form = _form(_recipe("horse"), label="plain grazer")
    form["holds_with"] = "none"
    form["abilities"] = ["wait", "pick_up"]
    with pytest.raises(CreatureRefused) as refused:
        assemble_creature(form, by=BY)
    assert refused.value.code == "thing_kind_body_unmet"
