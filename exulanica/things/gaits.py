"""How fast a drafted body walks and swims, from the body it was given.

A society moves its people at one pace. A creature made from words may stand a hand high or as
high as a house, and it walks at a pace its own body gives: by the dynamic similarity rule of
animal walking (Alexander and Jayes, 1983), bodies of different sizes move alike at equal Froude
numbers, so speed goes as the square root of the height a body stands at. Every figure of that
rule is data, one entry each with its reason, in ``assets/catalogs/things/gaits.v1.json``:

*   the **rule** (``stance_similarity``): pace is the reference pace times the square root of the
    ratio of standing heights;
*   the **reference** standing height, the one a society's own pace is a pace for;
*   one **gait** for each way the body grammar lets a body walk, saying which chains it stands on
    (legs; tentacles where it has no leg; none for a body lying along the ground) and whether its
    pace follows the rule or is the reference pace;
*   the **limits** every pace is held to;
*   from version 2 (``gaits.v2.json``), one **swim** entry for each way the body grammar lets a body
    swim (fins, four or more tentacles, a long body, legs that paddle), saying what share of its own
    walking pace a body swims at by it.

:func:`pace_permille` is the whole of walking: a body's pace in thousandths of the society's own,
in integer arithmetic alone, so a pace recorded in a society's input is the same on any machine; it
reads version 1, as it always has. :func:`swim_pace_permille` is a body's pace in water: its walking
pace times the best share among the ways it can swim, from version 2. Neither names a creature or
reads words: a recipe's figures and the catalog.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.grammar.catalogs import CatalogSchema, load_catalog, text_field
from exulanica.things.bodies import BodyRecipe, stance_mm
from exulanica.things.catalogs import CATALOG_DIRECTORY, ThingCatalogError

__all__ = [
    "GAITS_ID",
    "PACE_PERMILLE",
    "REFERENCE_PACE_PERMILLE",
    "SWIM_MOVEMENT",
    "SWIM_VERSION",
    "Gaits",
    "gaits",
    "load_gaits",
    "pace_permille",
    "swim_pace_permille",
]

GAITS_ID: Final = "gaits"
#: The name a kind's walking move states its pace under.
PACE_PERMILLE: Final = "pace_permille"
#: A society's own pace, in thousandths of itself.
REFERENCE_PACE_PERMILLE: Final = 1000
_GROUPS: Final = ("rule", "reference", "gait", "limit", "swim")
#: What a swim entry may read: a part counted as the recipe counts it (pairs, tentacles one by one),
#: or the posture of a long body.
_SWIM_PARTS: Final = ("fin", "leg", "tentacle")
_SWIM_POSTURES: Final = ("serpentine",)
#: The version of the catalog whose swim entries a body's pace in water is read from.
SWIM_VERSION: Final = 2
#: The body grammar's movement a pace in water is stated with.
SWIM_MOVEMENT: Final = "swimming"
#: The chains a gait may stand on, in the order a body is read: a body with legs walks on them.
_STANDS_ON: Final = ("leg", "tentacle")
_PACES: Final = ("stance_similarity", "reference")
_RULE: Final = {
    "numerator": "stance_mm",
    "denominator": "reference_stance_mm",
    "root": 2,
    "scale_permille": REFERENCE_PACE_PERMILLE,
}


@dataclass(frozen=True)
class Gaits:
    """The gaits catalog, read."""

    reference_stance_mm: int
    #: Each gait that stands on chains, in the order a body is read: ``(role, follows the rule)``.
    standing: tuple[tuple[str, bool], ...]
    #: The least and the most a pace may be, in thousandths.
    minimum: int
    maximum: int
    version: int
    #: Each way a body may swim, ``(reads, least, share in thousandths)``: a part with at least
    #: ``least`` of it, or a posture (``least`` None). None before version 2.
    swimming: tuple[tuple[str, int | None, int], ...] = ()


def _spec(where: str, value: object) -> str:
    if not isinstance(value, Mapping):
        raise ThingCatalogError(f"{where}: is an object")
    return json.dumps(value, sort_keys=True)


def _group(where: str, value: object) -> str:
    if value not in _GROUPS:
        raise ThingCatalogError(f"{where}: is one of {list(_GROUPS)}")
    return str(value)


def load_gaits(version: int, directory: Path = CATALOG_DIRECTORY) -> Gaits:
    """The gaits catalog at ``version``, read and held to its shape."""
    schema = CatalogSchema(
        GAITS_ID,
        version,
        (("group", _group), ("words", text_field), ("spec", _spec), ("reason", text_field)),
    )
    catalog = load_catalog(directory / f"{GAITS_ID}.v{version}.json", schema)
    rules: list[Mapping[str, Any]] = []
    references: list[int] = []
    limits: list[Mapping[str, Any]] = []
    standing: dict[str, bool] = {}
    lying: list[str] = []
    swimming: dict[str, tuple[int | None, int]] = {}
    for entry in catalog.entries:
        values = dict(entry.values)
        where = f"{GAITS_ID}.{entry.key}"
        spec = json.loads(str(values["spec"]))
        group = values["group"]
        if group == "rule":
            if spec != _RULE:
                raise ThingCatalogError(
                    f"{where}: states the one rule this code computes: {json.dumps(_RULE)}"
                )
            rules.append(spec)
        elif group == "reference":
            value = spec.get("value")
            if set(spec) != {"value"} or type(value) is not int or not 1 <= value <= 100_000:
                raise ThingCatalogError(f"{where}: states one whole number of millimetres")
            references.append(value)
        elif group == "limit":
            limits.append(spec)
        elif group == "swim":
            reads, least, share = spec.get("reads"), spec.get("least"), spec.get("share_permille")
            part = reads in _SWIM_PARTS and type(least) is int and 1 <= least <= 64
            posture = reads in _SWIM_POSTURES and least is None
            if (
                set(spec) != {"reads", "least", "share_permille"}
                or not (part or posture)
                or reads in swimming
                or type(share) is not int
                or not 1 <= share <= REFERENCE_PACE_PERMILLE
            ):
                raise ThingCatalogError(
                    f"{where}: reads one part with how many, or one posture, once, and the share "
                    "of a body's walking pace it swims at, in thousandths, at most the whole"
                )
            swimming[str(reads)] = (least, share)
        else:
            reads, pace = spec.get("reads"), spec.get("pace")
            if set(spec) != {"reads", "pace"} or pace not in _PACES:
                raise ThingCatalogError(f"{where}: states what it reads and how its pace follows")
            if reads is None:
                if pace != "reference":
                    raise ThingCatalogError(f"{where}: a gait that reads no chain keeps the pace")
                lying.append(entry.key)
            elif reads not in _STANDS_ON or reads in standing:
                raise ThingCatalogError(f"{where}: reads one of {list(_STANDS_ON)}, once")
            else:
                standing[reads] = pace == "stance_similarity"
    if len(rules) != 1 or len(references) != 1 or len(limits) != 1 or len(lying) != 1:
        raise ThingCatalogError(
            f"{GAITS_ID}: states one rule, one reference, one entry of limits and one gait that "
            "reads no chain"
        )
    if set(standing) != set(_STANDS_ON):
        raise ThingCatalogError(f"{GAITS_ID}: states a gait for each of {list(_STANDS_ON)}")
    low, high = limits[0].get("pace_permille_minimum"), limits[0].get("pace_permille_maximum")
    if (
        set(limits[0]) != {"pace_permille_minimum", "pace_permille_maximum"}
        or type(low) is not int
        or type(high) is not int
        or not 1 <= low <= REFERENCE_PACE_PERMILLE <= high <= 10_000
    ):
        raise ThingCatalogError(
            f"{GAITS_ID}.limits: states a least and a most pace around the reference pace"
        )
    return Gaits(
        reference_stance_mm=references[0],
        standing=tuple((role, standing[role]) for role in _STANDS_ON),
        minimum=low,
        maximum=high,
        version=catalog.catalog_version,
        swimming=tuple((reads, least, share) for reads, (least, share) in sorted(swimming.items())),
    )


@cache
def gaits(version: int = 1) -> Gaits:
    """The gaits catalog this repository ships at ``version``."""
    return load_gaits(version)


def pace_permille(recipe: BodyRecipe, table: Gaits | None = None) -> int:
    """The pace of the body ``recipe`` describes, in thousandths of a society's own pace.

    The body is read as standing on the first kind of chain it has, legs before tentacles, at the
    height the body builder hangs those chains from; its pace follows the rule where that gait
    says so, the whole root of a whole quotient, held to the catalog's limits. A body that stands
    on no chain keeps the society's pace."""
    table = table or gaits()
    for role, follows in table.standing:
        stance = stance_mm(recipe, role)
        if stance is None:
            continue
        if not follows:
            return REFERENCE_PACE_PERMILLE
        pace = math.isqrt(1_000_000 * stance // table.reference_stance_mm)
        return max(table.minimum, min(table.maximum, pace))
    return REFERENCE_PACE_PERMILLE


def swim_pace_permille(recipe: BodyRecipe, table: Gaits | None = None) -> int | None:
    """The pace in water of the body ``recipe`` describes, in thousandths of a society's own pace,
    or None where it has no way to swim the table states.

    It is the body's own walking pace (:func:`pace_permille`, read from the same table) times the
    largest share among the swim entries the body meets: at least ``least`` of a part, or the
    posture named. So a larger body swims faster as it walks faster, by the same rule. A whole
    number by floor division, never less than one."""
    table = table or gaits(SWIM_VERSION)
    shares = [
        share
        for reads, least, share in table.swimming
        if (recipe.posture == reads if least is None else recipe.pairs(reads) >= least)
    ]
    if not shares:
        return None
    return max(1, pace_permille(recipe, table) * max(shares) // REFERENCE_PACE_PERMILLE)
