"""Bake the tiles of a city SOMEBODY ASKED FOR, from a specification in a file, twice, offline.

The counterpart to ``bake_corridor_tiles.py``, and the difference is the whole point of it. That
script bakes ONE world, whose seed, identity and eleven bound values are Python constants in
``exulanica/grammar/grammars/city/generation/corridor.py``. This one bakes whatever world a
specification names, and a specification is DATA:

    EXULANICA_DATABASE_URL=postgresql://localhost:5433/<your scratch db> \
    EXULANICA_DATA_DIR=<a data directory> \
    uv run python scripts/bake_a_specified_world.py <a specification>.json [x,y ...]

The file is the body ``POST /world-generation/worlds`` accepts, verbatim, so a world the route
answered can be baked by handing this script the request that made it.

**Why it imports the route's own seed derivation.** The seed and the identity come from
:func:`exulanica.api.routes.world_generation.derived_seed` and its neighbour, not from a copy of the
rule. If this script derived them itself, the route would state one seed and the bake would record
another, and the two would agree only for as long as nobody edited either. The dependency direction
is the honest one: the route is the door that says what a specification means, and a baker bakes
what the door specified.

**It bakes twice and both answers must be ``identical``**, which is migration 0072's determinism
check and the reason the second pass exists. Nothing here writes to ``assets/``, nothing bakes
inside a request, and it connects as whatever role the URL names; recording a tile needs the owner.

**It reports the world, not just the tiles**, because the point of asking for a world is to find out
what you got: the derived seed, the admitted identity, every tile, and for each tile what the
tessellator drew, what a material record dresses and what is waiting on something.
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
from exulanica.api.routes.world_generation import (
    GENERATED_LOD,
    WORLD_COVERAGE,
    derived_identity,
    derived_seed,
    specification_payload,
)
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.document import document_bytes, validate_city_document
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    check_piece_lengths,
    city_records,
    generate_city,
    tile_document,
)
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.parameters import CascadeBinding
from exulanica.grammar.records import record_payload
from exulanica.ingest.stages import STAGES, baked_tile_id
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileRepository
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "web" / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"


def bake(document: Path, container: Path) -> dict[str, object]:
    """The tessellator's own bake, and its statement about what it wrote.

    A refusal is raised WITH what the tessellator said, because that sentence names which record it
    could not draw and why, and an exit status alone sends the reader back to run the command by
    hand to learn what it already knew.

    Its own three lines rather than an import from ``bake_corridor_tiles``, which would pull
    ``CORRIDOR_BINDINGS`` in through the module graph. A script for baking any specified world must
    not depend on the one world that used to be the only one.
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


def measure(container: Path, document: Path) -> dict[str, object]:
    """What the container drew, and what it left undressed or undrawn, from the container itself.

    Derived rather than listed, so a kind nobody anticipated appears here the first time something
    draws it instead of being quietly absent from a list of the kinds worth asking about.
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


def _read_specification(path: Path) -> tuple[str, int, tuple[CascadeBinding, ...]]:
    """The specification as data, refused rather than repaired if it is not the route's shape."""
    document = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(document) - {"grammar_id", "grammar_version", "bindings"}
    if unknown:
        raise SystemExit(f"{path.name} has keys the route does not accept: {sorted(unknown)}")
    bindings = tuple(
        CascadeBinding.of(entry["level"], entry["values"]) for entry in document["bindings"]
    )
    return document["grammar_id"], int(document["grammar_version"]), bindings


def _chosen(arguments: list[str], tiles: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """The tiles to bake and record: all of them, or the ones named as ``x,y``.

    Every tile document is still generated and the whole city's reference closure still checked,
    because a tile is only well formed with respect to the city it was cut from.
    """
    if not arguments:
        return set(tiles)
    chosen = set()
    for argument in arguments:
        try:
            x, y = (int(part) for part in argument.split(","))
        except ValueError:
            raise SystemExit(f"a tile is two integers as x,y, not {argument!r}") from None
        if (x, y) not in tiles:
            raise SystemExit(f"({x}, {y}) is not a tile of this world: {tiles}")
        chosen.add((x, y))
    return chosen


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    url = os.environ.get("EXULANICA_DATABASE_URL")
    data_dir = os.environ.get("EXULANICA_DATA_DIR")
    if not url or not data_dir:
        print("set EXULANICA_DATABASE_URL and EXULANICA_DATA_DIR", file=sys.stderr)
        return 2
    if not TSX.exists():
        print(f"the web toolchain is missing ({TSX}); run pnpm install in web/", file=sys.stderr)
        return 2

    grammar_id, grammar_version, bindings = _read_specification(Path(sys.argv[1]))
    coverage = WORLD_COVERAGE.get(grammar_id)
    if coverage is None:
        print(f"{grammar_id} declares no world coverage rule, so its tiles cannot be counted",
              file=sys.stderr)
        return 2
    payload = specification_payload(grammar_id, grammar_version, bindings)
    seed = derived_seed(payload)
    identity = derived_identity(seed)

    catalogs = load_city_catalogs()
    generation = generate_city(seed=seed, subject_identity=identity, bindings=bindings)
    records = city_records(generation)
    check_piece_lengths(records)
    values = dict(generation.receipt.parameters.values)
    tiles = coverage.tiles(values)
    chosen = _chosen(sys.argv[2:], tiles)

    print(f"specification  {Path(sys.argv[1]).name}")
    print(f"grammar        {grammar_id} v{grammar_version}")
    print(f"world_seed     {seed}")
    print(f"world_identity {identity}")
    print(f"output_digest  {generation.receipt.output_digest}")
    print(f"records        {len(records)}")
    print(f"tiles          {len(tiles)}: {tiles}")
    print(f"baking         {len(chosen)} of them")

    documents = []
    for tile_x, tile_y in tiles:
        document = tile_document(
            records,
            seed=seed,
            subject_identity=identity,
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=GENERATED_LOD,
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
        outcomes: list[tuple[str, str]] = []
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
                        # Computed from the record rather than carried in it: the record states the
                        # inputs and `tile_inputs_digest` is the one function over them.
                        "tile_inputs_digest": tile_inputs_digest(tile),
                        **record_payload(tile)["fields"],
                    },
                    document=data,
                    container=container,
                    render_batch_sha256=bytes.fromhex(statement["triangle_digests"]["render_batch"]),
                    nav_envelope_sha256=bytes.fromhex(statement["triangle_digests"]["nav_envelope"]),
                    receipt={
                        "drawn": drawn,
                        "stage": spec.key,
                        "stage_version": spec.version,
                        "container": spec.params["container"],
                        "tessellator": spec.params["tessellator"],
                        "triangle_digest": spec.params["triangle_digest"],
                        "tile_document": spec.params["tile_document"],
                        "bake": statement,
                        # What this world was asked for, so a row can be traced back to a request.
                        # The bindings and not only the seed, because the seed is a digest over
                        # them and a digest cannot be read back into a specification.
                        "specification": payload,
                    },
                )
                outcomes.append((pass_name, outcome))
                print(
                    pass_name,
                    tile.tile_x,
                    tile.tile_y,
                    key,
                    len(container),
                    outcome,
                    f"drawn {drawn['surfaces']} surfaces, {drawn['dressed']} dressed,",
                    f"triangles {drawn['triangles']},",
                    f"undressed {drawn['undressed'] or 'none'},",
                    f"waiting {drawn['waiting'] or 'nothing'}",
                )
    second = [outcome for pass_name, outcome in outcomes if pass_name == "second"]
    if set(second) != {"identical"}:
        print(f"a second bake answered {sorted(set(second))}, not identical", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
