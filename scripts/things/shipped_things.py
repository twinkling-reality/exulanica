"""Write the thing kinds and looks this repository ships, or check the committed ones are exactly it.

    uv run python scripts/things/shipped_things.py          # write
    uv run python scripts/things/shipped_things.py --check  # exit 1 on any difference

The slice's kinds (a knight, a traveller, a lantern spirit, a visitor, a villager, a sword, a
lantern, a well and a gate) are stated here; the world object catalog's six pieces of furniture
are derived from it, their places, seats and perches as that catalog derives them, so neither
states a figure twice. Each look this repository authors pins the digest of the container its
recipe writes (exulanica/things/authored.py); each furniture look pins its reviewed asset's.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from exulanica.canonical import sha256_of_canonical  # noqa: E402
from exulanica.things.authored import AUTHORED_LOOKS, container_of  # noqa: E402
from exulanica.things.vocabularies import origin_of_character_family  # noqa: E402
from exulanica.world.assets import reviewed_asset_of  # noqa: E402
from exulanica.world.object_catalog import world_object_catalog  # noqa: E402

KINDS = ROOT / "assets/catalogs/things/kinds"
LOOKS = ROOT / "assets/catalogs/things/looks"
WALKING = "exulanica-movement/walking/v1"
#: The furniture the world object catalog states, as thing kinds; its markers are test pieces.
FURNITURE = ("bench", "cafe_table", "planter_tree", "lamp_post", "market_stall", "seating_planter")


def _origin(spdx: str) -> dict[str, Any]:
    return {
        "profile": "exulanica.origin/v1",
        "class": "authored",
        "by": {"kind": "project"},
        "sources": [],
        "licence": {
            "spdx": spdx,
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": None,
            "licence_text_sha256": None,
        },
        "authors": [],
        "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": None},
        "distribution": "public",
    }


def _look(key: str, label: str, plan: str, look_kind: str, **parts: Any) -> dict[str, Any]:
    document = {
        "profile": "exulanica.look/v1",
        "look": key,
        "version": 1,
        "label": label,
        "body_plan": plan,
        "look_kind": look_kind,
        "container": parts.get("container"),
        "rig": None,
        "height_mm": parts.get("height_mm"),
        "sampling": "linear",
        "light": parts.get("light"),
        "role": None,
        "origin": _origin("CC0-1.0"),
    }
    return document


def _people_origin() -> dict[str, Any]:
    """Where the people a routine person is drawn as came from: the one family the published
    people catalog's street population draws, read from the catalog and its definition."""
    # The character documents are the browser's, with fractional figures: read as plain JSON.
    catalog = json.loads((ROOT / "assets/characters/catalog.json").read_text("utf-8"))
    drawn = {entry["familyId"] for entry in catalog["population"]}
    families = [family for family in catalog["families"] if family["familyId"] in drawn]
    if len(families) != 1:
        raise SystemExit(f"the street population draws {sorted(drawn)}; one family is read here")
    family = families[0]
    directory = (ROOT / "assets/characters" / family["licence"]["file"]).parent
    definition = json.loads((directory / "definition.json").read_text("utf-8"))
    origin = origin_of_character_family(family, definition)
    return dict(origin.document)


def _container(data: bytes) -> dict[str, Any]:
    import hashlib

    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "media_type": "model/gltf-binary",
    }


