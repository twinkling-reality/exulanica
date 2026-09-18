"""Read a baked container's entries through the tessellator's own decoder.

Python has no reader for the ``owd`` container and should not grow one: two readers that disagreed
would be worse than none, and the disagreement would be silent. So this hands a small TypeScript
program to the tessellator's own decoder and document reader and takes back what they say.

The mapping from an entry to its record is the part worth having in one place. A container states
one entry per record in ONE MERGED LIST SORTED BY KIND, while a document states owned records and
then halo records. Reading the container's order as the document's gives a confident wrong answer:
on 2026-09-18 it said a surface material record was drawing a carriageway.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"

_READER = """
import { readFileSync } from 'node:fs';
import { decodeOwd } from '<ROOT>/web/packages/loom-tess/src/core/owd.js';
import { readTileDocument } from '<ROOT>/web/packages/loom-tess/src/core/document.js';

const owd = decodeOwd(new Uint8Array(readFileSync(process.argv[2]))) as any;
const document = readTileDocument(new Uint8Array(readFileSync(process.argv[3]))) as any;
const records = document.grammars
  .flatMap((grammar: any) => [...grammar.owned, ...grammar.halo])
  .sort((a: any, b: any) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.version - b.version));

process.stdout.write(JSON.stringify(Object.values<any>(owd.projections).map((projection: any) => ({
  name: projection.header.name,
  triangles: projection.header.triangle_count,
  entries: projection.header.entries.map((entry: any) => ({
    kind: records[entry.record]?.kind ?? 'unknown record index',
    identity: records[entry.record]?.fields?.identity ?? null,
    state: entry.state,
    needs: entry.needs ?? [],
    surfaces: (entry.surfaces ?? []).map((surface: any) => ({
      role: surface.role,
      orientation: surface.orientation,
      material: surface.material.state,
    })),
  })),
}))));
"""


@dataclass(frozen=True, slots=True)
class Surface:
    kind: str
    identity: str | None
    role: str
    orientation: str
    material: str


def projections(container: Path, document: Path) -> list[dict]:
    """Every projection of ``container``, with each entry named by the record it is for."""
    with tempfile.TemporaryDirectory() as work:
        program = Path(work) / "read-entries.ts"
        program.write_text(_READER.replace("<ROOT>", str(ROOT)), encoding="utf-8")
        result = subprocess.run(
            [str(TSX), str(program), str(container.resolve()), str(document.resolve())],
            capture_output=True,
            text=True,
            cwd=ROOT / "web",
        )
    if result.returncode != 0:
        raise AssertionError(
            f"reading {container.name} failed: {(result.stderr or result.stdout).strip()}"
        )
    return json.loads(result.stdout)


def undressed(projection: dict) -> list[Surface]:
    """Every surface the projection DRAWS for which the tile states no material record.

    Derived from what was drawn, never from a list of the kinds worth checking: a gate that
    enumerates what to look at is silent about the class nobody thought of, which is how a facade's
    ground band went unnoticed until something drew it.
    """
    return [
        Surface(
            entry["kind"],
            entry["identity"],
            surface["role"],
            surface["orientation"],
            surface["material"],
        )
        for entry in projection["entries"]
        if entry["state"] == "drawn"
        for surface in entry["surfaces"]
        if surface["material"] != "record"
    ]
