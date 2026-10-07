"""Bodies from recipes: an imagined creature's body plan, built from a few drafted figures.

A model asked for a creature with ten legs and a long tail never writes sixty bone names with their
parents. It fills a small **body recipe**, profile ``exulanica.body-recipe/v1``: a posture (upright,
horizontal, serpentine or floating), how many torso segments, its heads and their necks and jaws,
its limbs by role (legs, arms, wings, fins in left and right pairs; tentacles in a ring), its tail,
whether a long body rises into an upright torso at the front, its extent in
millimetres, what it carries things with, the named colours its sketch is drawn in and a short
appearance for the sculptor. Every choice and bound comes from the body grammar catalog
(``assets/catalogs/things/body-grammar.v1.json``), so the vocabulary is data.

:func:`build_body` is written once and serves every creature: it turns a recipe into a body plan
document (:data:`~exulanica.things.catalogs.BODY_PLAN_PROFILE`): bones with parents in one naming
grammar (``spine2``, ``head1Neck3``, ``head1Jaw``, ``leg3Left2``, ``wing1Right3``,
``tentacle4Segment2``, ``tail4``), the chains a drawing moves together (``limbs``), the sockets
that carry things, the extent ranges a kind of it may state, the motions a look must have, and the
movement modules the body moves by, as the grammar's movement entries map what a body can do to
the modules built here. It also places every joint at rest, in whole millimetres in the slot
frame (x across with the body's left at -x, y forward, z up, the ground at 0), by one layout rule
per posture, which the sketch look is drawn from and a sculpted look is bound to. Integer
arithmetic only: the same recipe gives the same bytes on any machine.

Pure: no connection, no store, no model.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    catalog_digest,
    load_catalog,
    text_field,
)
from exulanica.grammar.documents import split_versioned_name
from exulanica.things.catalogs import (
    BODY_PLAN_BONES_MAXIMUM,
    BODY_PLAN_PROFILE,
    CATALOG_DIRECTORY,
    EXTENT_SIDES,
    ThingCatalogError,
)

__all__ = [
    "BODY_RECIPE_CODES",
    "BODY_RECIPE_PROFILE",
    "BUILDER",
    "BodyGrammar",
    "BodyRecipe",
    "BodyRefused",
    "BuiltBody",
    "body_grammar",
    "build_body",
    "load_body_grammar",
    "read_body_recipe",
]

BODY_RECIPE_PROFILE: Final = "exulanica.body-recipe/v1"
#: The builder's identity: a change to any layout rule or name below is a new version.
BUILDER: Final = "exulanica-body-builder/v1"
_CATALOG_ID: Final = "body-grammar"
_GROUPS: Final = ("posture", "part", "movement", "colour", "limit")
_PAIRED: Final = ("leg", "arm", "wing", "fin")
_HOLDS_WITH: Final = ("none", "jaws", "hands", "front_claws")
_UPPER: Final = ("none", "upright")
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_SRGB: Final = re.compile(r"#[0-9a-f]{6}")
#: The refusals a recipe meets, each with the sentence a person and a drafting model read.
BODY_RECIPE_CODES: Final = (
    (
        "body_recipe_invalid",
        "A recipe states exactly its fields, each in its shape: whole numbers, lists, the "
        "grammar's own names.",
    ),
    (
        "body_recipe_out_of_bounds",
        "Every count, segment number and size lies within the bounds the body grammar states.",
    ),
    (
        "body_part_unfit",
        "Some parts belong only to some postures: an upright torso rises only from a horizontal "
        "or serpentine body, and a floating body has no legs.",
    ),
    (
        "body_too_many_bones",
        f"A body here has at most {BODY_PLAN_BONES_MAXIMUM} bones, counting every segment of every "
        "limb, neck and tail.",
    ),
    (
        "body_holds_nothing",
        "A body carries things with jaws, hands or front claws only when it has them: jaws need a "
        "jaw, hands need arms, front claws need legs.",
    ),
    (
        "body_span_unfit",
        "A body with wings spans at least its own width with them spread; a body with none spans "
        "nothing.",
    ),
)


class BodyRefused(ValueError):
    """A body recipe this code will not read or build, by a code, the field at fault and a
    sentence."""

    def __init__(self, code: str, where: str, detail: str) -> None:
        super().__init__(f"{code} at {where}: {detail}")
        self.code = code
        self.where = where
        self.detail = detail


# -- the grammar --------------------------------------------------------------------------------


@dataclass(frozen=True)
class BodyGrammar:
    """The body grammar catalog, read: its entries' specifications by group and key."""

    postures: Mapping[str, Mapping[str, Any]]
    parts: Mapping[str, Mapping[str, Any]]
    movements: Mapping[str, Mapping[str, Any]]
    colours: Mapping[str, str]
    limits: Mapping[str, Any]
    words: Mapping[str, str]
    version: int
    sha256: str


def _spec(where: str, value: object) -> str:
    if not isinstance(value, Mapping):
        raise ThingCatalogError(f"{where}: is an object")
    try:
        return canonical_json(dict(value)).decode("utf-8")
    except CanonicalisationError as exc:
        raise ThingCatalogError(f"{where}: {exc}") from exc


def _group(where: str, value: object) -> str:
    if value not in _GROUPS:
        raise ThingCatalogError(f"{where}: is one of {list(_GROUPS)}")
    return str(value)


def _words(where: str, value: object) -> str:
    text = text_field(where, value)
    if type(text) is not str or len(text) > 120:
        raise ThingCatalogError(f"{where}: is at most 120 characters")
    return text


def _schema(version: int) -> CatalogSchema:
    return CatalogSchema(
        _CATALOG_ID,
        version,
        (("group", _group), ("words", _words), ("spec", _spec), ("reason", text_field)),
    )


def _newest(directory: Path) -> Catalog:
    versions = sorted(
        split_versioned_name(path)[1] for path in directory.glob(f"{_CATALOG_ID}.v*.json")
    )
    if not versions:
        raise ThingCatalogError(f"{directory} holds no {_CATALOG_ID} catalog")
    return load_catalog(directory / f"{_CATALOG_ID}.v{versions[-1]}.json", _schema(versions[-1]))


