"""Hand-written test kinds as the brief a model would fill in, for the kind drafter's tests and
the drafting measurement's dry run (:mod:`exulanica.selection.kind_brief`)."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
#: What a drafted kind records of how it was drafted, as the drafter states it.
PROVENANCE = {
    "role": "specification_drafter",
    "model": "test/model",
    "prompt_version": "kind-drafting-4",
    "prompt_sha256": "0" * 64,
    "words_sha256": "1" * 64,
}
_USE_ROLES = ("home", "shop", "workplace")
_COMPILED_ROLES = ("path", "road", "boundary")


def fixture_kind(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))


def _span(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {"from": value["from"], "to": value["to"]}
    return {"from": value, "to": value}


def brief_of(document: Mapping[str, Any]) -> dict[str, Any]:
    """The brief stating what a hand-written kind states at its first preset, as a model would
    fill it in: what each zone holds nested in it, and each part's use where it stands."""
    first = document["presets"][0]["values"]

    def fixed(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"parameter"}:
            return first[value["parameter"]]
        if isinstance(value, dict):
            return {key: fixed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fixed(item) for item in value]
        return value

    kind = fixed(copy.deepcopy(dict(document)))
    parts = {part["key"]: part for part in kind["parts"]}
    uses = {use["key"]: use for use in kind["use_classes"]}

    def use_role(part: Mapping[str, Any]) -> str:
        return next((role for role in part["roles"] if role in _USE_ROLES), "")

    def others(part: Mapping[str, Any]) -> list[str]:
        return [r for r in part["roles"] if r not in _USE_ROLES and r not in _COMPILED_ROLES]

    def work(part: Mapping[str, Any]) -> list[dict[str, Any]]:
        use = uses.get(part["use_class"])
        if use is None or use["kind"] != "workplace":
            return []
        return [
            {
                "role_label": use["role_label"],
                "staff_per_unit": use["staff_per_unit"],
                "opening_minute": use["opening_minute"],
                "closing_minute": use["closing_minute"],
                "shifts": list(use["shifts"]),
            }
        ]

    def visit(part: Mapping[str, Any]) -> list[dict[str, Any]]:
        use = uses.get(part["use_class"])
        if use is None or use["kind"] != "workplace" or not use["visitor_capacity"]:
            return []
        return [
            {
                "visitor_capacity": use["visitor_capacity"],
                "visitor_affordances": list(use["visitor_affordances"]),
            }
        ]

    def common(part: Mapping[str, Any], holding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "label": part["label"],
            "description": part["description"],
            "look": part["look"],
            "count": _span(holding["count"]),
        }

    def fixture(part: Mapping[str, Any], holding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **common(part, holding),
            "pattern": holding["pattern"],
            **{name: part[name] for name in ("width_mm", "depth_mm", "height_mm")},
            **{name: part[name] for name in ("seats", "stands", "sleepers")},
            "blocks": bool(part["blocks"]),
            "use_role": use_role(part),
            "roles": others(part),
            "work": work(part),
            "visit": visit(part),
        }

    def room(part: Mapping[str, Any], holding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **common(part, holding),
            "share": part["share"],
            "fixtures": [fixture(parts[held["part"]], held) for held in part["holds"]],
        }

    def residents(part: Mapping[str, Any]) -> int:
        use = uses.get(part["use_class"])
        return int(use["resident_capacity"]) if use and use["kind"] == "residential" else 0

    def structure(part: Mapping[str, Any], holding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **common(part, holding),
            "width_mm": _span(part["width_mm"]),
            "depth_mm": _span(part["depth_mm"]),
            "storeys": _span(part["storeys"]),
            **{
                name: part[name]
                for name in (
                    "storey_height_mm",
                    "roof_form",
                    "roof_look",
                    "wall_look",
                    "door_width_mm",
                )
            },
            "use_role": use_role(part),
            "residents": residents(part),
            "work": work(part),
            "visit": visit(part),
            "rooms": [room(parts[held["part"]], held) for held in part["rooms"]],
        }

    def area(part: Mapping[str, Any], holding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **common(part, holding),
            "use_role": use_role(part),
            "roles": others(part),
            "work": work(part),
        }

    makers = {"structure": structure, "area": area, "fixture": fixture}
    zones = []
    for zone in kind["zones"]:
        held = [(parts[holding["part"]], holding) for holding in zone["holds"]]
        listed = {
            f"{form}s": [
                makers[form](part, holding) for part, holding in held if part["form"] == form
            ]
            for form in makers
        }
        zones.append(
            {
                "label": zone["label"],
                "placement": zone["placement"],
                "share": zone["share"],
                "ground": zone["ground"],
                "access": zone["access"],
                "fenced": bool(zone["boundary"]),
                **listed,
            }
        )
    site = kind["site"]
    spine = parts[site["spine"]]
    walls = parts.get(site["boundary"]) or next(
        parts[zone["boundary"]] for zone in kind["zones"] if zone["boundary"]
    )
    society = kind["society"]
    return {
        "kind": kind["kind"],
        "label": kind["label"],
        "summary": kind["summary"],
        "enclosure": site["enclosure"],
        "site_width_mm": site["width_mm"],
        "site_depth_mm": site["depth_mm"],
        "ground": site["ground"],
        "site_fenced": bool(site["boundary"]),
        "employment_permille": society["employment_permille"],
        "offsite_residents": society["offsite_residents"],
        "offsite_home": "homes nearby",
        "place_words": {"here": "here", "around": "around here"},
        "spine": {
            "label": spine["label"],
            "look": spine["look"],
            "width_mm": spine["width_mm"],
            "road": "road" in spine["roles"],
        },
        "boundary": {
            "label": walls["label"],
            "look": walls["look"],
            **{name: walls[name] for name in ("height_mm", "thickness_mm", "gate_width_mm")},
        },
        "zones": zones,
    }


def held_to_form(brief: Mapping[str, Any]) -> dict[str, Any]:
    """The brief as the form reads it: refused here when a reply like it would be."""
    from exulanica.selection.kind_brief import brief_form

    return brief_form().model_validate(brief).model_dump(mode="json")  # type: ignore[no-any-return]
