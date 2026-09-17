"""Maker manifests and recipes: the checks, identical to ``loom-texture``'s ``src/recipe.ts``.

A texture set is a maker applied to a recipe. The maker's manifest says which controls it has,
what kind, unit and range each is, and which rules across controls a recipe must satisfy. A
recipe names a maker and version and states every control, the seed, the resolution and the
physical extent, with nothing left to a default.

This module is the backend's copy of the two checks, and it is held to the TypeScript copy by
``web/packages/loom-texture/test/recipe-cases.json``: both run every case there and must return
exactly the listed problems, in the listed order. A recipe proposed by a person, by the Companion
or by a model is checked here before anything stores or bakes it, and the explanation a person
sees is the same one the baker would give. Nothing here decides what a surface looks like; it
decides only whether a recipe means something the maker can bake exactly.

Documents are the parsed JSON objects, mutable or frozen (see :mod:`exulanica.materials.objects`).
A value is an integer only if it is an ``int`` that is not a ``bool`` and fits in the safe range,
because that is what JavaScript reads as an integer; a ``bool`` is never an integer here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Set
from types import MappingProxyType
from typing import Any, Final

from exulanica.materials.classes import MAKER_KINDS, MATERIAL_CLASSES, RELIEF_CLASSES
from exulanica.materials.objects import (
    MAKER_PROFILE,
    MAKER_PROFILE_V2,
    RECIPE_PROFILE,
    SAFE_INTEGER,
    MaterialObjectError,
    is_sha256,
    portable,
)

__all__ = [
    "COMMON_CONTROLS",
    "GLAZING_CONTROLS",
    "GROUPS",
    "HEIGHT_RANGE_TEXEL_LIMIT",
    "MAXIMUM_EXPRESSION_DEPTH",
    "MAXIMUM_EXTENT_MM",
    "MAXIMUM_RESOLUTION",
    "MINIMUM_RESOLUTION",
    "SURFACES",
    "UNITS",
    "check_recipe",
    "evaluate",
    "manifest_problems",
    "recipe_problems",
]

UNITS: Final = ("mm", "mm_1024ths", "q16", "percent", "permille", "count", "cells_per_tile")
GROUPS: Final = ("colour", "module", "relief", "wear", "detail", "finish", "lighting")
SURFACES: Final = ("vertical", "horizontal")
#: Controls every procedural maker whose class bakes a height field declares, because the bake reads
#: them: (unit, lowest minimum, highest maximum). The bake divides by the first and third. A glazing
#: maker declares none of them, and a model-made maker declares no controls at all.
COMMON_CONTROLS: Final = MappingProxyType(
    {
        "height_range_mm": ("mm", 1, 64),
        "occlusion_radius_mm": ("mm", 1, 64),
        "occlusion_depth_mm": ("mm", 1, 64),
        "occlusion_strength_permille": ("permille", 0, 1000),
    }
)
#: Controls every procedural glazing maker declares, because its header declares the film from them
#: (``GlazingFilm`` in ``classes``): the film's colour, and its roughness in thousandths. An integer
#: control is (kind, unit, lowest minimum, highest maximum).
GLAZING_CONTROLS: Final = MappingProxyType(
    {
        "film_colour": ("srgb",),
        "film_roughness_permille": ("integer", "permille", 0, 1000),
    }
)
MINIMUM_RESOLUTION: Final = 16
MAXIMUM_RESOLUTION: Final = 1024
MAXIMUM_EXTENT_MM: Final = 100_000
#: A conservative bound: height range times texels on an axis, at most this many times that axis
#: in mm. The baker's normal derivation stays exact up to about 90 on both axes at once, or 128 on
#: one (``maps.normalMap`` and ``isqrt`` in loom-texture), so 32 is a deliberate margin.
HEIGHT_RANGE_TEXEL_LIMIT: Final = 32
MAXIMUM_EXPRESSION_DEPTH: Final = 8

_MAKER_ID: Final = re.compile(r"[a-z][a-z0-9.-]*")
_CONTROL_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")
_FAMILY: Final = re.compile(r"[a-z][a-z0-9-]*")
_PRINTABLE: Final = re.compile(r"[\x20-\x7e]*")
_MANIFEST_KEYS: Final = (
    "profile",
    "maker_id",
    "version",
    "kind",
    "family",
    "surface",
    "truth",
    "controls",
    "constraints",
)
_PROCEDURAL_MANIFEST_KEYS: Final = (
    "profile",
    "maker_id",
    "version",
    "kind",
    "material_class",
    "family",
    "surface",
    "truth",
    "controls",
    "constraints",
)
_MODEL_MANIFEST_KEYS: Final = (*_PROCEDURAL_MANIFEST_KEYS, "generation", "maps_produced")
_GENERATION_KEYS: Final = ("model", "conditioning", "inputs", "seed", "sampler", "runtime")
_BASE_KEYS: Final = ("key", "kind", "group", "label", "explanation", "default")
_CONTROL_KEYS: Final = MappingProxyType(
    {
        "integer": (*_BASE_KEYS, "unit", "minimum", "maximum"),
        "integer_list": (
            *_BASE_KEYS,
            "unit",
            "minimum",
            "maximum",
            "minimum_items",
            "maximum_items",
        ),
        "choice": (*_BASE_KEYS, "options"),
        "srgb": _BASE_KEYS,
        "srgb_list": (*_BASE_KEYS, "minimum_items", "maximum_items"),
    }
)
_COMPARISONS: Final = ("equal", "less", "less_or_equal")
_RECIPE_KEYS: Final = ("profile", "maker", "seed", "resolution", "extent_mm", "parameters")
_EXPRESSION_SHAPE: Final = "an expression has exactly one of param, extent, constant, sum, product"


def _is_integer(value: object) -> bool:
    return type(value) is int and -SAFE_INTEGER <= value <= SAFE_INTEGER


def _is_list(value: object) -> bool:
    return isinstance(value, list | tuple)


def _is_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.strip(" ") != ""
        and _PRINTABLE.fullmatch(value) is not None
    )


def _inside(value: object, options: tuple[str, ...]) -> bool:
    return isinstance(value, str) and value in options


def _same_keys(value: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return len(value) == len(keys) and set(value) == set(keys)


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _is_colour(value: Any) -> bool:
    return (
        _is_list(value)
        and len(value) == 3
        and all(_is_integer(channel) and 0 <= channel <= 255 for channel in value)
    )


def _value_problem(control: Mapping[str, Any], value: Any) -> str | None:
    kind = control["kind"]
    if kind == "integer":
        if not _is_integer(value):
            return "is an integer"
        if not control["minimum"] <= value <= control["maximum"]:
            return f"is between {control['minimum']} and {control['maximum']}"
        return None
    if kind == "integer_list":
        if not _is_list(value):
            return "is a list of integers"
        if not control["minimum_items"] <= len(value) <= control["maximum_items"]:
            return f"holds {control['minimum_items']} to {control['maximum_items']} integers"
        if not all(
            _is_integer(item) and control["minimum"] <= item <= control["maximum"] for item in value
        ):
            return f"holds integers between {control['minimum']} and {control['maximum']}"
        return None
    if kind == "choice":
        options = tuple(control["options"])
        return None if _inside(value, options) else f"is one of {', '.join(options)}"
    if kind == "srgb":
        return None if _is_colour(value) else "is three bytes of sRGB"
    if not _is_list(value):
        return "is a list of sRGB colours"
    if not control["minimum_items"] <= len(value) <= control["maximum_items"]:
        return f"holds {control['minimum_items']} to {control['maximum_items']} colours"
    if all(_is_colour(item) for item in value):
        return None
    return "holds only three-byte sRGB colours"


def _control_shape_problem(control: Mapping[str, Any]) -> str | None:
    kind = control.get("kind")
    keys = _CONTROL_KEYS.get(kind) if isinstance(kind, str) else None
    if keys is None:
        return "kind is one of integer, integer_list, choice, srgb, srgb_list"
    if not _same_keys(control, keys):
        return f"a control of kind {kind} has exactly {', '.join(keys)}"
    key = control["key"]
    if not isinstance(key, str) or _CONTROL_KEY.fullmatch(key) is None:
        return "key is lowercase letters, digits and underscores, starting with a letter"
    if not _inside(control["group"], GROUPS):
        return f"group is one of {', '.join(GROUPS)}"
    if not _is_text(control["label"]) or not _is_text(control["explanation"]):
        return "label and explanation are non-empty printable ASCII"
    if kind in ("integer", "integer_list"):
        if not _inside(control["unit"], UNITS):
            return f"unit is one of {', '.join(UNITS)}"
        minimum, maximum = control["minimum"], control["maximum"]
        if not _is_integer(minimum) or not _is_integer(maximum) or minimum > maximum:
            return "minimum and maximum are integers, minimum first"
    if kind in ("integer_list", "srgb_list"):
        least = 1 if kind == "srgb_list" else 0
        fewest, most = control["minimum_items"], control["maximum_items"]
        if not _is_integer(fewest) or not _is_integer(most) or fewest < least or fewest > most:
            return f"minimum_items and maximum_items are integers, at least {least}, minimum first"
    if kind == "choice":
        options = control["options"]
        if (
            not _is_list(options)
            or len(options) == 0
            or not all(_is_text(option) for option in options)
            or len(set(options)) != len(options)
        ):
            return "options are distinct non-empty printable ASCII, at least one"
    return None


def _expression_problem(expression: object, integer_keys: Set[str], depth: int) -> str | None:
    if depth > MAXIMUM_EXPRESSION_DEPTH:
        return f"an expression nests at most {MAXIMUM_EXPRESSION_DEPTH} deep"
    if not isinstance(expression, Mapping) or len(expression) != 1:
        return _EXPRESSION_SHAPE
    if "param" in expression:
        param = expression["param"]
        if not isinstance(param, str):
            return "param names a control by its key"
        if param in integer_keys:
            return None
        return f"{param} is not an integer control of this maker"
    if "extent" in expression:
        return None if expression["extent"] in ("u", "v") else "extent is u or v"
    if "constant" in expression:
        return None if _is_integer(expression["constant"]) else "a constant is an integer"
    if "sum" in expression:
        terms = expression["sum"]
    elif "product" in expression:
        terms = expression["product"]
    else:
        return _EXPRESSION_SHAPE
    if not _is_list(terms) or len(terms) == 0:
        return "a sum or product has at least one term"
    for term in terms:
        problem = _expression_problem(term, integer_keys, depth + 1)
        if problem is not None:
            return problem
    return None


def _constraint_problem(
    constraint: object,
    integer_keys: Set[str],
    choices: Mapping[str, tuple[str, ...]],
) -> str | None:
    if not isinstance(constraint, Mapping):
        return "a constraint is an object"
    kind = constraint.get("kind")
    comparison = _inside(kind, _COMPARISONS)
    if not comparison and kind != "even":
        return "kind is one of equal, less, less_or_equal, even"
    keys = (
        ("kind", "left", "right", "explanation") if comparison else ("kind", "value", "explanation")
    )
    conditioned = "when" in constraint
    if not _same_keys(constraint, (*keys, "when") if conditioned else keys):
        return f"a constraint of kind {kind} has exactly {', '.join(keys)}, and may have when"
    if not _is_text(constraint["explanation"]):
        return "explanation is non-empty printable ASCII"
    for side in ("left", "right") if comparison else ("value",):
        problem = _expression_problem(constraint[side], integer_keys, 1)
        if problem is not None:
            return f"{side}: {problem}"
    if conditioned:
        when = constraint["when"]
        if not isinstance(when, Mapping) or not _same_keys(when, ("param", "equals")):
            return "when has exactly param and equals"
        param = when["param"]
        options = choices.get(param) if isinstance(param, str) else None
        if options is None:
            return "when names a choice control of this maker"
        if not _inside(when["equals"], options):
            return "when equals one of that choice's options"
    return None


def _is_settings(value: object) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(key, str)
        and _CONTROL_KEY.fullmatch(key) is not None
        and (_is_integer(item) or _is_text(item))
        for key, item in value.items()
    )


def _generation_problems(generation: object) -> list[str]:
    """Why a model-made maker's record of its generation is not well formed, or an empty list."""
    if not isinstance(generation, Mapping) or not _same_keys(generation, _GENERATION_KEYS):
        return [f"generation has exactly {', '.join(_GENERATION_KEYS)}"]
    problems: list[str] = []
    model = generation["model"]
    if not (
        isinstance(model, Mapping)
        and _same_keys(model, ("id", "revision", "weights_sha256"))
        and _is_text(model["id"])
        and _is_text(model["revision"])
        and is_sha256(model["weights_sha256"])
    ):
        problems.append(
            "generation: model has exactly an id and a revision, non-empty printable ASCII, "
            "and the weights_sha256 of its weights"
        )
    conditioning = generation["conditioning"]
    if not (
        _is_list(conditioning)
        and all(
            isinstance(given, Mapping)
            and _same_keys(given, ("role", "sha256"))
            and _is_text(given["role"])
            and is_sha256(given["sha256"])
            for given in conditioning
        )
        and len({given["role"] for given in conditioning}) == len(conditioning)
    ):
        problems.append(
            "generation: conditioning is a list of inputs, each a distinct role and the sha256 of "
            "its bytes"
        )
    given = generation["inputs"]
    prompt = (
        isinstance(given, Mapping) and _same_keys(given, ("prompt",)) and _is_text(given["prompt"])
    )
    parameters = (
        isinstance(given, Mapping)
        and _same_keys(given, ("parameters",))
        and _is_settings(given["parameters"])
        and len(given["parameters"]) > 0
    )
    if not prompt and not parameters:
        problems.append(
            "generation: inputs has exactly a prompt, non-empty printable ASCII, or parameters, "
            "integers and printable ASCII under lowercase keys"
        )
    seed = generation["seed"]
    if not _is_integer(seed) or not 0 <= seed <= 0xFFFFFFFF:
        problems.append("generation: seed is an unsigned 32-bit integer")
    sampler = generation["sampler"]
    if not (_is_settings(sampler) and "name" in sampler and _is_text(sampler["name"])):
        problems.append(
            "generation: sampler has a name and its settings, integers and printable ASCII under "
            "lowercase keys"
        )
    runtime = generation["runtime"]
    libraries = (
        runtime["libraries"]
        if isinstance(runtime, Mapping)
        and "libraries" in runtime
        and _is_list(runtime["libraries"])
        else ()
    )
    if not (
        isinstance(runtime, Mapping)
        and _same_keys(runtime, ("hardware", "libraries"))
        and _is_text(runtime["hardware"])
        and len(libraries) > 0
        and all(
            isinstance(library, Mapping)
            and _same_keys(library, ("name", "version"))
            and _is_text(library["name"])
            and _is_text(library["version"])
            for library in libraries
        )
        and len({library["name"] for library in libraries}) == len(libraries)
    ):
        problems.append(
            "generation: runtime has exactly the hardware and its libraries, at least one, each a "
            "distinct name and its version"
        )
    return problems


