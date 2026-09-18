"""Bake the corridor city's tiles through the tessellator and record them, twice, offline.

Run from the repository root, against a database of your own:

    EXULANICA_DATABASE_URL=postgresql://localhost:5433/<your scratch db> \
    EXULANICA_DATA_DIR=<a data directory> \
    uv run python scripts/bake_corridor_tiles.py

It generates the corridor city from its specification, cuts it into tiles, validates each with the
grammar's own document check, bakes each through the Node tessellator's CLI (the same bake the
``baked_tile`` stage declares, so the served bytes are the bytes that stage digests), and records
each through migration 0072. Then it bakes every tile a second time and records it again: the
answer must be ``identical`` for every tile, and anything else is the fault 0072 exists to keep.

Name tiles as ``x,y`` arguments to bake only those, for instance ``2,0``. Every tile document is
still generated and the city's reference closure still checked; only the bake and the record are
narrowed. That is for the case where the tessellator refuses one tile and the others are wanted in
the store meanwhile, which is a state to say out loud rather than a reason to record nothing.

EVERY BAKE MEASURES WHAT IT DREW, and keeps the measurement in the row's receipt: how many
surfaces were drawn, how many a material record dresses, which ones none dresses by kind and role,
and what each record that did not draw is waiting for. That is derived from the container itself
rather than from a list of the kinds worth asking about, so it cannot go quiet about a kind nobody
anticipated. Twice in one day a surface was drawn with nothing dressing it and no gate said so,
because each gate was asking about the kinds somebody had thought of. A bake that carries its own
count means nobody has to remember to go and ask.

It never bakes inside a request, never writes to ``assets/``, and connects as whatever role the
URL names; recording a tile needs the owner, because a baked tile is published by this offline
bake and never by a runtime process.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import psycopg
from owd_entries import projections, undressed
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
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.records import record_payload
from exulanica.ingest.stages import STAGES, baked_tile_id
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileRepository
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "web" / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"


def measure(container: Path, document: Path) -> dict[str, object]:
    """What the container drew, and what it left undressed or undrawn, from the container itself.

    Derived rather than listed: every surface the bake states it drew is asked whether a material
    record dresses it, so a kind nobody anticipated appears here the first time something draws it.
    """
    render_batch = next(p for p in projections(container, document) if p["name"] == "render_batch")
    surfaces = [surface for entry in render_batch["entries"] for surface in entry["surfaces"]]
    bare = Counter(f"{surface.kind} {surface.role}" for surface in undressed(render_batch))
    waiting: Counter[str] = Counter()
    for entry in render_batch["entries"]:
        if entry["state"] == "unavailable":
            waiting.update(entry["needs"] or ["(states no need)"])
    return {
        "entries": len(render_batch["entries"]),
        "surfaces": len(surfaces),
        "dressed": len(surfaces) - sum(bare.values()),
        "undressed": dict(sorted(bare.items())),
        "waiting": dict(sorted(waiting.items())),
        "triangles": render_batch["triangles"],
    }


def bake(document: Path, container: Path) -> dict[str, object]:
    """The tessellator's own bake, and its statement about what it wrote.

    A refusal is raised WITH what the tessellator said. It states which record it could not draw
    and why, and that sentence is the whole diagnosis; a CalledProcessError that carries only an
    exit status sends the reader back to run the command again by hand to find out what it already
    knew. On 2026-09-18 that cost a rebake and a puzzled half hour.
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


