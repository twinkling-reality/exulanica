"""Read a baked container's entries through the tessellator's own decoder.

Used by ``scripts/bake_corridor_tiles.py``, by the corridor's drawn-surface evidence script and by
``tests/test_drawn_surfaces_are_dressed.py``. One reader, three callers: a second implementation
that disagreed with this one would disagree silently.

Python has no reader for the ``owd`` container and should not grow one: two readers that disagreed
would be worse than none, and the disagreement would be silent. So this hands a small TypeScript
program to the tessellator's own decoder and document reader and takes back what they say.

The mapping from an entry to its record is the part worth having in one place, and the container
states it itself: ``header.records``, one per entry, in the container's own order. Two attempts to
RECONSTRUCT that order from the document were wrong before anyone thought to look for it, the first
visibly and the second invisibly. The first read the document's owned-then-halo order and said a
surface material record was drawing a carriageway. The second merged and sorted by kind, version
and identity, which grouped the kinds correctly and so produced right counts by kind with the wrong
record inside each one, and it took a census matching dressings to surfaces to notice.
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

const owd = decodeOwd(new Uint8Array(readFileSync(process.argv[2]))) as any;

// THE CONTAINER CARRIES ITS OWN RECORD LIST and every entry indexes THAT. Read it; do not rebuild
// it from the document. Rebuilding merged the document's owned and halo records and sorted them,
// which groups the kinds identically and so gives correct counts BY KIND while assigning the
// wrong identity and the wrong membership inside every kind. Following the container's own
// material pointer showed 2 of 1445 agreeing.
const records = owd.header.records;

process.stdout.write(JSON.stringify(Object.values<any>(owd.projections).map((projection: any) => ({
  name: projection.header.name,
  triangles: projection.header.triangle_count,
  entries: projection.header.entries.map((entry: any) => ({
    kind: records[entry.record]?.kind ?? 'unknown record index',
    identity: records[entry.record]?.identity ?? null,
    membership: records[entry.record]?.membership ?? null,
    state: entry.state,
    needs: entry.needs ?? [],
    surfaces: (entry.surfaces ?? []).map((surface: any) => ({
      role: surface.role,
      orientation: surface.orientation,
      material: surface.material.state,
      materialRecord: surface.material.state === 'record' ? surface.material.record : null,
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