def manifest_problems(candidate: object) -> list[str]:
    """Why ``candidate`` is not a well-formed maker manifest, or an empty list."""
    v2 = isinstance(candidate, Mapping) and candidate.get("profile") == MAKER_PROFILE_V2
    model = v2 and candidate.get("kind") == "model"
    keys = (
        _MANIFEST_KEYS if not v2 else _MODEL_MANIFEST_KEYS if model else _PROCEDURAL_MANIFEST_KEYS
    )
    if not isinstance(candidate, Mapping) or not _same_keys(candidate, keys):
        return [f"a maker manifest has exactly {', '.join(keys)}"]
    problems: list[str] = []
    if candidate["profile"] != MAKER_PROFILE and not v2:
        problems.append(f"profile is {MAKER_PROFILE} or {MAKER_PROFILE_V2}")
    maker_id = candidate["maker_id"]
    if not isinstance(maker_id, str) or _MAKER_ID.fullmatch(maker_id) is None:
        problems.append(
            "maker_id is lowercase letters, digits, dots and hyphens, starting with a letter"
        )
    version = candidate["version"]
    if not _is_integer(version) or version < 1:
        problems.append("version is a positive integer")
    if not v2 and candidate["kind"] != "procedural":
        problems.append("kind is procedural")
    if v2 and not _inside(candidate["kind"], MAKER_KINDS):
        problems.append(f"kind is one of {', '.join(MAKER_KINDS)}")
    if v2 and not _inside(candidate["material_class"], MATERIAL_CLASSES):
        problems.append(f"material_class is one of {', '.join(MATERIAL_CLASSES)}")
    family = candidate["family"]
    if not isinstance(family, str) or _FAMILY.fullmatch(family) is None:
        problems.append("family is lowercase letters, digits and hyphens, starting with a letter")
    if not _inside(candidate["surface"], SURFACES):
        problems.append(f"surface is one of {', '.join(SURFACES)}")
    if candidate["truth"] != "invented":
        problems.append("truth is invented")
    if model:
        problems.extend(_generation_problems(candidate["generation"]))
        produced = candidate["maps_produced"]
        if not (
            isinstance(produced, Mapping)
            and _same_keys(produced, ("normal", "height"))
            and type(produced["normal"]) is bool
            and type(produced["height"]) is bool
        ):
            problems.append("maps_produced has exactly normal and height, each true or false")
    controls = candidate["controls"]
    if not _is_list(controls):
        return [*problems, "controls is a list"]
    constraints = candidate["constraints"]
    if not _is_list(constraints):
        return [*problems, "constraints is a list"]
    if model and len(controls) > 0:
        problems.append(
            "a model-made maker declares no controls; a variation is a new generation and a new "
            "version"
        )
    if model and len(constraints) > 0:
        problems.append("a model-made maker declares no constraints")

    declared: dict[str, Mapping[str, Any]] = {}
    for index, control in enumerate(controls):
        if not isinstance(control, Mapping):
            problems.append(f"controls[{index}]: a control is an object")
            continue
        shape = _control_shape_problem(control)
        if shape is not None:
            problems.append(f"controls[{index}]: {shape}")
            continue
        key = control["key"]
        if key in declared:
            problems.append(f"controls[{index}]: {key} is declared twice")
            continue
        declared[key] = control
        problem = _value_problem(control, control["default"])
        if problem is not None:
            problems.append(f"controls[{index}]: default {problem}")
    # A v1 maker is opaque. A procedural maker of a class that bakes a height field declares the
    # controls the bake reads; a glazing maker, which bakes none, declares none of them.
    relief = not v2 or (not model and candidate["material_class"] in RELIEF_CLASSES)
    for key, (unit, lowest, highest) in COMMON_CONTROLS.items():
        control = declared.get(key)
        if relief and (
            control is None
            or control["kind"] != "integer"
            or control["unit"] != unit
            or control["minimum"] < lowest
            or control["maximum"] > highest
        ):
            problems.append(
                f"{key} is an integer control in {unit} within {lowest} to {highest}, "
                "because the bake reads it"
            )
        if (
            not relief
            and not model
            and candidate["material_class"] == "glazing"
            and control is not None
        ):
            problems.append(
                f"{key} is not a control of a glazing maker, whose bake reads no height field"
            )
    if v2 and not model and candidate["material_class"] == "glazing":
        for key, wanted in GLAZING_CONTROLS.items():
            control = declared.get(key)
            if wanted[0] == "srgb":
                if control is None or control["kind"] != "srgb":
                    problems.append(
                        f"{key} is an srgb control, because the header declares the film from it"
                    )
                continue
            _, unit, lowest, highest = wanted
            if (
                control is None
                or control["kind"] != "integer"
                or control["unit"] != unit
                or control["minimum"] < lowest
                or control["maximum"] > highest
            ):
                problems.append(
                    f"{key} is an integer control in {unit} within {lowest} to {highest}, "
                    "because the header declares the film from it"
                )

    integer_keys = {key for key, control in declared.items() if control["kind"] == "integer"}
    choices = {
        key: tuple(control["options"])
        for key, control in declared.items()
        if control["kind"] == "choice"
    }
    for index, constraint in enumerate(constraints):
        problem = _constraint_problem(constraint, integer_keys, choices)
        if problem is not None:
            problems.append(f"constraints[{index}]: {problem}")
    if not problems and not portable(candidate):
        problems.append("a manifest is canonical JSON: integers and printable ASCII only")
    return problems