def _chosen_tiles(arguments: list[str]) -> set[tuple[int, int]] | None:
    """The tiles to bake: every corridor tile, or the ones named as ``x,y`` arguments.

    Every tile document is still generated and the whole city's reference closure still checked,
    because a tile is only well formed with respect to the city it was cut from. Naming a subset
    says which of them to bake and record, and is for the case where one tile is refused by the
    tessellator and the rest are wanted meanwhile. A refusal is not a reason to record nothing, and
    it is not a reason to pretend the refused tile is fine either: it is named on the way out.
    """
    if not arguments:
        return set(CORRIDOR_TILES)
    chosen = set()
    for argument in arguments:
        try:
            x, y = (int(part) for part in argument.split(","))
        except ValueError:
            print(f"a tile is two integers as x,y, not {argument!r}", file=sys.stderr)
            return None
        if (x, y) not in CORRIDOR_TILES:
            print(
                f"({x}, {y}) is not one of the corridor's tiles {CORRIDOR_TILES}", file=sys.stderr
            )
            return None
        chosen.add((x, y))
    return chosen


def main() -> int:
    url = os.environ.get("EXULANICA_DATABASE_URL")
    data_dir = os.environ.get("EXULANICA_DATA_DIR")
    if not url or not data_dir:
        print("set EXULANICA_DATABASE_URL and EXULANICA_DATA_DIR", file=sys.stderr)
        return 2
    if not TSX.exists():
        print(f"the web toolchain is missing ({TSX}); run pnpm install in web/", file=sys.stderr)
        return 2
    chosen = _chosen_tiles(sys.argv[1:])
    if chosen is None:
        return 2
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

    spec = STAGES["baked_tile"]
    with (
        tempfile.TemporaryDirectory() as work,
        psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection,
    ):
        repository = BakedTileRepository(connection=connection, store=tile_store(Path(data_dir)))
        outcomes: list[tuple[str, str, str, int, str]] = []
        for pass_name in ("first", "second"):
            for document in [d for d in documents if (d.tile.tile_x, d.tile.tile_y) in chosen]:
                tile = document.tile
                key = baked_tile_id(spec, tile)
                document_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.json"
                container_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.{pass_name}.owd"
                data = document_bytes(document)
                document_path.write_bytes(data)
                statement = bake(document_path, container_path)
                container = container_path.read_bytes()
                drawn = measure(container_path, document_path)
                if hashlib.sha256(container).hexdigest() != statement["container_sha256"]:
                    raise SystemExit("the bake's statement and its bytes disagree")
                outcome = repository.record(
                    baked_tile_id=key,
                    stage_version=spec.version,
                    stage_params_sha256=spec.params_digest,
                    tile={
                        # The digest is computed from the record, not carried in it: the record
                        # states the inputs and `tile_inputs_digest` is the one function over them.
                        "tile_inputs_digest": tile_inputs_digest(tile),
                        **record_payload(tile)["fields"],
                    },
                    document=data,
                    container=container,
                    render_batch_sha256=bytes.fromhex(
                        statement["triangle_digests"]["render_batch"]
                    ),
                    nav_envelope_sha256=bytes.fromhex(
                        statement["triangle_digests"]["nav_envelope"]
                    ),
                    receipt={
                        "drawn": drawn,
                        "stage": spec.key,
                        "stage_version": spec.version,
                        "container": spec.params["container"],
                        "tessellator": spec.params["tessellator"],
                        "triangle_digest": spec.params["triangle_digest"],
                        "tile_document": spec.params["tile_document"],
                        "bake": statement,
                    },
                )
                outcomes.append(
                    (
                        pass_name,
                        f"({tile.tile_x}, {tile.tile_y})",
                        str(key),
                        len(container),
                        outcome,
                    )
                )
                print(
                    pass_name,
                    tile.tile_x,
                    tile.tile_y,
                    key,
                    len(container),
                    outcome,
                    f"drawn {drawn['surfaces']} surfaces, {drawn['dressed']} dressed,",
                    f"undressed {drawn['undressed'] or 'none'},",
                    f"waiting {drawn['waiting'] or 'nothing'}",
                )
    second = [outcome for pass_name, _t, _k, _b, outcome in outcomes if pass_name == "second"]
    if set(second) != {"identical"}:
        print(f"a second bake answered {sorted(set(second))}, not identical", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
