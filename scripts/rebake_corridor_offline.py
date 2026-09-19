"""Rebuild the corridor's containers from the repository alone, with no database and no store.

    uv run python scripts/rebake_corridor_offline.py <directory> [x,y ...]

WHY THIS EXISTS. A scored run binds its containers by digest, and the store those containers were
served from is usually a private one belonging to a session that has since ended. When it ends, the
run's own record still states what was measured and NOTHING IN THE TREE CAN PRODUCE THE THING IT
WAS MEASURED ON, so the figures cannot be checked and a reader has to take them. The corridor is
generated from its specification in code, so it can be built again from a commit: this writes the
containers and prints each one's size and SHA-256 READ BACK FROM THE FILE IT WROTE, for comparing
against whatever a record binds.

It is `scripts/bake_corridor_tiles.py` with the recording half removed. That script needs a database
and the owner role because it PUBLISHES a baked tile; generating the documents and baking them needs
neither, and those two steps are the ones that decide the bytes. Nothing here writes to a store,
connects to anything, or reaches the network.

MEASURED 2026-09-19 on main `15e8198c` at tessellator source version 20: the four containers of
tiles (0,0), (1,0), (2,0) and (3,0) come back byte for byte identical to the four that
`docs/evaluation/2026-09-19-corridor-composed-world-private-store.json` binds, whose store was gone.

A digest that does not match is not necessarily this script's fault. The likeliest cause is that
`TESSELLATOR_SOURCE_VERSION` has moved since the record was written, which restates every container
by design; the second likeliest is a change to the city grammar or the generation stages. Both are
findings rather than failures, and both are why the version is printed beside the digests.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.document import document_bytes, validate_city_document
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_LOD,
    CORRIDOR_SEED,
    CORRIDOR_TILES,
)
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    check_piece_lengths,
    city_records,
    generate_city,
    tile_document,
)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "web" / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"
EXPAND = ROOT / "web" / "packages" / "loom-tess" / "src" / "core" / "expand.ts"


def _tessellator_version() -> str:
    """The version the bake stamps into every container, read from the source that stamps it.

    Not from the bake's own report, which does not carry it, and not typed here: a container is
    refused on read unless its `tessellator_version` is this number, so a digest that has moved
    since a record was written is explained by this line or by nothing.
    """
    match = re.search(r"TESSELLATOR_SOURCE_VERSION = (\d+)", EXPAND.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"TESSELLATOR_SOURCE_VERSION is not stated in {EXPAND}")
    return match.group(1)


def _bake(document: Path, container: Path) -> dict[str, object]:
    """The tessellator's own bake, with its refusal carried out whole.

    A refusal states which record it could not draw and why, and that sentence is the diagnosis; an
    exit status alone sends the reader back to run the command again by hand.
    """
    result = subprocess.run(
        [str(TSX), str(CLI), "bake", str(document), str(container)],
        capture_output=True,
        text=True,
        cwd=ROOT / "web",
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "no output"
        raise SystemExit(f"the tessellator refused {document.name}: {message}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _chosen(arguments: list[str]) -> set[tuple[int, int]]:
    if not arguments:
        return set(CORRIDOR_TILES)
    chosen = set()
    for argument in arguments:
        try:
            x, y = (int(part) for part in argument.split(","))
        except ValueError:
            raise SystemExit(f"a tile is two integers as x,y, not {argument!r}") from None
        if (x, y) not in CORRIDOR_TILES:
            raise SystemExit(f"({x}, {y}) is not one of the corridor's tiles {CORRIDOR_TILES}")
        chosen.add((x, y))
    return chosen


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    if not TSX.exists():
        print(f"the web toolchain is missing ({TSX}); run pnpm install in web/", file=sys.stderr)
        return 2
    chosen = _chosen(sys.argv[2:])
    out.mkdir(parents=True, exist_ok=True)

    # Every tile's document is generated and the whole city's closure checked whatever subset is
    # baked, because a tile is only well formed with respect to the city it was cut from.
    catalogs = load_city_catalogs()
    generation = generate_city(
        seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
    )
    records = city_records(generation)
    check_piece_lengths(records)
    documents = []
    for tile_x, tile_y in CORRIDOR_TILES:
        document = tile_document(
            records,
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=CORRIDOR_LOD,
        )
        validate_city_document(document, catalogs=catalogs)
        documents.append(document)
    check_city_reference_closure(documents)

    for document in documents:
        tile = document.tile
        if (tile.tile_x, tile.tile_y) not in chosen:
            continue
        name = f"tile-{tile.tile_x}-{tile.tile_y}"
        document_path = out / f"{name}.json"
        container_path = out / f"{name}.owd"
        document_path.write_bytes(document_bytes(document))
        statement = _bake(document_path, container_path)
        # Read back what was written rather than reporting what the bake said it wrote: the two
        # disagreeing is the one thing this check exists to catch.
        raw = container_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != statement["container_sha256"]:
            raise SystemExit(f"{name}: the bake's statement and the bytes on disk disagree")
        print(f"{name:<12}{len(raw):>12} bytes  {digest}", flush=True)

    print(f"\ntessellator source version {_tessellator_version()}, written to {out}")
    print("Compare these against whatever a record binds. A digest that has moved is a finding:")
    print("read the version above first, because a new tessellator restates every container.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