def evaluate(expression: Mapping[str, Any], recipe: Mapping[str, Any]) -> int | None:
    """An expression's value, or ``None`` where the arithmetic leaves the safe integer range."""
    if "param" in expression:
        value: int = recipe["parameters"][expression["param"]]
        if not _is_integer(value):
            raise MaterialObjectError(
                f"expression names {expression['param']}, which is not an integer control"
            )
        return value
    if "extent" in expression:
        axis: int = recipe["extent_mm"][expression["extent"]]
        return axis
    if "constant" in expression:
        constant: int = expression["constant"]
        return constant
    adding = "sum" in expression
    total = 0 if adding else 1
    for term in expression["sum"] if adding else expression["product"]:
        value = evaluate(term, recipe)
        if value is None:
            return None
        total = total + value if adding else total * value
        if not -SAFE_INTEGER <= total <= SAFE_INTEGER:
            return None
    return total


def _holds(constraint: Mapping[str, Any], recipe: Mapping[str, Any]) -> bool | None:
    when = constraint.get("when")
    if when is not None and recipe["parameters"][when["param"]] != when["equals"]:
        return True
    if constraint["kind"] == "even":
        value = evaluate(constraint["value"], recipe)
        return None if value is None else value % 2 == 0
    left = evaluate(constraint["left"], recipe)
    right = evaluate(constraint["right"], recipe)
    if left is None or right is None:
        return None
    if constraint["kind"] == "equal":
        return left == right
    if constraint["kind"] == "less":
        return left < right
    return left <= right


