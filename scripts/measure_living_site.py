#!/usr/bin/env python3
"""Measure a site world's living tick at the most people its ground admits, beside a town's.

    uv run python scripts/measure_living_site.py --ticks 60 --blocks 4 --out PATH

Pure: no database, no store and no model. It makes two living societies of 128 people, the most
the society ground catalog admits on a site and on a town:

* **A site** of a kind written here for the measurement: the hand-written test farm
  (``tests/fixtures/world-kinds/fixture-farm.json``) on a site 128 m by 192 m, its farmyard,
  fields and twelve zones of benches among obstructions laid so its walking graph comes near the
  bounds catalog's ``walking_nodes``, every person beyond the farmhouse's coming in from homes off
  the site; checked as every kind is (stage A and its sample worlds) before it is measured.
* **A town**: the market town ``scripts/measure_living_town.py`` measures, its homes holding 128
  people as that script's "stated 128" makes them.

Each is composed into its walking-surfaces-v2 input as the runtime composes one, and played
minute by minute from genesis by the living engine, in ``--blocks`` alternating blocks of
``--ticks`` minutes each, so both meet the same moments of this machine's load. Each minute's wall
and process CPU time is recorded, with the machine's idle share and load before and after. Run it
inside ``.exulanica/bin/quiet-slot``.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.composers import composer_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.samples import check_samples
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    input_routine,
    living_places,
)
from exulanica.world.society_walking_surfaces import build_walking_surfaces_input
from exulanica.world.world_recipes import town_recipe

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "living_town", ROOT / "scripts/measure_living_town.py"
)
assert _spec is not None and _spec.loader is not None
town_measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(town_measure)

#: The people each society holds: the most a site's and a town's society ground admits.
PEOPLE = 128
#: The market town and values ``scripts/measure_living_town.py`` was run with for a town's 128.
TOWN_RECIPE = "market_town"
TOWN_VALUES = {
    "city_extent_x_mm": 384000,
    "block_length_mm": 140000,
    "storey_band_low": 3,
    "storey_band_high": 5,
}
SITE = composer_module("site-plan", 1)


def site_kind() -> dict[str, Any]:
    """The measured kind: the test farm made large and busy, near the walking graph's bound."""
    farm = json.loads((ROOT / "tests/fixtures/world-kinds/fixture-farm.json").read_text("utf-8"))
    first = farm["presets"][0]["values"]

    def fixed(value: Any) -> Any:
        # Every figure the farm states by a parameter, at its first preset's value.
        if isinstance(value, dict) and set(value) == {"parameter"}:
            return first[value["parameter"]]
        if isinstance(value, dict):
            return {key: fixed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fixed(item) for item in value]
        return value

    document = fixed(copy.deepcopy(farm))
    document["kind"] = "measured_large_farm"
    document["label"] = "A large farm measured for its tick"
    document["parameters"] = []
    document["presets"] = [{"key": "only", "label": "Only", "values": {}}]
    document["site"]["width_mm"] = 128000
    document["site"]["depth_mm"] = 192000
    document["parts"].append(
        {
            "key": "meadow_bench",
            "label": "meadow bench",
            "description": "",
            "form": "fixture",
            "roles": ["seat"],
            "look": "fixture.bench",
            "use_class": "",
            "width_mm": 1800,
            "depth_mm": 600,
            "height_mm": 900,
            "seats": 3,
            "stands": 0,
            "sleepers": 0,
            "blocks": 1,
        }
    )
    document["parts"].append(
        {
            "key": "stone",
            "label": "stone",
            "description": "",
            "form": "fixture",
            "roles": ["obstruction"],
            "look": "prop.stone",
            "use_class": "",
            "width_mm": 600,
            "depth_mm": 600,
            "height_mm": 500,
            "seats": 0,
            "stands": 0,
            "sleepers": 0,
            "blocks": 1,
        }
    )
    extra = [
        {
            "key": f"meadow_{index}",
            "label": f"meadow {index}",
            "placement": "middle",
            "share": 100,
            "ground": "ground.grass",
            "access": "open",
            "boundary": "",
            "holds": [
                {"part": "meadow_bench", "count": 3, "pattern": "scatter"},
                {"part": "stone", "count": 30, "pattern": "scatter"},
            ],
        }
        for index in range(12 - len(document["zones"]))
    ]
    document["zones"] = [*document["zones"], *extra]
    # Everybody beyond the farmhouse's sleepers comes in from homes off the site.
    document["society"]["offsite_residents"] = PEOPLE - 3
    return document


