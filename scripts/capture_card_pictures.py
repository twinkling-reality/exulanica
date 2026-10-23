"""Capture the pictures on Create's starter cards, when a release is built.

Each card Create serves (a recipe of ``GET /worlds/specification``, a shipped kind of ``GET
/worlds/kinds``) shows the first view of a world made from it, through the page's own route, as the
page keeps a world's first view. This step makes those worlds on a running personal install,
scales each first view to the card's size and writes the pictures and their record,
``web/packages/app/public/card-pictures/card-pictures.v1.json`` (profile
``exulanica.card-pictures/v1``). Each entry states the card, the reference of the world it was
made from (a recipe's, as ``town_recipe(key, values).reference()`` states it, or a kind's key,
version and digest), the picture and its digest and size, the world and entry made, the commit and
the tracked paths that differed from it, and the day. The page shows an entry's picture only on the
card whose served values, or version and digest, it records; any other card shows its quiet tile.
A card the record holds back (``held``, each with its reason) is not captured.

    uv run python scripts/capture_card_pictures.py --state <run state.json>
    uv run python scripts/capture_card_pictures.py --check

Start the install from the release checkout with a home of its own, so the cards' worlds are made
in an empty workspace (``HOME=<empty directory> python3 scripts/acceptance/launch.py up --worktree
. --personal --tiles``; the cards ask no model). The browser half
(``scripts/capture_card_pictures.mjs``) needs Node and Google Chrome on this machine; nothing is
downloaded. ``--check`` reads no install: it names every entry whose recorded reference differs
from the current recipe or kind, whose card the page now shows quiet, and exits 1 if there is one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "web" / "packages" / "app" / "public" / "card-pictures"
CATALOG = CATALOG_DIR / "card-pictures.v1.json"
PROFILE = "exulanica.card-pictures/v1"
SIZE = (640, 360)
BROWSER_HALF = ROOT / "scripts" / "capture_card_pictures.mjs"


def read_catalog() -> dict:
    if not CATALOG.exists():
        return {"profile": PROFILE, "entries": [], "held": []}
    catalog = json.loads(CATALOG.read_text())
    if catalog.get("profile") != PROFILE:
        raise SystemExit(f"{CATALOG} is not {PROFILE}")
    return catalog


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """A baseline or progressive JPEG's width and height, from its frame header."""
    if data[:2] != b"\xff\xd8":
        return None
    at = 2
    while at + 9 < len(data):
        if data[at] != 0xFF:
            return None
        marker, length = data[at + 1], int.from_bytes(data[at + 2 : at + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[at + 5 : at + 7], "big")
            width = int.from_bytes(data[at + 7 : at + 9], "big")
            return width, height
        at += 2 + length
    return None


def current_reference(card: str, values: dict | None) -> dict:
    """The reference a world made from ``card`` now records: a recipe's, or a shipped kind's.

    A recipe card's town stands on its preset's land, as a deployment that makes worlds on land
    (``EXULANICA_WORLDS_ON_LAND``, on unless stated off) makes it, so the reference names that land
    (``land_sha256`` and ``land_rules``) where the preset has one."""
    family, key = card.split(":", 1)
    if family == "recipe":
        from exulanica.world.composers.city_grammar_town import on_land
        from exulanica.world.world_recipes import preset_land, town_recipe

        recipe, land = town_recipe(key, values), preset_land(key)
        return (recipe if land is None else on_land(recipe, land.land)).reference()
    from exulanica.world.kinds.library import shipped_kinds, town_adapter

    # The town is served among the kinds by its adapter, with the adapter's version and digest.
    for kind in (*shipped_kinds(), town_adapter()):
        if kind.kind == key:
            return {"kind": kind.kind, "version": kind.version, "sha256": kind.sha256}
    raise LookupError(f"no shipped kind {key}")


def made_reference(card: str, values: dict | None, entry: dict) -> dict:
    """``card``'s reference, held to what the world made from it serves (its saved entry): a
    recipe town's land digest, specification and values. A town that did not stand on its land
    (a deployment with worlds on land off, or a land that refused the town) is refused by name."""
    reference = current_reference(card, values)
    if card.startswith("recipe:"):
        ground = entry.get("generated_ground") or {}
        for field in ("land_sha256", "specification", "values"):
            if ground.get(field) != reference.get(field):
                raise SystemExit(
                    f"{card}: the world made serves {field} {ground.get(field)!r}, its card "
                    f"states {reference.get(field)!r}; capture with worlds on land"
                )
    return reference


def check() -> int:
    stale = []
    for entry in read_catalog()["entries"]:
        recorded = entry["reference"]
        try:
            now = current_reference(entry["card"], recorded.get("values"))
        except (LookupError, ValueError) as error:
            stale.append(f"{entry['card']}: {error}")
            continue
        if now != recorded:
            stale.append(
                f"{entry['card']}: recorded {json.dumps(recorded, sort_keys=True)}, now {json.dumps(now, sort_keys=True)}"
            )
    for line in stale:
        print(f"stale: {line}")
    print(f"{len(stale)} stale of {len(read_catalog()['entries'])} entries")
    return 1 if stale else 0


def capture(state_path: Path, port: int) -> int:
    state = json.loads(state_path.read_text())
    token = Path(state["token_file"]).read_text().strip()
    api = f"http://127.0.0.1:{state['ports']['api']}"

    def read(path: str) -> object:
        request = urllib.request.Request(api + path, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=60) as answer:
            return json.load(answer)

    catalog = read_catalog()
    held = {item["card"] for item in catalog["held"]}
    served: dict[str, dict | None] = {}
    for preset in read("/worlds/specification")["presets"]:
        served[f"recipe:{preset['key']}"] = dict(preset["values"])
    for kind in read("/worlds/kinds")["kinds"]:
        if kind["source"] == "shipped" and kind["presets"]:
            served[f"kind:{kind['kind']}"] = None
    cards = [card for card in served if card not in held]

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tree_changes = sorted(line[3:] for line in changed.splitlines())
    with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as profile:
        run = subprocess.run(
            [
                "node",
                str(BROWSER_HALF),
                "--page",
                f"http://127.0.0.1:{state['ports']['vite']}",
                "--port",
                str(port),
                "--profile",
                profile,
                "--out",
                out,
                *cards,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        made = json.loads(run.stdout.strip().splitlines()[-1])["cards"]
        listed = read("/world-entries")
        saved = {
            item["entry_id"]: item
            for item in (listed if isinstance(listed, list) else listed["entries"])
        }
        entries = []
        for item in made:
            data = Path(item["file"]).read_bytes()
            if jpeg_size(data) != SIZE:
                raise SystemExit(f"{item['card']}: the picture is {jpeg_size(data)}, not {SIZE}")
            name = item["card"].replace(":", "-") + ".jpg"
            (CATALOG_DIR / name).parent.mkdir(parents=True, exist_ok=True)
            (CATALOG_DIR / name).write_bytes(data)
            entries.append(
                {
                    "card": item["card"],
                    "reference": made_reference(
                        item["card"], served[item["card"]], saved[item["entry_id"]]
                    ),
                    "picture": name,
                    "picture_sha256": hashlib.sha256(data).hexdigest(),
                    "width": SIZE[0],
                    "height": SIZE[1],
                    "world_id": saved[item["entry_id"]]["world_id"],
                    "entry_id": item["entry_id"],
                    "commit": commit,
                    "tree_changes": tree_changes,
                    "captured_on": dt.datetime.now(dt.UTC).date().isoformat(),
                }
            )
    kept = {entry["picture"] for entry in entries}
    for entry in catalog["entries"]:
        if entry["picture"] not in kept:
            (CATALOG_DIR / entry["picture"]).unlink(missing_ok=True)
    CATALOG.write_text(
        json.dumps({"profile": PROFILE, "entries": entries, "held": catalog["held"]}, indent=2)
        + "\n"
    )
    print(f"captured {len(entries)} cards; held {sorted(held)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state", type=Path, help="the running personal install's run state")
    parser.add_argument(
        "--port", type=int, default=9333, help="the headless Chrome's debugging port"
    )
    parser.add_argument(
        "--check", action="store_true", help="report stale entries; read no install"
    )
    arguments = parser.parse_args(argv)
    if arguments.check:
        return check()
    if arguments.state is None:
        parser.error("--state is required unless --check")
    return capture(arguments.state, arguments.port)


if __name__ == "__main__":
    sys.exit(main())