def recipe_problems(candidate: object, manifest: Mapping[str, Any]) -> list[str]:
    """Why ``candidate`` is not a valid recipe for ``manifest``, or an empty list.

    ``manifest`` must already be well formed; :func:`manifest_problems` is the check for that.
    """
    if not isinstance(candidate, Mapping) or not _same_keys(candidate, _RECIPE_KEYS):
        return [f"a recipe has exactly {', '.join(_RECIPE_KEYS)}"]
    problems: list[str] = []
    if candidate["profile"] != RECIPE_PROFILE:
        problems.append(f"profile is {RECIPE_PROFILE}")
    maker = candidate["maker"]
    if (
        not isinstance(maker, Mapping)
        or not _same_keys(maker, ("id", "version"))
        or not isinstance(maker["id"], str)
        or maker["id"] != manifest["maker_id"]
        or not _is_integer(maker["version"])
        or maker["version"] != manifest["version"]
    ):
        problems.append(f"maker is {manifest['maker_id']} version {manifest['version']}")
    seed = candidate["seed"]
    if not _is_integer(seed) or not 0 <= seed <= 0xFFFFFFFF:
        problems.append("seed is an unsigned 32-bit integer")
    resolution = candidate["resolution"]
    if not (
        isinstance(resolution, Mapping)
        and _same_keys(resolution, ("width", "height"))
        and all(
            _is_integer(axis)
            and _is_power_of_two(axis)
            and MINIMUM_RESOLUTION <= axis <= MAXIMUM_RESOLUTION
            for axis in (resolution["width"], resolution["height"])
        )
    ):
        problems.append(
            f"resolution is a power of two from {MINIMUM_RESOLUTION} to "
            f"{MAXIMUM_RESOLUTION} on each axis"
        )
    extent = candidate["extent_mm"]
    if not (
        isinstance(extent, Mapping)
        and _same_keys(extent, ("u", "v"))
        and all(
            _is_integer(axis) and 0 < axis <= MAXIMUM_EXTENT_MM
            for axis in (extent["u"], extent["v"])
        )
    ):
        problems.append(f"extent_mm is a whole-millimetre u and v from 1 to {MAXIMUM_EXTENT_MM}")
    parameters = candidate["parameters"]
    if not isinstance(parameters, Mapping):
        return [*problems, "parameters is an object"]
    controls = manifest["controls"]
    declared = {control["key"] for control in controls}
    undeclared = sorted(
        key
        if isinstance(key, str) and _PRINTABLE.fullmatch(key)
        else "a key that is not printable ASCII"
        for key in parameters
        if key not in declared
    )
    problems.extend(
        f"parameters: {key} is not a control of {manifest['maker_id']}" for key in undeclared
    )
    for control in controls:
        key = control["key"]
        if key not in parameters:
            problems.append(f"parameters: {key} is missing; a recipe states every control")
            continue
        problem = _value_problem(control, parameters[key])
        if problem is not None:
            problems.append(f"parameters: {key} {problem}")
    if problems:
        return problems

    if manifest["kind"] == "model" and seed != manifest["generation"]["seed"]:
        problems.append("seed is the seed the model generated with")
    height_range = parameters.get("height_range_mm")
    if _is_integer(height_range) and (
        height_range * resolution["width"] > HEIGHT_RANGE_TEXEL_LIMIT * extent["u"]
        or height_range * resolution["height"] > HEIGHT_RANGE_TEXEL_LIMIT * extent["v"]
    ):
        problems.append(
            f"height_range_mm times the texels on an axis is at most {HEIGHT_RANGE_TEXEL_LIMIT} "
            "times that axis in mm, a margin that keeps the bake's normals exact"
        )
    for constraint in manifest["constraints"]:
        verdict = _holds(constraint, candidate)
        if verdict is None:
            problems.append(
                f"{constraint['explanation']} (its arithmetic leaves the safe integer range)"
            )
        elif not verdict:
            problems.append(constraint["explanation"])
    return problems


def check_recipe(candidate: object, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Refuse, naming every problem, or return the recipe."""
    problems = recipe_problems(candidate, manifest)
    if problems:
        raise MaterialObjectError(
            f"not a valid {manifest['maker_id']} recipe: {'; '.join(problems)}"
        )
    return candidate  # a recipe that passed every check
