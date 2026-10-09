"""A container a creature's look is drawn from holds no word a person wrote, by construction.

A creature drafted from a person's words keeps them only in rows its erasure removes at once
(migration 0172): the kind's label and summary, the keys made from the label, the plan's title and
the recipe's appearance. Its sketch's container stays in the workspace's looks namespace,
unreferenced and never served, until the purge destroys it on the creature's tombstone or the
workspace's (and longer while a look the workspace keeps names the same file), which is safe only
because a container holds none of them. The sketch writer (exulanica/things/sketch.py, through
exulanica/things/pieces.py) names a node for each bone of the body plan, a part for each limb,
membrane and eye, and a material for each colour; the body builder (exulanica/things/bodies.py)
names each bone in one grammar from the body grammar catalog's parts, with ordinals. So, for every
recipe the generator below draws across the grammar's postures, parts and bounds, and for every
creature in the fixtures:

*   every name the container carries, wherever it is, splits into words the body grammar catalog
    states (its part, posture and movement keys) or the few structural words the builders add,
    and ordinals;
*   every material's colour is one of the palette's sRGB values, the only colours a recipe can name;
*   every other string anywhere in its JSON is one the glTF format itself defines, its version or
    the writer's generator, and it states no copyright and no extras.

Each recipe is drafted under a key, a title and an appearance in words the vocabulary does not hold,
so a writer that let any of them into a name fails here.
"""

from __future__ import annotations

import json
import random
import re
import struct
from collections.abc import Iterator
from typing import Any

import pytest
from exulanica.things.bodies import BodyRefused, body_grammar, build_body, read_body_recipe
from exulanica.things.pieces import GENERATOR
from exulanica.things.sketch import sketch_look

from test_creature_bodies import CREATURES, DRAFTED

#: The words the builders add to the grammar's own keys: a body's root and spine, a bone's side and
#: segment, the parts a sketch draws for a bone, and the writer's node prefix and two-sided suffix.
STRUCTURAL = frozenset(
    {
        "hips",
        "spine",
        "left",
        "right",
        "segment",
        "limb",
        "membrane",
        "eye",
        "bone",
        "both",
        "sides",
    }
)
#: Words no grammar key or structural word holds, in every key, title and appearance drafted here.
FOREIGN = "ravenous marmalade quokka"
_SIDES_SUFFIX = " both sides"
_COLOUR = re.compile(r"#[0-9a-f]{6}")
#: The strings glTF itself defines, the only ones a container holds besides its names, its version
#: and its generator: accessor types, alpha modes, animation paths and interpolations, image types.
FORMAT_WORDS = frozenset(
    {
        "SCALAR",
        "VEC2",
        "VEC3",
        "VEC4",
        "MAT2",
        "MAT3",
        "MAT4",
        "OPAQUE",
        "MASK",
        "BLEND",
        "translation",
        "rotation",
        "scale",
        "weights",
        "LINEAR",
        "STEP",
        "CUBICSPLINE",
        "image/png",
        "image/jpeg",
    }
)


def vocabulary() -> frozenset[str]:
    """The grammar catalog's posture, part and movement keys, split into words, and the builders'
    structural words: everything a container's name may be made of besides ordinals."""
    grammar = body_grammar()
    keys = [*grammar.postures, *grammar.parts, *grammar.movements]
    return frozenset(word for key in keys for word in key.split("_")) | STRUCTURAL


def palette() -> frozenset[str]:
    return frozenset(body_grammar().colours.values())


def gltf(container: bytes) -> dict[str, Any]:
    """The JSON chunk of a glTF binary."""
    magic, _version, _length = struct.unpack_from("<4sII", container, 0)
    assert magic == b"glTF"
    chunk_length, chunk_type = struct.unpack_from("<I4s", container, 12)
    assert chunk_type == b"JSON"
    return json.loads(container[20 : 20 + chunk_length])


def _words(name: str) -> list[str]:
    """A name's words: split at anything not a letter or digit, at each capital, and at digits."""
    return [token.lower() for token in re.findall(r"[a-z]+|[A-Z][a-z]*|[0-9]+", name)]


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


def _strings(value: Any, path: tuple[str | int, ...] = ()) -> Iterator[tuple[tuple, str]]:
    """Every string anywhere in a JSON value, with the path that reaches it."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from _strings(inner, (*path, key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _strings(inner, (*path, index))


def faults(container: bytes) -> list[str]:
    """Every way a container's strings could hold a word nobody chose from the grammar."""
    document = gltf(container)
    allowed, colours = vocabulary(), palette()
    found = []
    for path, text in _strings(document):
        place = "/".join(str(step) for step in path)
        if path[-1] == "name" and path[0] == "materials":
            parts = text.removesuffix(_SIDES_SUFFIX).split("+")
            if not all(_COLOUR.fullmatch(part) and part in colours for part in parts):
                found.append(f"material name {text!r} is not the palette's")
        elif path[-1] == "name":
            strange = [w for w in _words(text) if not w.isdigit() and w not in allowed]
            if strange:
                found.append(f"{place} name {text!r} holds {strange}")
        elif path in (("asset", "generator"), ("asset", "version")):
            continue
        elif text not in FORMAT_WORDS:
            found.append(f"{place} holds {text!r}, no name and none of the format's words")
    if "extras" in set(_keys(document)):
        found.append("the container states extras")
    asset = document.get("asset", {})
    if "copyright" in asset or asset.get("generator") != GENERATOR or asset.get("version") != "2.0":
        found.append(f"the container's asset is {asset}")
    return found


def _bounds(rng: random.Random, spec: dict[str, int]) -> int:
    return rng.randint(int(spec["minimum"]), int(spec["maximum"]))