def load_body_grammar(directory: Path = CATALOG_DIRECTORY) -> BodyGrammar:
    """The newest body grammar catalog in ``directory``, its entries grouped and their
    specifications parsed back from canonical text."""
    catalog = _newest(directory)
    groups: dict[str, dict[str, Any]] = {group: {} for group in _GROUPS}
    words: dict[str, str] = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        spec = _parse(str(values["spec"]))
        groups[str(values["group"])][entry.key] = MappingProxyType(spec)
        words[entry.key] = str(values["words"])
    colours = {}
    for name, spec in groups["colour"].items():
        if type(spec.get("srgb")) is not str or _SRGB.fullmatch(spec["srgb"]) is None:
            raise ThingCatalogError(f"{_CATALOG_ID}.{name}: is #rrggbb")
        colours[name] = str(spec["srgb"])
    if set(groups["limit"]) != {"limits"}:
        raise ThingCatalogError(f"{_CATALOG_ID}: states one entry of limits")
    return BodyGrammar(
        postures=MappingProxyType(groups["posture"]),
        parts=MappingProxyType(groups["part"]),
        movements=MappingProxyType(groups["movement"]),
        colours=MappingProxyType(colours),
        limits=groups["limit"]["limits"],
        words=MappingProxyType(words),
        version=catalog.catalog_version,
        sha256=catalog_digest([catalog]),
    )


def _parse(text: str) -> dict[str, Any]:
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    return parsed


@cache
def body_grammar() -> BodyGrammar:
    """The grammar this process reads, once."""
    return load_body_grammar(CATALOG_DIRECTORY)


# -- the recipe ---------------------------------------------------------------------------------

_RECIPE: Final = frozenset(
    {
        "profile",
        "posture",
        "spine",
        "upper_body",
        "heads",
        "limbs",
        "tail",
        "extent_mm",
        "holds_with",
        "colours",
        "appearance",
    }
)


@dataclass(frozen=True)
class BodyRecipe:
    """A read body recipe: its document, its digest, and the figures the builder reads."""

    posture: str
    spine: int
    upper_body: bool
    #: Each head's neck bones and whether it has a jaw, in order from the body's left.
    heads: tuple[tuple[int, bool], ...]
    #: Each limb role's count (legs, arms, wings and fins in pairs; tentacles one by one) and
    #: segments; a role the recipe does not name has none.
    limbs: Mapping[str, tuple[int, int]]
    tail: int
    extent: Mapping[str, int]
    holds_with: str
    colours: tuple[str, ...]
    appearance: str
    document: Mapping[str, Any]
    sha256: str

    def pairs(self, role: str) -> int:
        return self.limbs.get(role, (0, 0))[0]

    def segments(self, role: str) -> int:
        return self.limbs.get(role, (0, 0))[1]


def _refuse(code: str, where: str, detail: str) -> BodyRefused:
    return BodyRefused(code, where, detail)


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _refuse("body_recipe_invalid", where, f"states exactly {sorted(keys)}")
    return value


def _whole(where: str, value: object, bounds: Mapping[str, Any]) -> int:
    low, high = int(bounds["minimum"]), int(bounds["maximum"])
    if type(value) is not int:
        raise _refuse("body_recipe_invalid", where, "is a whole number")
    if not low <= value <= high:
        raise _refuse("body_recipe_out_of_bounds", where, f"is from {low} to {high}")
    return value


def _plain(where: str, value: object, low: int, high: int) -> str:
    if type(value) is not str or value != value.strip() or not low <= len(value) <= high:
        raise _refuse(
            "body_recipe_out_of_bounds", where, f"is one line of {low} to {high} characters"
        )
    if any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 or ord(c) in (0x2028, 0x2029) for c in value):
        raise _refuse("body_recipe_invalid", where, "is plain text on one line")
    if any(c.isdigit() for c in value):
        raise _refuse(
            "body_recipe_invalid", where, "holds no numerals: a picture model paints numbers"
        )
    return value