def looks() -> dict[str, dict[str, Any]]:
    authored = {
        "blocky-traveller": ("blocky traveller", "humanoid/v1"),
        "blocky-knight": ("blocky knight", "humanoid/v1"),
        "primitive-sword": ("sword", "rigid/v1"),
        "primitive-lantern": ("lantern", "rigid/v1"),
        "primitive-well": ("well", "rigid/v1"),
        "primitive-gate": ("gate", "rigid/v1"),
    }
    assert set(authored) == set(AUTHORED_LOOKS)
    found = {}
    for key, (label, plan) in authored.items():
        kind = "rigid_on_bones" if plan == "humanoid/v1" else "static"
        found[key] = _look(
            key,
            label,
            plan,
            kind,
            container=_container(container_of(key)),
            height_mm=1700 if plan == "humanoid/v1" else None,
        )
    found["spirit-light"] = _look(
        "spirit-light",
        "drifting light",
        "bodiless/v1",
        "light",
        light={"colour": "#ffd76a", "intensity_milli": 1500, "radius_mm": 4000},
    )
    found["people-catalog"] = _look(
        "people-catalog", "one of the world's people", "humanoid/v1", "catalog_person", height_mm=1750
    )
    found["people-catalog"]["origin"] = _people_origin()
    catalog = world_object_catalog().by_key()
    for key in FURNITURE:
        kind = catalog[key]
        asset = reviewed_asset_of(kind)
        look = _look(
            key.replace("_", "-"),
            kind.title.lower(),
            "rigid/v1",
            "static",
            container=_container(asset.payload),
        )
        # The reviewed asset's own dedication, pinned by the digest its registry row carries.
        look["origin"]["licence"]["licence_text_sha256"] = asset.licence_sha256
        found[look["look"]] = look
    return found


def _ref(look: dict[str, Any]) -> dict[str, Any]:
    return {
        "look": look["look"],
        "version": look["version"],
        "sha256": sha256_of_canonical(look).hex(),
    }


def _abilities(*keys: str, **parameters: dict[str, int]) -> list[dict[str, Any]]:
    return [{"key": key, "parameters": parameters.get(key, {})} for key in keys]


def _offers(*keys: str, **parameters: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "parameters": parameters.get(key, {})} for key in keys]


_PURPOSEFUL_WEIGHTS = {"rest": 700, "visit": 1000, "stand": 300, "talk": 500}
_PEOPLE = ("wait", "stand", "talk", "rest", "visit")
_HANDS = ("pick_up", "put_down", "give", "take")


def _being(
    kind: str,
    label: str,
    summary: str,
    body: dict[str, Any],
    abilities: list[dict[str, Any]],
    offers: list[dict[str, Any]],
    routine: dict[str, Any],
    deciders: dict[str, Any],
    looks_: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "profile": "exulanica.thing-kind/v1",
        "kind": kind,
        "version": 1,
        "label": label,
        "summary": summary,
        "class": "being",
        "body": body,
        "origin": _origin("Apache-2.0"),
        "moves": [WALKING],
        "abilities": abilities,
        "offers": offers,
        "routine": routine,
        "deciders": deciders,
        "looks": looks_,
        "ext": {},
    }


def _object(
    kind: str,
    label: str,
    summary: str,
    box: tuple[int, int, int],
    blocks: bool,
    offers: list[dict[str, Any]],
    looks_: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "profile": "exulanica.thing-kind/v1",
        "kind": kind,
        "version": 1,
        "label": label,
        "summary": summary,
        "class": "object",
        "body": {
            "plan": "rigid/v1",
            "box_mm": {"width": box[0], "depth": box[1], "height": box[2]},
            "blocks_walking": blocks,
        },
        "origin": _origin("Apache-2.0"),
        "moves": [],
        "abilities": [],
        "offers": offers,
        "routine": None,
        "deciders": None,
        "looks": looks_,
        "ext": {},
    }


