"""A kind's routine: the living town's routine with the kind's own workplaces, shops and homes.

The living society runs every world on a routine (:class:`~exulanica.world.society_catalogs.
RoutineModel`): needs, activities, use classes, shifts and a policy, read from versioned catalogs
and named by their digest. A world kind brings use classes of its own (a dairy, a site office, an
espresso bar) and the share of its residents who work. This module lays those over the town
routine (``TOWN_ROUTINE_VERSIONS``) as an **overlay**: a canonical document
(``exulanica.routine-overlay/v1``) holding exactly the kind's use classes and its employment
share. The overlaid routine's digest is SHA-256 over the base routine's digest and the overlay, so
a place made under it names both, and a routine with no overlay is the base routine unchanged.

Each use class is built by the rules the catalog loader builds the society's own by: what it
offers is something an activity of the routine does, visitors need both a capacity and something
to do, and its shifts are the shift catalog's; the kind's reader has held it to the use-class
schema already (:mod:`exulanica.world.kinds.document`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import CatalogError
from exulanica.world.kinds.document import KindDocument
from exulanica.world.society_catalogs import RoutineModel, UseClass

__all__ = ["OVERLAY_PROFILE", "kind_overlay", "kind_routine", "overlay_routine"]

OVERLAY_PROFILE: Final = "exulanica.routine-overlay/v1"


def kind_overlay(kind: KindDocument) -> dict[str, Any]:
    """The overlay a kind lays over the town routine: its use classes and its employment share."""
    return {
        "profile": OVERLAY_PROFILE,
        "use_classes": [dict(kind.use_classes[key]) for key in sorted(kind.use_classes)],
        "employment_share_milli": kind.employment_permille,
    }


def overlay_routine(base: RoutineModel, overlay: Mapping[str, Any]) -> RoutineModel:
    """``base`` with ``overlay``'s use classes added and its employment share in place."""
    if overlay.get("profile") != OVERLAY_PROFILE:
        raise CatalogError(f"a routine overlay is {OVERLAY_PROFILE}")
    affordances = {activity.affordance for activity in base.activities.values()}
    added: dict[str, UseClass] = {}
    for stated in overlay["use_classes"]:
        key = str(stated["key"])
        if key in base.use_classes or key in added:
            raise CatalogError(f"overlay use class {key} repeats one the routine states")
        offered = tuple(stated["visitor_affordances"])
        if not set(offered) <= affordances:
            raise CatalogError(f"overlay use class {key} offers an affordance no activity uses")
        if bool(offered) != (stated["visitor_capacity"] != 0):
            raise CatalogError(
                f"overlay use class {key}: visitors need a capacity and an affordance"
            )
        named = tuple(stated["shifts"])
        if not set(named) <= set(base.shifts):
            raise CatalogError(f"overlay use class {key} names a shift the routine does not state")
        first = base.shifts[named[0]] if named else None
        added[key] = UseClass(
            key,
            str(stated["label"]),
            str(stated["kind"]),
            str(stated["role_key"]),
            str(stated["role_label"]),
            int(stated["staff_per_unit"]),
            int(stated["visitor_capacity"]),
            int(stated["resident_capacity"]),
            offered,
            first.start_minute if first is not None else 0,
            first.minutes if first is not None else 0,
            opening=(int(stated["opening_minute"]), int(stated["closing_minute"])),
            shifts=named,
        )
    share = overlay["employment_share_milli"]
    if type(share) is not int or not 0 < share <= 1000:
        raise CatalogError("an overlay's employment share is a positive share, at most 1000")
    if "employment_share_milli" not in base.policy:
        raise CatalogError("the base routine states no employment share to replace")
    return dataclasses.replace(
        base,
        use_classes={**base.use_classes, **added},
        policy={**base.policy, "employment_share_milli": share},
        sha256=sha256_of_canonical({"base": base.sha256, "overlay": dict(overlay)}).hex(),
    )


def kind_routine(kind: KindDocument, base: RoutineModel | None = None) -> RoutineModel:
    """The routine a world of this kind lives under: the town routine with the kind's overlay."""
    if base is None:
        from exulanica.world.society_living import town_routine

        base = town_routine()
    return overlay_routine(base, kind_overlay(kind))