def read_body_recipe(raw: object, *, grammar: BodyGrammar | None = None) -> BodyRecipe:
    """``raw`` as a body recipe, every choice from the grammar and every figure in its bounds, or
    :class:`BodyRefused` with a code from :data:`BODY_RECIPE_CODES`."""
    grammar = grammar or body_grammar()
    document = _closed("recipe", raw, _RECIPE)
    try:
        canonical_json(dict(document))
    except CanonicalisationError as exc:
        raise _refuse("body_recipe_invalid", "recipe", f"is canonical JSON: {exc}") from exc
    if document["profile"] != BODY_RECIPE_PROFILE:
        raise _refuse("body_recipe_invalid", "profile", f"is {BODY_RECIPE_PROFILE}")
    posture_key = document["posture"]
    if posture_key not in grammar.postures:
        raise _refuse("body_recipe_invalid", "posture", f"is one of {sorted(grammar.postures)}")
    posture = grammar.postures[posture_key]
    allowed = set(posture["parts"])
    spine = _whole("spine", document["spine"], posture["spine"])
    upper = document["upper_body"]
    if upper not in _UPPER:
        raise _refuse("body_recipe_invalid", "upper_body", f"is one of {list(_UPPER)}")
    if upper == "upright" and "upper_body" not in allowed:
        raise _refuse(
            "body_part_unfit",
            "upper_body",
            f"an upright torso rises only from a horizontal or serpentine body, not a "
            f"{posture_key} one",
        )
    parts = grammar.parts
    raw_heads = document["heads"]
    if not isinstance(raw_heads, list):
        raise _refuse("body_recipe_invalid", "heads", "is a list of heads")
    _whole("heads", len(raw_heads), parts["head"]["count"])
    heads = []
    for index, raw_head in enumerate(raw_heads):
        at = f"heads[{index}]"
        head = _closed(at, raw_head, frozenset({"neck", "jaw"}))
        neck = _whole(f"{at}.neck", head["neck"], parts["neck"]["bones_per_head"])
        if type(head["jaw"]) is not bool:
            raise _refuse("body_recipe_invalid", f"{at}.jaw", "is true or false")
        heads.append((neck, bool(head["jaw"])))
    raw_limbs = document["limbs"]
    if not isinstance(raw_limbs, list):
        raise _refuse("body_recipe_invalid", "limbs", "is a list of limb groups")
    limbs: dict[str, tuple[int, int]] = {}
    for index, raw_limb in enumerate(raw_limbs):
        at = f"limbs[{index}]"
        limb = _closed(at, raw_limb, frozenset({"role", "count", "segments"}))
        role = limb["role"]
        if role not in ("leg", "arm", "wing", "fin", "tentacle"):
            raise _refuse("body_recipe_invalid", f"{at}.role", "is leg, arm, wing, fin or tentacle")
        if role in limbs:
            raise _refuse("body_recipe_invalid", f"{at}.role", "names each role once")
        if role not in allowed:
            raise _refuse("body_part_unfit", f"{at}.role", f"a {posture_key} body has no {role}s")
        spec = parts[role]
        count = limb["count"]
        if type(count) is not int:
            raise _refuse("body_recipe_invalid", f"{at}.count", "is a whole number")
        if spec.get("paired"):
            if count % 2:
                raise _refuse(
                    "body_recipe_out_of_bounds",
                    f"{at}.count",
                    f"{role}s come in left and right pairs: an even number",
                )
            bounds = spec["pairs"]
            if role == "leg":
                bounds = {
                    "minimum": max(int(bounds["minimum"]), int(posture["leg_pairs"]["minimum"])),
                    "maximum": min(int(bounds["maximum"]), int(posture["leg_pairs"]["maximum"])),
                }
            low, high = int(bounds["minimum"]) * 2, int(bounds["maximum"]) * 2
            _whole(f"{at}.count", count, {"minimum": low, "maximum": high})
            number = count // 2
        else:
            number = _whole(f"{at}.count", count, spec["count"])
        segments = _whole(f"{at}.segments", limb["segments"], spec["segments"])
        if number:
            limbs[str(role)] = (number, segments)
    if "leg" not in limbs and int(posture["leg_pairs"]["minimum"]) > 0:
        raise _refuse(
            "body_recipe_out_of_bounds",
            "limbs",
            f"a {posture_key} body stands on at least {posture['leg_pairs']['minimum'] * 2} legs",
        )
    tail = _whole("tail", document["tail"], parts["tail"]["bones"])
    extent = _closed("extent_mm", document["extent_mm"], frozenset(EXTENT_SIDES))
    figures = {
        side: _whole(f"extent_mm.{side}", extent[side], posture["extent_mm"][side])
        for side in EXTENT_SIDES
    }
    if "wing" in limbs and figures["span"] < figures["width"]:
        raise _refuse(
            "body_span_unfit", "extent_mm.span", "spans at least its own width with wings spread"
        )
    if "wing" not in limbs and figures["span"]:
        raise _refuse("body_span_unfit", "extent_mm.span", "is 0 for a body with no wings")
    holds = document["holds_with"]
    if holds not in _HOLDS_WITH:
        raise _refuse("body_recipe_invalid", "holds_with", f"is one of {list(_HOLDS_WITH)}")
    if (
        (holds == "jaws" and not any(jaw for _neck, jaw in heads))
        or (holds == "hands" and "arm" not in limbs)
        or (holds == "front_claws" and "leg" not in limbs)
    ):
        raise _refuse(
            "body_holds_nothing", "holds_with", f"a body with no {holds.replace('_', ' ')} part"
        )
    limits = grammar.limits
    colours = document["colours"]
    if not isinstance(colours, list):
        raise _refuse("body_recipe_invalid", "colours", "is a list of named colours")
    _whole("colours", len(colours), limits["colours"])
    for index, colour in enumerate(colours):
        if colour not in grammar.colours:
            raise _refuse(
                "body_recipe_invalid", f"colours[{index}]", "is a colour the grammar names"
            )
    span = limits["appearance_characters"]
    appearance = _plain(
        "appearance", document["appearance"], int(span["minimum"]), int(span["maximum"])
    )
    recipe = BodyRecipe(
        posture=str(posture_key),
        spine=spine,
        upper_body=upper == "upright",
        heads=tuple(heads),
        limbs=MappingProxyType(limbs),
        tail=tail,
        extent=MappingProxyType(figures),
        holds_with=str(holds),
        colours=tuple(str(colour) for colour in colours),
        appearance=appearance,
        document=MappingProxyType(dict(document)),
        sha256=sha256_of_canonical(dict(document)).hex(),
    )
    bones = _bone_count(recipe)
    if bones > int(limits["bones_maximum"]):
        raise _refuse(
            "body_too_many_bones",
            "recipe",
            f"this body has {bones} bones; a body here has at most {limits['bones_maximum']}",
        )
    return recipe


def _bone_count(recipe: BodyRecipe) -> int:
    count = 1 + recipe.spine + (2 if recipe.upper_body else 0) + recipe.tail
    count += sum(neck + 1 + (1 if jaw else 0) for neck, jaw in recipe.heads)
    for role, (number, segments) in recipe.limbs.items():
        count += number * segments * (2 if role in _PAIRED else 1)
    return count


# -- integer geometry ---------------------------------------------------------------------------

Point = tuple[int, int, int]

#: Cosine and sine of 0 to 90 degrees in 15 degree steps, in millionths, each rounded to the
#: nearest millionth: (sqrt 6 + sqrt 2) / 4, sqrt 3 / 2, sqrt 2 / 2, one half and their
#: complements. The other directions follow by symmetry, so every turn here is integer arithmetic.
_QUADRANT: Final = (
    (1_000_000, 0),
    (965_926, 258_819),
    (866_025, 500_000),
    (707_107, 707_107),
    (500_000, 866_025),
    (258_819, 965_926),
    (0, 1_000_000),
)
_MILLION: Final = 1_000_000


def _direction(step: int) -> tuple[int, int]:
    """The cosine and sine, in millionths, of ``step`` times 15 degrees."""
    step %= 24
    quadrant, within = divmod(step, 6)
    cos, sin = _QUADRANT[within]
    for _ in range(quadrant):
        cos, sin = -sin, cos
    return cos, sin


def _tdiv(numerator: int, denominator: int) -> int:
    """Division truncated toward zero, so a left side is exactly the mirror of the right."""
    quotient = abs(numerator) // abs(denominator)
    return quotient if (numerator >= 0) == (denominator > 0) else -quotient


def _of(value: int, permille: int) -> int:
    return _tdiv(value * permille, 1000)


def _lerp(a: Point, b: Point, numerator: int, denominator: int) -> Point:
    return (
        a[0] + _tdiv((b[0] - a[0]) * numerator, denominator),
        a[1] + _tdiv((b[1] - a[1]) * numerator, denominator),
        a[2] + _tdiv((b[2] - a[2]) * numerator, denominator),
    )


def _distance(a: Point, b: Point) -> int:
    return math.isqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))