def version_of(world_id: str, snapshot_id: uuid.UUID) -> AlternateVersion:
    return town_measure.version_of(world_id, snapshot_id)


def site_input(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The measured site world's living input, as the runtime composes one, and its check."""
    kind = read_kind(document)
    report = check_samples(kind)
    world_id = "world:generated:measured-site"
    composed = SITE.compose_kind(kind, kind.values("only"), world_id)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = SITE.receipt_routine(composed.receipt)
    policy = routine.policy
    built = build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=SITE.society_place(ground.place_id, composed.receipt, composed.records),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        living=routine,
    )
    return built, report


def town_input() -> dict[str, Any]:
    recipe = town_recipe(TOWN_RECIPE, TOWN_VALUES)
    towns = [made for made in (town_measure.town(recipe, i) for i in range(4)) if made]
    largest = max(towns, key=lambda t: t["document"]["population"]["size"])
    return largest["document"]


def society(document: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
    """Genesis of ``document`` at :data:`PEOPLE`, its homes made to hold them as the town
    measurement makes a town's, with its place and routine."""
    stated = town_measure.with_homes(document, PEOPLE)
    routine = input_routine(stated)
    [place] = living_places([stated], routine, {})
    state = town_measure.genesis(stated, LIVING_TOWN_PROFILE, routine, place, PEOPLE)
    return state, place, routine


def block(state: dict[str, Any], place: Any, routine: Any, ticks: int) -> tuple[Any, list, list]:
    wall, cpu = [], []
    for _ in range(ticks):
        (state, _events), w, c = town_measure.timed(
            lambda s=state: advance_living_society(s, town_measure._SEED, [place], routine)
        )
        wall.append(w * 1000)
        cpu.append(c * 1000)
    return state, wall, cpu


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    idle_before, load_before = town_measure.idle_share(), town_measure.load()
    site_document, report = site_input(site_kind())
    town_document = town_input()
    measured = {}
    societies = {"site": society(site_document), "town": society(town_document)}
    times = {name: {"wall": [], "cpu": []} for name in societies}
    for _ in range(args.blocks):
        for name in ("site", "town"):
            state, place, routine = societies[name]
            state, wall, cpu = block(state, place, routine, args.ticks)
            societies[name] = (state, place, routine)
            times[name]["wall"].extend(wall)
            times[name]["cpu"].extend(cpu)
    for name, document in (("site", site_document), ("town", town_document)):
        place = document["living"]["place"]
        measured[name] = {
            "people": PEOPLE,
            "nodes": len(place["nodes"]),
            "edges": len(place["edges"]),
            "destinations": len(place["destinations"]),
            "spots": len(place["spots"]),
            "ticks": len(times[name]["wall"]),
            "tick_wall_ms": town_measure.spread(times[name]["wall"]),
            "tick_cpu_ms": town_measure.spread(times[name]["cpu"]),
        }
    record = {
        "script": "scripts/measure_living_site.py",
        "people": PEOPLE,
        "blocks": args.blocks,
        "ticks_per_block": args.ticks,
        "site_kind_check": {"verdict": report["verdict"], "samples": len(report["samples"])},
        "town": {"recipe": TOWN_RECIPE, "values": TOWN_VALUES},
        "measured": measured,
        "machine": {
            "idle_before_percent": idle_before,
            "idle_after_percent": town_measure.idle_share(),
            "load_before": load_before,
            "load_after": town_measure.load(),
        },
    }
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"measured": measured, "machine": record["machine"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
