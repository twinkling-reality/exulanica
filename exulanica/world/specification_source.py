"""The world specification a draft is built from and judged by, as the specification states it.

The drafter (:mod:`exulanica.selection.world_drafting`), its route and the sample town read the
specification through these three functions and nothing else, so what they read is what a person's
own values meet at ``POST /worlds/generated``:

*   :func:`served_document`: the document ``GET /worlds/specification`` serves;
*   :func:`value_refusal`: the gate's own check of a preset and values (``town_recipe``), as a
    refusal by name with the range and step it broke, or None;
*   :func:`composed_town`: the town a preset makes with values for a world identity, before
    anything is written, by the gate and the composer every generated world passes
    (``compose_specified_world``), refused by the same names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["ValueRefusal", "composed_town", "served_document", "value_refusal"]


@dataclass(frozen=True, slots=True)
class ValueRefusal:
    """The validation's refusal of a proposed preset and values, by name, with what it broke."""

    code: str
    detail: str
    key: str | None = None
    value: int | str | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    #: A choice's range, where the refused key takes one of several keys.
    choices: tuple[str, ...] = ()
    #: For values that disagree, the other key and its value, which narrowed this one's range.
    with_key: str | None = None
    with_value: int | str | None = None


def served_document() -> Mapping[str, Any]:
    """The document ``GET /worlds/specification`` serves."""
    from exulanica.world.world_recipes import specification_document

    return specification_document()


def value_refusal(preset: str, values: Mapping[str, int | str]) -> ValueRefusal | None:
    """The refusal the gate every request for a world passes gives ``preset`` with ``values``
    (``town_recipe``), by name with the range it broke, or None when it accepts them."""
    from exulanica.world.world_recipes import SpecificationRefused, UnknownWorldRecipe, town_recipe

    try:
        town_recipe(preset, values)
    except UnknownWorldRecipe as refused:
        return ValueRefusal(code=refused.code, detail=str(refused))
    except SpecificationRefused as refused:
        stated = refused.document()
        bounds = stated["range"] or {}
        return ValueRefusal(
            code=refused.code,
            detail=refused.detail,
            key=refused.key or None,
            value=refused.value if isinstance(refused.value, int | str) else None,
            minimum=bounds.get("minimum"),
            maximum=bounds.get("maximum"),
            step=bounds.get("step"),
            choices=tuple(bounds.get("choices") or ()),
            with_key=(stated.get("with") or {}).get("key"),
            with_value=(stated.get("with") or {}).get("value"),
        )
    return None


def composed_town(preset: str, values: Mapping[str, int | str], world_id: str) -> Any:
    """The town ``preset`` makes with ``values`` for ``world_id``, through the same gate and
    composer ``POST /worlds/generated`` makes a world through, and nothing written."""
    from exulanica.world.generated_worlds import compose_specified_world

    return compose_specified_world(preset, values, world_id)
