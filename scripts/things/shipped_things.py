"""Write the thing kinds and looks this repository ships, or check the committed ones are exactly it.

    uv run python scripts/things/shipped_things.py          # write
    uv run python scripts/things/shipped_things.py --check  # exit 1 on any difference

The first version of the slice's kinds (a knight, a traveller, a lantern spirit, a visitor, a
villager, a sword, a lantern, a well and a gate) is stated here; the world object catalog's six
pieces of furniture are derived from it, their places, seats and perches as that catalog derives
them, so neither states a figure twice. A later version of a kind is data: its committed document
(``kinds/<kind>.v<N>.json``) is the source, which this reads, checks and formats, and never writes
from figures of its own.

Every look is data: its committed document (``looks/<look>.v<N>.json``) is read and held to its
source by what it is, and a look changes only as a new version. An authored look with a recipe
(exulanica/things/authored.py) pins the container its recipe writes, and writing refreshes that
container block alone; an authored look without one pins a reviewed asset of the world object
catalog and that asset's dedication; the people catalog's look states the origin of the family the
street population draws; an imported look's container, import receipt, translation manifest
(``manifests/<look>.v<N>.json``) and the source reading the manifest accounts for are committed
beside it (``assets/things/<folder>/``). A file the script cannot hold to a source is reported.

``kinds.lock.json`` beside the kinds names every shipped version with the digest it shipped with,
and the kind loader refuses a file it does not name at that digest. Writing adds a line for each
new version and refuses to change one already there: a shipped version never changes.
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
from exulanica.grammar.documents import read_json  # noqa: E402
from exulanica.things.kinds import KINDS_LOCK, LOCK_PROFILE, read_kind_lock  # noqa: E402
from exulanica.things.kinds import read_thing_kind  # noqa: E402
from exulanica.things.authored import AUTHORED_LOOKS, container_of  # noqa: E402
from exulanica.things.looks import LookRefused, read_look  # noqa: E402
from exulanica.things.manifests import (  # noqa: E402
    ManifestRefused,
    check_accounting,
    read_manifest,
)
from exulanica.things.vocabularies import origin_of_character_family  # noqa: E402
from exulanica.world.assets import reviewed_asset_of  # noqa: E402
from exulanica.world.object_catalog import world_object_catalog  # noqa: E402

KINDS = ROOT / "assets/catalogs/things/kinds"
LOOKS = ROOT / "assets/catalogs/things/looks"
MANIFESTS = ROOT / "assets/catalogs/things/manifests"
#: Where imported looks keep their containers, import receipts and source readings, by folder.
IMPORTED = ROOT / "assets/things"
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


class LookUnheld(ValueError):
    """A committed look this script cannot hold to its source, by what is wrong."""


def _imported_files() -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every imported container, by its digest: its file and its import receipt."""
    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    for receipt_path in sorted(IMPORTED.glob("*/*.import.json")):
        receipt = read_json(receipt_path)
        container = receipt_path.with_name(receipt_path.name.removesuffix(".import.json") + ".glb")
        found[receipt["content_sha256"]] = (container, dict(receipt))
    return found


def _reviewed_assets() -> dict[str, str]:
    """Every reviewed asset the world object catalog draws, by its payload's digest, with the
    digest of its dedication."""
    found = {}
    for kind in world_object_catalog().kinds:
        asset = reviewed_asset_of(kind)
        found[_container(asset.payload)["sha256"]] = asset.licence_sha256
    return found


def _hold_imported(
    document: dict[str, Any], imported: dict[str, tuple[Path, dict[str, Any]]]
) -> str:
    """An imported look's committed sources, or :class:`LookUnheld`: its container and receipt,
    its manifest by the digest its origin names, and the source reading the manifest accounts for.
    Returns the manifest's file name."""
    held = imported.get(document["container"]["sha256"])
    if held is None:
        raise LookUnheld("no import receipt names its container")
    container, receipt = held
    if not container.exists() or _container(container.read_bytes()) != document["container"]:
        raise LookUnheld(f"{container.relative_to(ROOT)} is not the container it pins")
    if receipt["byte_size"] != document["container"]["bytes"]:
        raise LookUnheld("its import receipt states another length")
    stem = f"{document['look']}.v{document['version']}"
    manifest_path = MANIFESTS / f"{stem}.json"
    lineage = document["origin"]["lineage"]
    if not manifest_path.exists():
        raise LookUnheld(f"no manifest {manifest_path.relative_to(ROOT)}")
    manifest = read_json(manifest_path)
    if sha256_of_canonical(manifest).hex() != lineage["translation_manifest_sha256"]:
        raise LookUnheld("its origin names another manifest")
    if manifest["target"] != {
        "kind": None,
        "look": {"look": document["look"], "version": document["version"]},
    }:
        raise LookUnheld("its manifest names another look")
    reading_path = container.with_name(f"{document['look']}.source.json")
    if not reading_path.exists():
        raise LookUnheld(f"no source reading {reading_path.relative_to(ROOT)}")
    reading = read_json(reading_path)
    if sha256_of_canonical(reading).hex() != manifest["source"]["sha256"]:
        raise LookUnheld("its manifest accounts for another source reading")
    try:
        check_accounting(read_manifest(manifest), reading)
    except ManifestRefused as refused:
        raise LookUnheld(str(refused)) from refused
    return manifest_path.name


