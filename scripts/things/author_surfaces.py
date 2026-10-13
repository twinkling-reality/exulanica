"""Write a validated authored body/look/kind bundle from declarative input, without a model.

Usage: uv run python scripts/things/author_surfaces.py SOURCE --output DIRECTORY
The directory contains reusable documents, GLB, and an authoring receipt, never runtime code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.things.bodies import build_body, read_body_recipe
from exulanica.things.body_surfaces import author_surface_look
from exulanica.things.catalogs import read_body_plan
from exulanica.things.creatures import Creature
from exulanica.things.kinds import THING_KIND_PROFILE, read_thing_kind


def assemble_authored(source: dict[str, Any]) -> tuple[Creature, dict[str, Any]]:
    """Assemble original content, preserving authored provenance and existing kind validation."""
    if set(source) != {"recipe", "body", "surface", "look", "kind", "origin"}:
        raise ValueError("source states recipe, body, surface, look, kind and origin")
    origin = source["origin"]
    if origin["class"] != "authored":
        raise ValueError("this authoring path requires authored provenance")
    recipe = read_body_recipe(source["recipe"])
    # The ordinary society run-form reader requires this ingredient, independently of looks.
    body_origin = dict(origin) | {
        "lineage": dict(origin["lineage"])
        | {"ingredients": list(dict.fromkeys([*origin["lineage"]["ingredients"], recipe.sha256]))}
    }
    built = build_body(recipe, **source["body"], origin=body_origin)
    plan = read_body_plan(dict(built.plan))
    look, payload, receipt = author_surface_look(
        source["surface"], built, recipe, **source["look"], origin=origin
    )
    kind = read_thing_kind(
        {
            **source["kind"],
            "profile": THING_KIND_PROFILE,
            "body": {
                "plan": plan.name,
                "plan_sha256": plan.sha256,
                "extent_mm": dict(recipe.extent),
            },
            "origin": dict(body_origin)
            | {
                "lineage": dict(body_origin["lineage"])
                | {"ingredients": [*body_origin["lineage"]["ingredients"], plan.sha256]}
            },
            "looks": [look.reference()],
        },
        plan_of=lambda name: plan if name == plan.name else None,
        look_of=lambda ref: look if dict(ref) == look.reference() else None,
    )
    return Creature(
        MappingProxyType(dict(recipe.document)),
        recipe.sha256,
        plan,
        built.plan,
        look,
        payload,
        kind,
    ), dict(receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--look-only", action="store_true", help="Write only the compatible look, GLB and receipt"
    )
    args = parser.parse_args()
    creature, receipt = assemble_authored(json.loads(args.source.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    for key, document in creature.documents.items():
        if args.look_only and key != "look":
            continue
        (args.output / f"{key}.json").write_bytes(canonical_json(dict(document)))
    (args.output / "body.glb").write_bytes(creature.sketch_container)
    (args.output / "receipt.json").write_bytes(canonical_json(receipt))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