def kinds(made_looks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ref = {key: _ref(look) for key, look in made_looks.items()}
    anyone = {"default": "routine", "allowed": ["routine", "model", "person", "external"]}
    found = {
        "knight": _being(
            "knight",
            "knight",
            "An armoured knight who walks, carries things, hands them over and says things.",
            {"plan": "humanoid/v1", "height_mm": {"from": 1700, "to": 1900}},
            _abilities(*_PEOPLE, *_HANDS, "follow", "say"),
            _offers("talk_to", "hear", "receive", "be_followed"),
            {
                "weights": {
                    **_PURPOSEFUL_WEIGHTS,
                    "pick_up": 200,
                    "put_down": 100,
                    "give": 150,
                    "take": 100,
                    "follow": 100,
                },
                "follow_holders_of": [],
                "reason": (
                    "The purposeful routine's own weights for resting, visiting, standing and "
                    "talking, with smaller ones for its hands and for following, so left to its "
                    "routine it goes about as people do and now and then picks something up, hands "
                    "it over or follows; what it says is its decider's."
                ),
            },
            anyone,
            [ref["blocky-knight"]],
        ),
        "traveller": _being(
            "traveller",
            "traveller",
            "A traveller passing through, who walks, carries things, hands them over and talks.",
            {"plan": "humanoid/v1", "height_mm": {"from": 1550, "to": 1800}},
            _abilities(*_PEOPLE, *_HANDS, "follow", "say"),
            _offers("talk_to", "hear", "receive", "be_followed"),
            {
                "weights": {
                    **_PURPOSEFUL_WEIGHTS,
                    "pick_up": 200,
                    "put_down": 100,
                    "give": 100,
                    "take": 100,
                    "follow": 150,
                },
                "follow_holders_of": [],
                "reason": (
                    "As the knight's, a little readier to follow and a little slower to give."
                ),
            },
            anyone,
            [ref["blocky-traveller"]],
        ),
        "lantern_spirit": _being(
            "lantern_spirit",
            "lantern spirit",
            "A spirit with no body, a light that drifts and holds a small thing beside it.",
            {"plan": "bodiless/v1", "radius_mm": 200},
            _abilities("wait", "follow", "say", *_HANDS),
            _offers("talk_to", "hear", "receive", "be_followed"),
            {
                "weights": {"wait": 200, "follow": 800, "pick_up": 50, "give": 50},
                "follow_holders_of": ["lantern"],
                "reason": (
                    "A light that mostly follows, and most of all whoever carries a lantern, now "
                    "and then taking up or handing on something small."
                ),
            },
            anyone,
            [ref["spirit-light"]],
        ),
        "visitor": _being(
            "visitor",
            "visitor",
            "Someone who came into this world from another program, run by that program.",
            {"plan": "humanoid/v1", "height_mm": {"from": 1500, "to": 2000}},
            _abilities(
                "wait",
                "stand",
                "talk",
                "say",
                *_HANDS,
                "follow",
                "leave",
                leave={"quiet_minutes": 5},
            ),
            _offers("talk_to", "hear", "receive", "be_followed"),
            {
                "weights": {"wait": 700, "stand": 300},
                "follow_holders_of": [],
                "reason": (
                    "What a visitor does only when its own program gives no usable answer: it "
                    "waits or stands, and goes home after five unanswered minutes."
                ),
            },
            {"default": "external", "allowed": ["external"]},
            [],
        ),
        "villager": _being(
            "villager",
            "villager",
            "One of the world's own people, going about the purposeful routine.",
            {"plan": "humanoid/v1", "height_mm": {"from": 1500, "to": 1950}},
            _abilities(*_PEOPLE),
            _offers("talk_to", "hear"),
            {
                "weights": dict(_PURPOSEFUL_WEIGHTS),
                "follow_holders_of": [],
                "reason": "The purposeful routine's own weights, as every saved world's people.",
            },
            {"default": "routine", "allowed": ["routine", "model", "person"]},
            [ref["people-catalog"]],
        ),
        "sword": _object(
            "sword",
            "sword",
            "A sword one hand holds by its grip, the blade up.",
            (120, 40, 1000),
            False,
            _offers(
                "holdable",
                holdable={"hands": 1, "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 150}, "axis": "+z"},
            ),
            [ref["primitive-sword"]],
        ),
        "lantern": _object(
            "lantern",
            "lantern",
            "A lantern held by the ring on its cap, hanging below the hand.",
            (180, 180, 300),
            False,
            _offers(
                "holdable",
                holdable={"hands": 1, "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 290}, "axis": "-z"},
            ),
            [ref["primitive-lantern"]],
        ),
        "well": _object(
            "well",
            "well",
            "A stone well with a little roof, which people walk up to and look into.",
            (1600, 1600, 2200),
            True,
            _offers(
                "visit",
                visit={
                    "places": [
                        {"x_mm": 0, "y_mm": 1100, "faces": "-y", "seat": None},
                        {"x_mm": 0, "y_mm": -1100, "faces": "+y", "seat": None},
                    ]
                },
            ),
            [ref["primitive-well"]],
        ),
        "gate": _object(
            "gate",
            "gate",
            "A gate visitors from other programs arrive through and leave by.",
            (3000, 400, 3000),
            False,
            _offers(
                "arrive_through",
                "leave_through",
                arrive_through={
                    "point": {"x_mm": 0, "y_mm": 1000, "faces": "+y", "seat": None}
                },
            ),
            [ref["primitive-gate"]],
        ),
    }
    catalog = world_object_catalog().by_key()
    for key in FURNITURE:
        kind = catalog[key]
        use = kind.use
        width, depth, height = kind.dimensions_mm
        offers: list[dict[str, Any]] = []
        if use.affordance in ("rest", "visit") and use.places:
            places = [
                {
                    "x_mm": point[0],
                    "y_mm": point[1],
                    "faces": facing,
                    "seat": None
                    if seat is None
                    else {
                        "x_mm": seat.position_mm[0],
                        "y_mm": seat.position_mm[1],
                        "z_mm": seat.position_mm[2],
                        "faces": seat.faces,
                    },
                }
                for point, facing, seat in zip(
                    use.places, use.facing or (), use.seats or (), strict=True
                )
            ]
            offer = "rest_at" if use.affordance == "rest" else "visit"
            offers.append({"key": offer, "parameters": {"places": places}})
        if kind.perches:
            offers.append(
                {
                    "key": "perch",
                    "parameters": {
                        "perches": [
                            {"position_mm": list(perch.position_mm), "span_mm": perch.span_mm}
                            for perch in kind.perches
                        ]
                    },
                }
            )
        if kind.hosts:
            offers.append(
                {
                    "key": "host",
                    "parameters": {"flyers": {host.kind: host.count for host in kind.hosts}},
                }
            )
        found[key] = _object(
            key,
            kind.title.lower(),
            f"The world object catalog's {kind.title.lower()}, as a thing.",
            (width, depth, height),
            use.blocks_navigation,
            offers,
            [ref[key.replace("_", "-")]],
        )
    return found


def _text(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    made_looks = looks()
    made_kinds = kinds(made_looks)
    wanted = {LOOKS / f"{key}.v1.json": _text(doc) for key, doc in made_looks.items()}
    wanted |= {KINDS / f"{key}.v1.json": _text(doc) for key, doc in made_kinds.items()}
    present = {path for directory in (LOOKS, KINDS) for path in directory.glob("*.json")}
    if arguments.check:
        differing = sorted(
            str(path.relative_to(ROOT))
            for path, text in wanted.items()
            if not path.exists() or path.read_text(encoding="utf-8") != text
        )
        stray = sorted(str(path.relative_to(ROOT)) for path in present - set(wanted))
        for path in differing:
            print(f"differs: {path}")
        for path in stray:
            print(f"not written by this script: {path}")
        return 1 if differing or stray else 0
    for directory in (LOOKS, KINDS):
        directory.mkdir(parents=True, exist_ok=True)
    for path, text in wanted.items():
        path.write_text(text, encoding="utf-8")
    for path in present - set(wanted):
        path.unlink()
    print(f"wrote {len(made_looks)} looks and {len(made_kinds)} kinds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
