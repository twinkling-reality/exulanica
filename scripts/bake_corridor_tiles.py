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
from pathlib import Path

import psycopg
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
from exulanica.grammar.records import record_payload
from exulanica.ingest.stages import STAGES, baked_tile_id
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileRepository
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "web" / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"


def bake(document: Path, container: Path) -> dict[str, object]:
    """The tessellator's own bake, and its statement about what it wrote."""
    result = subprocess.run(
        [str(TSX), str(CLI), "bake", str(document), str(container)],
        capture_output=True,
        text=True,
        cwd=ROOT / "web",
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    url = os.environ.get("EXULANICA_DATABASE_URL")
    data_dir = os.environ.get("EXULANICA_DATA_DIR")
    if not url or not data_dir:
        print("set EXULANICA_DATABASE_URL and EXULANICA_DATA_DIR", file=sys.stderr)
        return 2
    if not TSX.exists():
        print(f"the web toolchain is missing ({TSX}); run pnpm install in web/", file=sys.stderr)
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
            for document in documents:
                tile = document.tile
                key = baked_tile_id(spec, tile)
                document_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.json"
                container_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.{pass_name}.owd"
                data = document_bytes(document)
                document_path.write_bytes(data)
                statement = bake(document_path, container_path)
                container = container_path.read_bytes()
                if hashlib.sha256(container).hexdigest() != statement["container_sha256"]:
                    raise SystemExit("the bake's statement and its bytes disagree")
                outcome = repository.record(
                    baked_tile_id=key,
                    stage_version=spec.version,
                    stage_params_sha256=spec.params_digest,
                    tile=record_payload(tile)["fields"],
                    document=data,
                    container=container,
                    render_batch_sha256=bytes.fromhex(
                        statement["triangle_digests"]["render_batch"]
                    ),
                    nav_envelope_sha256=bytes.fromhex(
                        statement["triangle_digests"]["nav_envelope"]
                    ),
                    receipt={
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
                print(pass_name, tile.tile_x, tile.tile_y, key, len(container), outcome)
    second = [outcome for pass_name, _t, _k, _b, outcome in outcomes if pass_name == "second"]
    if set(second) != {"identical"}:
        print(f"a second bake answered {sorted(set(second))}, not identical", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