def _along(points: Sequence[Point], segments: int) -> list[Point]:
    """``segments + 1`` points spaced evenly by length along the polyline ``points``, its ends
    included: a chain's joints and its tip."""
    lengths = [_distance(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths) or 1
    placed = []
    for index in range(segments + 1):
        target = total * index // segments
        walked = 0
        for piece, length in enumerate(lengths):
            if target <= walked + length or piece == len(lengths) - 1:
                placed.append(_lerp(points[piece], points[piece + 1], target - walked, length or 1))
                break
            walked += length
    return placed


def _mirror(point: Point, side: int) -> Point:
    return (point[0] * side, point[1], point[2])


# -- the built body -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltBody:
    """A recipe built: the body plan document, and every joint at rest with its thickness."""

    plan: Mapping[str, Any]
    #: Each bone's joint at rest, where its node stands in a look of this plan.
    joints: Mapping[str, Point]
    #: Where each bone ends at rest: its child's joint, or a tip for a bone with no child.
    ends: Mapping[str, Point]
    #: Each bone's thickness at its joint and at its end, in millimetres, for the sketch.
    radii: Mapping[str, tuple[int, int]]
    #: Each wing bone's stretch of membrane, as the three or four corners it is stretched between
    #: at rest (its own segment and the matching stretch of the trailing edge), for the sketch.
    membranes: Mapping[str, tuple[Point, ...]]


class _Skeleton:
    """Bones as they are laid out: names, parents, joints, ends, radii and chains, in order."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.parents: dict[str, str | None] = {}
        self.joints: dict[str, Point] = {}
        self.ends: dict[str, Point] = {}
        self.radii: dict[str, tuple[int, int]] = {}
        self.limbs: list[dict[str, Any]] = []
        self.membranes: dict[str, tuple[Point, ...]] = {}

    def bone(
        self, name: str, parent: str | None, joint: Point, end: Point, r0: int, r1: int
    ) -> str:
        self.order.append(name)
        self.parents[name] = parent
        self.joints[name] = joint
        self.ends[name] = end
        self.radii[name] = (max(r0, 1), max(r1, 1))
        return name

    def chain(
        self,
        names: Sequence[str],
        parent: str | None,
        points: Sequence[Point],
        radii: tuple[int, int],
    ) -> list[str]:
        """Bones ``names`` along ``points`` (one more point than names), thinning from the
        first radius to the second."""
        made = []
        count = len(names)
        for index, name in enumerate(names):
            r0 = radii[0] + _tdiv((radii[1] - radii[0]) * index, count)
            r1 = radii[0] + _tdiv((radii[1] - radii[0]) * (index + 1), count)
            made.append(self.bone(name, parent, points[index], points[index + 1], r0, r1))
            parent = name
        return made

    def carrier(self, bones: Sequence[str], point: Point) -> str:
        """Of ``bones``, a chain from back to front, the one whose stretch along y holds ``point``:
        the last whose joint is not ahead of it, or the first when every joint is."""
        held = bones[0]
        for name in bones:
            if self.joints[name][1] <= point[1]:
                held = name
        return held

    def limb(self, key: str, role: str, side: str, order: int, bones: Sequence[str]) -> None:
        self.limbs.append(
            {"key": key, "role": role, "side": side, "order": order, "bones": list(bones)}
        )


_SIDES: Final = ((-1, "Left", "left"), (1, "Right", "right"))


def _torso(recipe: BodyRecipe) -> tuple[int, int, int, int, int]:
    """The horizontal body's lengths along y: torso, neck, head, tail; and the longest neck."""
    length = recipe.extent["length"]
    longest = max((neck for neck, _jaw in recipe.heads), default=0)
    torso_weight = 400
    neck_weight = 40 * longest
    head_weight = 100
    tail_weight = 45 * recipe.tail
    total = torso_weight + neck_weight + head_weight + tail_weight
    torso = length * torso_weight // total
    neck = length * neck_weight // total
    head = length * head_weight // total
    tail = length - torso - neck - head
    return torso, neck, head, tail, longest


def _heads(
    skeleton: _Skeleton,
    recipe: BodyRecipe,
    parent: str,
    base: Point,
    forward: int,
    rise_permille: int,
    head_length: int,
    radius: int,
    upright: bool,
) -> None:
    """Each head on its neck, side by side from the body's left: necks rise from ``base`` by
    ``forward`` millimetres along y (or up, for an upright body) at ``rise_permille`` of that
    upward, each head reaching ``head_length`` beyond its neck."""
    count = len(recipe.heads)
    spread = _of(recipe.extent["width"], 260)
    for index, (neck_bones, jaw) in enumerate(recipe.heads):
        number = index + 1
        offset = _tdiv((2 * index - (count - 1)) * spread, 2)
        at = parent
        point = (base[0] + _tdiv(offset, 3), base[1], base[2])
        if upright:
            top = (base[0] + offset, base[1], base[2] + forward)
        else:
            # A neck rises at its angle, but never lifts its head above the body's stated height.
            ceiling = recipe.extent["height"] - _of(radius, 550)
            lift = min(_of(forward, rise_permille), max(ceiling - base[2], 0))
            top = (base[0] + offset, base[1] + forward, base[2] + lift)
        if neck_bones:
            names = [f"head{number}Neck{bone + 1}" for bone in range(neck_bones)]
            points = _along([point, top], neck_bones)
            made = skeleton.chain(names, at, points, (_of(radius, 450), _of(radius, 380)))
            skeleton.limb(f"head{number}Neck", "neck", "centre", index, made)
            at, point = made[-1], points[-1]
        if upright:
            tip = (point[0], point[1] + _of(head_length, 300), point[2] + head_length)
        else:
            tip = (point[0], point[1] + head_length, point[2] - _of(head_length, 130))
        head_radius = _of(radius, 550)
        head = skeleton.bone(f"head{number}", at, point, tip, head_radius, _of(radius, 330))
        if jaw:
            start = _lerp(point, tip, 200, 1000)
            start = (start[0], start[1], start[2] - _of(head_radius, 600))
            end = _lerp(point, tip, 900, 1000)
            end = (end[0], end[1], end[2] - _of(head_radius, 700))
            name = skeleton.bone(
                f"head{number}Jaw", head, start, end, _of(radius, 300), _of(radius, 180)
            )
            skeleton.limb(f"head{number}Jaw", "jaw", "centre", index, [name])


def _paired(
    skeleton: _Skeleton,
    role: str,
    pairs: int,
    segments: int,
    parent: str | tuple[str, ...],
    polyline: Any,
    radii: tuple[int, int],
) -> None:
    """Every pair of a paired role, front to back, each side's chain along the polyline
    ``polyline(pair)`` gives for the right side, mirrored for the left. ``parent`` is the bone
    every pair hangs from, or a chain of bones from back to front, when each pair hangs from the
    one beside its root, so a bending spine carries each pair with its own stretch of body."""
    for pair in range(pairs):
        right = polyline(pair)
        carrier = parent if isinstance(parent, str) else skeleton.carrier(parent, right[0])
        for sign, word, side in _SIDES:
            points = _along([_mirror(point, sign) for point in right], segments)
            names = [f"{role}{pair + 1}{word}{segment + 1}" for segment in range(segments)]
            made = skeleton.chain(names, carrier, points, radii)
            skeleton.limb(f"{role}{pair + 1}{word}", role, side, pair, made)


def _tentacles(
    skeleton: _Skeleton, recipe: BodyRecipe, parent: str, centre: Point, ring: int, floor: int
) -> None:
    """Tentacles in a ring of radius ``ring`` around ``centre``, each hanging to ``floor`` and
    splaying outward, from the front of the ring round to its left."""
    count, segments = recipe.limbs["tentacle"]
    radius = max(_of(ring, 400), 2)
    for index in range(count):
        step = (index * 24 + count // 2) // count
        cos, sin = _direction(step + 6)
        root = (
            centre[0] - _tdiv(ring * cos, _MILLION),
            centre[1] + _tdiv(ring * sin, _MILLION),
            centre[2],
        )
        reach = ring * 2
        tip = (
            centre[0] - _tdiv(reach * cos, _MILLION),
            centre[1] + _tdiv(reach * sin, _MILLION),
            floor,
        )
        middle = _lerp(root, tip, 1, 2)
        middle = (middle[0], middle[1], middle[2] + _of(centre[2] - floor, 150))
        names = [f"tentacle{index + 1}Segment{segment + 1}" for segment in range(segments)]
        made = skeleton.chain(
            names, parent, _along([root, middle, tip], segments), (radius, 2 + radius // 8)
        )
        skeleton.limb(f"tentacle{index + 1}", "tentacle", "centre", index, made)


def _tail(
    skeleton: _Skeleton, recipe: BodyRecipe, start: Point, length: int, low: int, radius: int
) -> None:
    """The tail from ``start`` back along -y over ``length``, drooping to ``low``."""
    if not recipe.tail:
        return
    bones = recipe.tail
    points = []
    for index in range(bones + 1):
        # Droops slowly at first and more toward the tip: the drop goes with the square of how far
        # along it is.
        drop = _tdiv((start[2] - low) * index * index, bones * bones)
        points.append((start[0], start[1] - _tdiv(length * index, bones), start[2] - drop))
    names = [f"tail{index + 1}" for index in range(bones)]
    made = skeleton.chain(names, "hips", points, (_of(radius, 700), _of(radius, 90)))
    skeleton.limb("tail", "tail", "centre", 0, made)


def _wings(
    skeleton: _Skeleton,
    recipe: BodyRecipe,
    parent: str | tuple[str, ...],
    root_of: Any,
    torso: int,
) -> None:
    pairs, segments = recipe.limbs["wing"]
    span = recipe.extent["span"]
    half = _tdiv(span, 2)
    height = recipe.extent["height"]

    def polyline(pair: int) -> list[Point]:
        # Spread nearly level at rest, as arms are in a T-pose, rising toward the wrist no higher
        # than the body's stated height.
        root = root_of(pair)
        rise = max(min(height - root[2], _of(span, 60)), 0)
        elbow = (_of(half, 440), root[1] + _of(torso, 50), root[2] + _of(rise, 600))
        wrist = (_of(half, 760), root[1] - _of(torso, 20), root[2] + rise)
        tip = (half, root[1] - _of(torso, 450), root[2] + _of(rise, 300))
        return [root, elbow, wrist, tip]

    radius = max(_of(recipe.extent["width"], 60), 4)
    _paired(skeleton, "wing", pairs, segments, parent, polyline, (radius, _of(radius, 350)))
    for pair in range(pairs):
        right = polyline(pair)
        trailing = (_of(half, 600), right[0][1] - _of(torso, 750), right[0][2])
        body = (right[0][0], right[0][1] - _of(torso, 700), right[0][2])
        for sign, word, _side in _SIDES:
            # The membrane runs between the leading edge (the wing's bones, root to tip) and the
            # trailing edge (from the body back out to the tip), cut into one stretch a bone.
            leading = _along([_mirror(point, sign) for point in right], segments)
            edge = _along([_mirror(point, sign) for point in (body, trailing, right[-1])], segments)
            for segment in range(segments):
                corners = [leading[segment], leading[segment + 1], edge[segment + 1], edge[segment]]
                distinct = tuple(dict.fromkeys(corners))
                if len(distinct) >= 3:
                    skeleton.membranes[f"wing{pair + 1}{word}{segment + 1}"] = distinct


def _horizontal(skeleton: _Skeleton, recipe: BodyRecipe) -> None:
    extent = recipe.extent
    width, height = extent["width"], extent["height"]
    torso, neck, head, tail, longest = _torso(recipe)
    legs = recipe.pairs("leg")
    splayed = legs >= 4
    upper = recipe.upper_body
    radius = min(_of(width, 150 if splayed else 300), _of(height, 300 if splayed else 250))
    back = _of(height, 450 if upper else 600) if legs else radius
    nose = _tdiv(extent["length"], 2)
    head_start = nose - head
    chest_y = head_start - (0 if upper else neck)
    hips_y = chest_y - torso
    skeleton.bone(
        "hips",
        None,
        (0, hips_y, back),
        (0, hips_y + _tdiv(torso, recipe.spine + 1), back),
        radius,
        radius,
    )
    spine_points = [
        _lerp((0, hips_y, back), (0, chest_y, back), index, recipe.spine + 1)
        for index in range(1, recipe.spine + 2)
    ]
    names = [f"spine{index + 1}" for index in range(recipe.spine)]
    spine = skeleton.chain(names, "hips", spine_points, (radius, _of(radius, 950)))
    skeleton.limb("spine", "spine", "centre", 0, spine)
    chest = spine[-1]
    if upper:
        top_z = back + _of(height, 300)
        points = [
            (0, chest_y, back),
            (0, chest_y + _of(radius, 250), back + _of(height, 150)),
            (0, chest_y + _of(radius, 300), top_z),
        ]
        made = skeleton.chain(
            ["upper1", "upper2"], chest, points, (_of(radius, 700), _of(radius, 550))
        )
        skeleton.limb("upper", "spine", "centre", 1, made)
        anchor, base = made[-1], points[-1]
        neck_rise = height - top_z - head
        _heads(
            skeleton, recipe, anchor, base, max(neck_rise, 1), 1000, head, _of(radius, 700), True
        )
        arms_from: tuple[str, Point] | None = (anchor, points[-1])
    else:
        rise = 1000 if longest >= 3 else 577
        # Necks run from the chest's front to where the heads begin, so the nose is at the front
        # of the stated length.
        base = (0, chest_y, back + _of(radius, 300))
        _heads(skeleton, recipe, chest, base, max(neck, 1), rise, head, radius, False)
        arms_from = None
    _tail(skeleton, recipe, (0, hips_y, back), tail, max(_of(back, 300), _tdiv(radius, 2)), radius)
    if legs:
        segments = recipe.segments("leg")

        def leg(pair: int) -> list[Point]:
            y = chest_y - _tdiv(torso * (2 * pair + 1), 2 * legs)
            root = (_of(radius, 700), y, back - _of(radius, 500))
            if splayed:
                return [
                    root,
                    (_of(width, 330), y, _of(back, 1150)),
                    (_of(width, 450), y, _of(back, 450)),
                    (_of(width, 490), y, 0),
                ]
            return [
                root,
                (_of(width, 450), y + _tdiv(torso, 30), _of(back, 500)),
                (_of(width, 450), y - _tdiv(torso, 40), _of(back, 150)),
                (_of(width, 470), y + _tdiv(torso, 20), 0),
            ]

        thick = _of(radius, 220 if splayed else 360)
        _paired(skeleton, "leg", legs, segments, ("hips", *spine), leg, (thick, _of(thick, 400)))
    if "arm" in recipe.limbs:
        pairs, segments = recipe.limbs["arm"]
        if arms_from is not None:
            anchor, shoulder = arms_from

            def arm(pair: int) -> list[Point]:
                z = shoulder[2] - _of(height, 40) - _of(height, 60) * pair
                return [
                    (_of(radius, 600), shoulder[1], z),
                    (_of(radius, 600) + _of(width, 250), shoulder[1], z),
                    (_of(radius, 600) + _of(width, 450), shoulder[1], z),
                ]

            parent = anchor
        else:

            def arm(pair: int) -> list[Point]:
                y = chest_y - _tdiv(torso, 10) - _of(torso, 120) * pair
                return [
                    (_of(radius, 600), y, back),
                    (radius, y + _tdiv(torso, 20), back - _of(height, 150)),
                    (_of(radius, 900), y + _tdiv(torso, 8), back - _of(height, 200)),
                ]

            parent = chest
        thick = _of(radius, 250)
        _paired(skeleton, "arm", pairs, segments, parent, arm, (thick, _of(thick, 600)))
    if "wing" in recipe.limbs:
        _wings(
            skeleton,
            recipe,
            ("hips", *spine),
            lambda pair: (
                _of(radius, 600),
                chest_y - _of(torso, 200 + 250 * pair),
                back + _of(radius, 700),
            ),
            torso,
        )
    if "fin" in recipe.limbs:
        pairs, segments = recipe.limbs["fin"]

        def fin(pair: int) -> list[Point]:
            y = chest_y - _tdiv(torso * (2 * pair + 1), 2 * pairs)
            return [
                (radius, y, back),
                (radius + _of(width, 250), y - _tdiv(torso, 6), back - _tdiv(radius, 2)),
            ]

        _paired(
            skeleton,
            "fin",
            pairs,
            segments,
            ("hips", *spine),
            fin,
            (_of(radius, 200), _of(radius, 60)),
        )
    if "tentacle" in recipe.limbs:
        _tentacles(
            skeleton, recipe, chest, (0, chest_y - _tdiv(torso, 4), back - radius), radius, 0
        )


def _upright(skeleton: _Skeleton, recipe: BodyRecipe) -> None:
    extent = recipe.extent
    width, height = extent["width"], extent["height"]
    longest = max((neck for neck, _jaw in recipe.heads), default=0)
    radius = min(_of(width, 160), _of(height, 120))
    hips_z = _of(height, 470)
    chest_z = _of(height, 720 if longest else 780)
    neck = min(_of(height, 50) * longest, _of(height, 150))
    head = height - chest_z - neck
    skeleton.bone(
        "hips",
        None,
        (0, 0, hips_z),
        (0, 0, hips_z + _tdiv(chest_z - hips_z, recipe.spine + 1)),
        radius,
        radius,
    )
    points = [
        _lerp((0, 0, hips_z), (0, 0, chest_z), index, recipe.spine + 1)
        for index in range(1, recipe.spine + 2)
    ]
    spine = skeleton.chain(
        [f"spine{index + 1}" for index in range(recipe.spine)],
        "hips",
        points,
        (radius, _of(radius, 1100)),
    )
    skeleton.limb("spine", "spine", "centre", 0, spine)
    chest = spine[-1]
    _heads(skeleton, recipe, chest, (0, 0, chest_z), max(neck, 1), 1000, max(head, 1), radius, True)
    _tail(skeleton, recipe, (0, 0, hips_z), _of(height, 450), _of(hips_z, 150), radius)
    legs, segments = recipe.limbs["leg"]

    def leg(pair: int) -> list[Point]:
        y = 0 if legs == 1 else _of(width, 200) * (1 - 2 * pair)
        return [
            (_of(width, 110), y, hips_z),
            (_of(width, 120), y + _of(width, 20), _of(hips_z, 500)),
            (_of(width, 120), y, _of(hips_z, 60)),
            (_of(width, 120), y + _of(width, 150), 0),
        ]

    _paired(skeleton, "leg", legs, segments, "hips", leg, (_of(radius, 450), _of(radius, 250)))
    if "arm" in recipe.limbs:
        pairs, segments = recipe.limbs["arm"]

        def arm(pair: int) -> list[Point]:
            z = chest_z - _of(height, 30) - _of(height, 70) * pair
            return [(_of(width, 160), 0, z), (_of(width, 330), 0, z), (_of(width, 500), 0, z)]

        _paired(skeleton, "arm", pairs, segments, chest, arm, (_of(radius, 300), _of(radius, 180)))
    if "wing" in recipe.limbs:
        _wings(
            skeleton,
            recipe,
            chest,
            lambda pair: (
                _of(width, 100),
                -_of(width, 100),
                chest_z - _of(height, 50) * (1 + pair),
            ),
            _of(height, 400),
        )
    if "fin" in recipe.limbs:
        pairs, segments = recipe.limbs["fin"]

        def fin(pair: int) -> list[Point]:
            z = chest_z - _tdiv((chest_z - hips_z) * (2 * pair + 1), 2 * pairs)
            return [
                (radius, -_tdiv(radius, 2), z),
                (radius + _of(width, 150), -radius, z - _tdiv(radius, 2)),
            ]

        _paired(skeleton, "fin", pairs, segments, chest, fin, (_of(radius, 250), _of(radius, 80)))
    if "tentacle" in recipe.limbs:
        _tentacles(skeleton, recipe, "hips", (0, 0, hips_z), radius, 0)


def _serpentine(skeleton: _Skeleton, recipe: BodyRecipe) -> None:
    extent = recipe.extent
    length, width, height = extent["length"], extent["width"], extent["height"]
    radius = max(_tdiv(width, 2), 2)
    longest = max((neck for neck, _jaw in recipe.heads), default=0)
    head = max(_of(length, 60), width)
    neck = _of(length, 30) * longest if not recipe.upper_body else 0
    body = length - head - neck
    tail = _tdiv(body * recipe.tail, recipe.spine + recipe.tail + 1) if recipe.tail else 0
    front = _tdiv(length, 2) - head - neck
    back = front - (body - tail)
    skeleton.bone(
        "hips",
        None,
        (0, back, radius),
        (0, back + _tdiv(body - tail, recipe.spine + 1), radius),
        _of(radius, 800),
        radius,
    )
    points = [
        _lerp((0, back, radius), (0, front, radius), index, recipe.spine + 1)
        for index in range(1, recipe.spine + 2)
    ]
    spine = skeleton.chain(
        [f"spine{index + 1}" for index in range(recipe.spine)], "hips", points, (radius, radius)
    )
    skeleton.limb("spine", "spine", "centre", 0, spine)
    chest = spine[-1]
    if recipe.upper_body:
        top = (0, front, _of(height, 600))
        points = [(0, front, radius), (0, front + _tdiv(radius, 2), _tdiv(radius + top[2], 2)), top]
        made = skeleton.chain(["upper1", "upper2"], chest, points, (radius, _of(radius, 800)))
        skeleton.limb("upper", "spine", "centre", 1, made)
        rise = height - top[2] - _of(height, 120)
        _heads(skeleton, recipe, made[-1], top, max(rise, 1), 1000, _of(height, 120), radius, True)
        if "arm" in recipe.limbs:
            pairs, segments = recipe.limbs["arm"]

            def arm(pair: int) -> list[Point]:
                z = top[2] - _of(height, 40) - _of(height, 60) * pair
                return [
                    (radius, front, z),
                    (radius + _of(height, 120), front, z),
                    (radius + _of(height, 220), front, z),
                ]

            _paired(
                skeleton,
                "arm",
                pairs,
                segments,
                made[-1],
                arm,
                (_of(radius, 400), _of(radius, 250)),
            )
    else:
        _heads(
            skeleton,
            recipe,
            chest,
            (0, front, radius),
            max(neck, 1),
            900 if longest else 0,
            head,
            radius,
            False,
        )
        if "arm" in recipe.limbs:
            pairs, segments = recipe.limbs["arm"]

            def arm(pair: int) -> list[Point]:
                y = front - _of(body, 80) * (pair + 1)
                return [
                    (radius, y, radius),
                    (radius + _of(width, 600), y + _of(width, 300), radius),
                    (radius + _of(width, 900), y + _of(width, 600), 0),
                ]

            _paired(
                skeleton,
                "arm",
                pairs,
                segments,
                ("hips", *spine),
                arm,
                (_of(radius, 450), _of(radius, 250)),
            )
    if recipe.tail:
        _tail(skeleton, recipe, (0, back, radius), tail, _tdiv(radius, 2), radius)
    if "leg" in recipe.limbs:
        pairs, segments = recipe.limbs["leg"]

        def leg(pair: int) -> list[Point]:
            y = front - _tdiv((body - tail) * (2 * pair + 1), 2 * pairs)
            return [
                (radius, y, radius),
                (radius + _of(width, 500), y, radius),
                (radius + _of(width, 700), y + _of(width, 200), 0),
            ]

        _paired(
            skeleton,
            "leg",
            pairs,
            segments,
            ("hips", *spine),
            leg,
            (_of(radius, 450), _of(radius, 250)),
        )
    if "wing" in recipe.limbs:
        _wings(
            skeleton,
            recipe,
            ("hips", *spine),
            lambda pair: (radius, front - _of(body, 150 + 200 * pair), radius + _tdiv(radius, 2)),
            body,
        )
    if "fin" in recipe.limbs:
        pairs, segments = recipe.limbs["fin"]

        def fin(pair: int) -> list[Point]:
            y = front - _tdiv((body - tail) * (2 * pair + 1), 2 * pairs)
            return [
                (radius, y, radius),
                (radius + _of(width, 800), y - _of(width, 600), _tdiv(radius, 2)),
            ]

        _paired(
            skeleton,
            "fin",
            pairs,
            segments,
            ("hips", *spine),
            fin,
            (_of(radius, 300), _of(radius, 80)),
        )
    if "tentacle" in recipe.limbs:
        _tentacles(skeleton, recipe, chest, (0, front, radius), radius, 0)


def _floating(skeleton: _Skeleton, recipe: BodyRecipe) -> None:
    extent = recipe.extent
    width, height = extent["width"], extent["height"]
    radius = min(_of(width, 300), _of(height, 200))
    centre = _of(height, 650)
    bottom, top = centre - radius, centre + radius
    skeleton.bone(
        "hips",
        None,
        (0, 0, bottom),
        (0, 0, bottom + _tdiv(top - bottom, recipe.spine + 1)),
        radius,
        radius,
    )
    points = [
        _lerp((0, 0, bottom), (0, 0, top), index, recipe.spine + 1)
        for index in range(1, recipe.spine + 2)
    ]
    spine = skeleton.chain(
        [f"spine{index + 1}" for index in range(recipe.spine)],
        "hips",
        points,
        (radius, _of(radius, 700)),
    )
    skeleton.limb("spine", "spine", "centre", 0, spine)
    chest = spine[-1]
    longest = max((neck for neck, _jaw in recipe.heads), default=0)
    head = max(_of(height - top, 500), 1)
    neck = max(height - top - head, 1) if longest else 1
    _heads(skeleton, recipe, chest, (0, 0, top), neck, 1000, head, radius, True)
    _tail(skeleton, recipe, (0, 0, centre), _of(width, 600), _of(height, 200), radius)
    if "tentacle" in recipe.limbs:
        _tentacles(skeleton, recipe, "hips", (0, 0, bottom), _of(radius, 700), _of(height, 30))
    if "arm" in recipe.limbs:
        pairs, segments = recipe.limbs["arm"]

        def arm(pair: int) -> list[Point]:
            z = centre - _of(radius, 300) * pair
            return [
                (radius, 0, z),
                (radius + _of(width, 200), 0, z - _of(height, 50)),
                (radius + _of(width, 350), 0, z - _of(height, 150)),
            ]

        _paired(skeleton, "arm", pairs, segments, chest, arm, (_of(radius, 250), _of(radius, 150)))
    if "wing" in recipe.limbs:
        _wings(
            skeleton,
            recipe,
            chest,
            lambda pair: (
                _of(radius, 800),
                -_tdiv(radius, 3),
                centre + _of(radius, 400) - _of(radius, 300) * pair,
            ),
            _of(height, 400),
        )
    if "fin" in recipe.limbs:
        pairs, segments = recipe.limbs["fin"]

        def fin(pair: int) -> list[Point]:
            z = top - _tdiv((top - bottom) * (2 * pair + 1), 2 * pairs)
            return [
                (radius, 0, z),
                (radius + _of(width, 250), -_tdiv(radius, 2), z - _tdiv(radius, 2)),
            ]

        _paired(skeleton, "fin", pairs, segments, chest, fin, (_of(radius, 250), _of(radius, 70)))


_LAYOUTS: Final = {
    "horizontal": _horizontal,
    "upright": _upright,
    "serpentine": _serpentine,
    "floating": _floating,
}


def _sockets(recipe: BodyRecipe, skeleton: _Skeleton) -> list[dict[str, Any]]:
    """What carries things, as the recipe says: each head's jaw, the first arms' hands or the
    front feet, each holding one thing up to a quarter of the body's length, gripped across at most
    a sixth of its width."""
    if recipe.holds_with == "none":
        return []
    length = min(max(_tdiv(recipe.extent["length"], 4), 50), 10_000)
    section = min(max(_tdiv(recipe.extent["width"], 6), 10), 1_000)
    sockets = []
    if recipe.holds_with == "jaws":
        for index, (_neck, jaw) in enumerate(recipe.heads):
            if jaw:
                sockets.append(
                    ("mouth" if index == 0 else f"mouth.head{index + 1}", f"head{index + 1}Jaw")
                )
    else:
        role, word = ("arm", "hand") if recipe.holds_with == "hands" else ("leg", "claw")
        segments = recipe.segments(role)
        for _sign, side_word, side in _SIDES:
            sockets.append((f"{word}.{side}", f"{role}1{side_word}{segments}"))
    for _key, bone in sockets:
        assert bone in skeleton.parents, bone
    return [
        {
            "key": key,
            "bone": bone,
            "holds": 1,
            "length_mm_maximum": length,
            "grip_section_mm_maximum": section,
        }
        for key, bone in sockets
    ]


def _moves(recipe: BodyRecipe, grammar: BodyGrammar) -> list[str]:
    """The built movement modules this body can move by, in the grammar's order of movements."""
    moves = []
    for movement in sorted(grammar.movements):
        spec = grammar.movements[movement]
        if spec["module"] is None or recipe.posture in spec["never"]:
            continue
        enabled = recipe.posture in spec["enabled_by"]["postures"] or any(
            recipe.pairs(part) >= int(least)
            for part, least in sorted(spec["enabled_by"]["parts"].items())
        )
        if enabled:
            moves.append(str(spec["module"]))
    return moves


def enabled_movements(recipe: BodyRecipe, grammar: BodyGrammar | None = None) -> list[str]:
    """Every movement of the grammar this body could move by, built here or not: what a kind of
    it may ask for, refused in the movement's own words where it is not built."""
    grammar = grammar or body_grammar()
    found = []
    for movement in sorted(grammar.movements):
        spec = grammar.movements[movement]
        if recipe.posture in spec["never"]:
            continue
        if recipe.posture in spec["enabled_by"]["postures"] or any(
            recipe.pairs(part) >= int(least)
            for part, least in sorted(spec["enabled_by"]["parts"].items())
        ):
            found.append(movement)
    return found


def _range(value: int, low: int) -> dict[str, int]:
    """The range a kind of this plan may state for a figure: four fifths to five quarters of the
    recipe's own."""
    return {"minimum": max(_tdiv(value * 4, 5), low), "maximum": max(_tdiv(value * 5, 4), low, 1)}


def build_body(
    recipe: BodyRecipe,
    *,
    key: str,
    version: int,
    title: str,
    origin: Mapping[str, Any],
    grammar: BodyGrammar | None = None,
) -> BuiltBody:
    """The body plan document ``key``/v``version`` a recipe describes, with its joints at rest.

    ``origin`` is the plan's origin record (a drafted plan's names the model that drafted the
    recipe and carries the recipe's digest among its ingredients); the plan reader checks it."""
    grammar = grammar or body_grammar()
    if _KEY.fullmatch(key) is None:
        raise _refuse("body_recipe_invalid", "key", "is a lowercase key")
    skeleton = _Skeleton()
    _LAYOUTS[recipe.posture](skeleton, recipe)
    assert len(skeleton.order) == _bone_count(recipe), (len(skeleton.order), _bone_count(recipe))
    moves = _moves(recipe, grammar)
    required = ["idle"]
    if "exulanica-movement/walking/v1" in moves:
        required.append("walk")
    optional = []
    if any(jaw for _neck, jaw in recipe.heads):
        optional.append("talk")
    sockets = _sockets(recipe, skeleton)
    if sockets:
        optional.append("hold")
    extent = recipe.extent
    size = {
        "extent_mm": {
            "length": _range(extent["length"], 1),
            "width": _range(extent["width"], 1),
            "height": _range(extent["height"], 1),
            "span": _range(extent["span"], 0),
        }
    }
    plan = {
        "profile": BODY_PLAN_PROFILE,
        "key": key,
        "version": version,
        "title": title,
        "bones": [
            {"name": name, "parent": skeleton.parents[name], "required": True}
            for name in skeleton.order
        ],
        "limbs": skeleton.limbs,
        "sockets": sockets,
        "size": size,
        "reach_mm": min(max(extent["height"], 500), 20_000) if sockets else None,
        "motions": {"required": required, "optional": optional},
        "moves": moves,
        "reason": (
            f"Built by {BUILDER} from a {recipe.posture} body recipe (sha256 {recipe.sha256}): "
            f"every bone, chain, socket and range follows from the recipe and the body grammar "
            f"version {grammar.version}."
        ),
        "origin": dict(origin),
    }
    return BuiltBody(
        plan=MappingProxyType(plan),
        joints=MappingProxyType(dict(skeleton.joints)),
        ends=MappingProxyType(dict(skeleton.ends)),
        radii=MappingProxyType(dict(skeleton.radii)),
        membranes=MappingProxyType(dict(skeleton.membranes)),
    )