def drawn_recipes(count: int, seed: int) -> list[dict[str, Any]]:
    """Recipes across the grammar: every posture, each part it allows in any number its bounds
    allow, any palette colours, each read by the recipe reader before it is kept."""
    grammar = body_grammar()
    rng = random.Random(seed)
    roles = ("leg", "arm", "wing", "fin", "tentacle")
    made: list[dict[str, Any]] = []
    while len(made) < count:
        posture_key = sorted(grammar.postures)[len(made) % len(grammar.postures)]
        posture = grammar.postures[posture_key]
        allowed = list(posture["parts"])
        limbs = []
        for role in rng.sample([r for r in roles if r in allowed], k=rng.randint(0, 3)):
            spec = grammar.parts[role]
            if spec.get("paired"):
                pairs = spec["pairs"]
                if role == "leg":
                    pairs = {
                        "minimum": max(pairs["minimum"], posture["leg_pairs"]["minimum"]),
                        "maximum": min(pairs["maximum"], posture["leg_pairs"]["maximum"]),
                    }
                count_of = _bounds(rng, pairs) * 2
            else:
                count_of = _bounds(rng, spec["count"])
            limbs.append(
                {"role": role, "count": count_of, "segments": _bounds(rng, spec["segments"])}
            )
        if posture["leg_pairs"]["minimum"] and "leg" not in [limb["role"] for limb in limbs]:
            spec = grammar.parts["leg"]
            limbs.append(
                {
                    "role": "leg",
                    "count": 2 * posture["leg_pairs"]["minimum"],
                    "segments": _bounds(rng, spec["segments"]),
                }
            )
        extent = {
            side: _bounds(rng, posture["extent_mm"][side]) for side in ("length", "width", "height")
        }
        winged = any(limb["role"] == "wing" and limb["count"] for limb in limbs)
        extent["span"] = (
            rng.randint(extent["width"], posture["extent_mm"]["span"]["maximum"]) if winged else 0
        )
        upright = "upper_body" in allowed and rng.random() < 0.3
        recipe = {
            "profile": "exulanica.body-recipe/v1",
            "posture": posture_key,
            "spine": _bounds(rng, posture["spine"]),
            "upper_body": "upright" if upright else "none",
            "heads": [
                {
                    "neck": _bounds(rng, grammar.parts["neck"]["bones_per_head"]),
                    "jaw": rng.random() < 0.5,
                }
                for _ in range(_bounds(rng, grammar.parts["head"]["count"]))
            ],
            "limbs": limbs,
            "tail": _bounds(rng, grammar.parts["tail"]["bones"]),
            "extent_mm": extent,
            "holds_with": "none",
            "colours": rng.sample(
                sorted(grammar.colours), k=_bounds(rng, grammar.limits["colours"])
            ),
            "appearance": f"a {FOREIGN} with eyes like lanterns",
        }
        try:
            read_body_recipe(recipe, grammar=grammar)
        except BodyRefused:
            continue
        made.append(recipe)
    return made


def sketched(recipe: dict[str, Any]) -> bytes | None:
    """The sketch container of ``recipe`` drafted under foreign words, or None for a recipe the
    builder refuses (too many bones)."""
    read = read_body_recipe(recipe)
    key = FOREIGN.replace(" ", "_")
    try:
        built = build_body(
            read, key=key, version=1, title=f"the body of a {FOREIGN}", origin=DRAFTED
        )
    except BodyRefused:
        return None
    _document, container = sketch_look(
        built,
        read,
        look=f"{key.replace('_', '-')}-sketch",
        version=1,
        plan_name=f"{key}/v1",
        origin={**DRAFTED, "class": "authored", "by": {"kind": "project"}},
    )
    return container


def test_the_vocabulary_holds_none_of_the_drafted_words():
    # The control: the words drafted here are words the vocabulary does not hold.
    assert not set(FOREIGN.split()) & vocabulary()


@pytest.mark.parametrize("creature", sorted(CREATURES))
def test_a_fixture_creature_s_container_holds_only_the_grammar_s_words(creature):
    container = sketched(CREATURES[creature]["recipe"])
    assert container is not None
    assert faults(container) == []


def test_every_drawn_recipe_s_container_holds_only_the_grammar_s_words():
    built = 0
    for recipe in drawn_recipes(160, seed=20261007):
        container = sketched(recipe)
        if container is None:
            continue
        built += 1
        assert faults(container) == [], recipe
    assert built >= 120, "too few drawn recipes built to stand for the grammar"


def _rebuilt(document: dict[str, Any]) -> bytes:
    """A glTF binary of ``document`` alone: the check reads nothing but its JSON chunk."""
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
        + struct.pack("<I4s", len(payload), b"JSON")
        + payload
    )


def test_a_word_in_a_part_name_is_found():
    # The check itself, on a container whose part name carries a drafted word.
    container = sketched(CREATURES[sorted(CREATURES)[0]]["recipe"])
    assert container is not None
    document = gltf(container)
    document["meshes"][0]["name"] = f"{document['meshes'][0]['name']} {FOREIGN}"
    assert any("ravenous" in fault for fault in faults(_rebuilt(document)))


def test_a_word_anywhere_in_the_container_is_found():
    # The same for a string no name field holds, deep in the document.
    container = sketched(CREATURES[sorted(CREATURES)[0]]["recipe"])
    assert container is not None
    document = gltf(container)
    assert faults(_rebuilt(document)) == []
    document["buffers"][0]["uri"] = FOREIGN
    assert [fault for fault in faults(_rebuilt(document)) if "ravenous" in fault] == [
        f"buffers/0/uri holds {FOREIGN!r}, no name and none of the format's words"
    ]