def looks() -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """Every committed look, by its file's stem, held to its source; the manifests imported looks
    name, by file name; and what could not be held, in words. A recipe look's container block is
    refreshed from its recipe, so writing keeps it current and checking reports the difference."""
    imported = _imported_files()
    reviewed = _reviewed_assets()
    people = _people_origin()
    found: dict[str, dict[str, Any]] = {}
    manifests: dict[str, str] = {}
    unheld: list[str] = []
    for path in sorted(LOOKS.glob("*.json")):
        name = str(path.relative_to(ROOT))
        document = dict(read_json(path))
        try:
            look = read_look(document)
        except LookRefused as refused:
            unheld.append(f"{name}: {refused}")
            continue
        stem = f"{look.look}.v{look.version}"
        if path.name != f"{stem}.json":
            unheld.append(f"{name}: names another look or version than it states")
            continue
        origin, kind = document["origin"], look.look_kind
        try:
            if kind == "catalog_person":
                if origin != people:
                    raise LookUnheld("its origin is not the people family's")
            elif kind == "light":
                pass
            elif origin["class"] == "imported":
                manifests[_hold_imported(document, imported)] = stem
            elif kind in ("static", "rigid_on_bones") and look.look in AUTHORED_LOOKS:
                document["container"] = _container(container_of(look.look))
            elif kind == "static":
                licence = reviewed.get(document["container"]["sha256"])
                if licence is None or origin["licence"]["licence_text_sha256"] != licence:
                    raise LookUnheld("no reviewed asset and dedication are the ones it pins")
            else:
                raise LookUnheld(f"no source holds a {kind} look here")
        except LookUnheld as unheld_look:
            unheld.append(f"{name}: {unheld_look}")
            continue
        found[stem] = document
    return found, manifests, unheld


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
    """The first version of every kind this states, by its file's stem (``sword.v1``)."""
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
                arrive_through={"point": {"x_mm": 0, "y_mm": 1000, "faces": "+y", "seat": None}},
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
    return {f"{doc['kind']}.v1": doc for doc in found.values()}


def later_versions() -> dict[str, dict[str, Any]]:
    """Every later version of a kind, by its file's stem: its committed document, read and checked
    against the things catalogs. A shipped version never changes; a changed kind is its next
    version, a new document beside the first."""
    later = {}
    for path in sorted(KINDS.glob("*.v*.json")):
        document = read_json(path)
        if document.get("version") == 1:
            continue
        kind = read_thing_kind(document)
        stem = f"{kind.kind}.v{kind.version}"
        if path.name != f"{stem}.json":
            raise SystemExit(f"{path.name} names another kind or version than it states")
        later[stem] = dict(document)
    return later


def _text(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _lock_text(locked: dict[tuple[str, int], str]) -> str:
    return _text(
        {
            "profile": LOCK_PROFILE,
            "reason": (
                "Every thing kind version this repository ships, with the digest it shipped "
                "with: a shipped version never changes, so the kind loader refuses a file this "
                "does not name at its digest, and a changed kind is a new version and a new line."
            ),
            "kinds": [
                {"kind": kind, "version": version, "sha256": digest}
                for (kind, version), digest in sorted(locked.items())
            ],
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    made_looks, manifests, unheld = looks()
    first_looks = {doc["look"]: doc for doc in made_looks.values() if doc["version"] == 1}
    made_kinds = {**kinds(first_looks), **later_versions()}
    wanted = {LOOKS / f"{stem}.json": _text(doc) for stem, doc in made_looks.items()}
    wanted |= {KINDS / f"{stem}.json": _text(doc) for stem, doc in made_kinds.items()}
    wanted |= {MANIFESTS / name: _text(read_json(MANIFESTS / name)) for name in manifests}
    present = {path for directory in (LOOKS, KINDS, MANIFESTS) for path in directory.glob("*.json")}
    for line in unheld:
        print(f"not held to a source: {line}")
    digests = {
        (doc["kind"], doc["version"]): sha256_of_canonical(doc).hex() for doc in made_kinds.values()
    }
    locked = read_kind_lock(KINDS_LOCK) if KINDS_LOCK.exists() else {}
    # A version already shipped keeps its digest and its file; anything else is a refusal.
    changed = sorted(key for key in locked if key in digests and digests[key] != locked[key])
    missing = sorted(key for key in locked if key not in digests)
    for kind, version in changed:
        print(f"refused: {kind} version {version} shipped with another digest; make a new version")
    for kind, version in missing:
        print(f"refused: {kind} version {version} shipped and has no document")
    lock_text = _lock_text({**locked, **digests} if not (changed or missing) else locked)
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
        unlocked = not KINDS_LOCK.exists() or KINDS_LOCK.read_text(encoding="utf-8") != lock_text
        if unlocked:
            print(f"differs: {KINDS_LOCK.relative_to(ROOT)}")
        return 1 if differing or stray or changed or missing or unlocked or unheld else 0
    if changed or missing or unheld:
        return 1
    for directory in (LOOKS, KINDS, MANIFESTS):
        directory.mkdir(parents=True, exist_ok=True)
    for path, text in wanted.items():
        path.write_text(text, encoding="utf-8")
    for path in present - set(wanted):
        path.unlink()
    KINDS_LOCK.write_text(lock_text, encoding="utf-8")
    print(f"wrote {len(made_looks)} looks, {len(made_kinds)} kinds and the lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
