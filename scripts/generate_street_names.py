"""Write the street-name catalog from the authored elements and types it composes.

    uv run python scripts/generate_street_names.py

A street name is an element and a street type. Each part states the band of street-hierarchy
ranks it suits, a composition is admissible when the two bands meet, and the composed name suits
exactly the hierarchies in both. So a word authored once reaches every type it can take, and the
vocabulary grows by a word rather than by a name.

**Why this is generated and not written out.** The catalog is the only place a street name may
come from: the record's ``name`` is a key into it. Twenty-eight elements and nine types compose
to more names than anybody would write by hand and keep consistent, and a hand-written list is
where the six local street names came from. ``tests/test_street_name_vocabulary.py`` holds the
committed file to exactly what this writes, and holds the vocabulary to what the declared
parameter space can ask for.

**Nothing here decides what a street may be called.** The words and their bands are in
``assets/catalogs/sources/street-name-parts.json``, which is reviewed data; this file is the rule
that composes them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exulanica.grammar.grammars.city.catalogs import (  # noqa: E402
    CATALOG_DIRECTORY,
    entry_fields,
    load_city_catalogs,
)

PARTS_PATH = CATALOG_DIRECTORY / "sources" / "street-name-parts.json"
CATALOG_PATH = CATALOG_DIRECTORY / "street-name.v1.json"
#: The one sentence every entry carries. It already describes a composition, which is why the
#: twelve entries this catalog began as keep it unchanged.
REASON = (
    "Authored generic street name, a common landscape or trade word and a street type. It names "
    "no real street and comes from no city's street list."
)


def hierarchy_ranks() -> dict[str, int]:
    """Every street hierarchy with its rank, READ FROM ITS OWN CATALOG rather than restated."""
    catalogs = {catalog.catalog_id: catalog for catalog in load_city_catalogs()}
    hierarchies = catalogs["street-hierarchy"]
    keys = hierarchies.keys()
    return {key: int(entry_fields(hierarchies, key)["rank"]) for key in keys}


def compose(parts: dict, ranks: dict[str, int]) -> list[dict]:
    """Every admissible element and type pairing, as catalog entries sorted by key."""
    entries = []
    for element in parts["elements"]:
        for kind in parts["types"]:
            shared = set(element["hierarchies"]) & set(kind["hierarchies"])
            if not shared:
                continue
            entries.append(
                {
                    "key": f"{element['word'].lower()}_{kind['word'].lower()}",
                    "text": f"{element['word']} {kind['word']}",
                    "hierarchies": sorted(shared, key=lambda name: ranks[name]),
                    "reason": REASON,
                    "licence": parts["licence"],
                }
            )
    entries.sort(key=lambda entry: entry["key"])
    return entries


def catalog_document(parts: dict, ranks: dict[str, int]) -> dict:
    return {
        "schema_version": 1,
        "catalog_id": "street-name",
        "catalog_version": 1,
        "entries": compose(parts, ranks),
    }


def written_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def main() -> int:
    parts = json.loads(PARTS_PATH.read_text(encoding="utf-8"))
    ranks = hierarchy_ranks()
    unknown = sorted(
        {
            name
            for part in (*parts["elements"], *parts["types"])
            for name in part["hierarchies"]
            if name not in ranks
        }
    )
    if unknown:
        print(f"{PARTS_PATH.name}: {unknown} are not street hierarchies", file=sys.stderr)
        return 1
    document = catalog_document(parts, ranks)
    CATALOG_PATH.write_bytes(written_bytes(document))
    counts = {
        name: sum(1 for entry in document["entries"] if name in entry["hierarchies"])
        for name in sorted(ranks, key=lambda name: ranks[name])
    }
    print(f"{CATALOG_PATH.relative_to(ROOT)}: {len(document['entries'])} entries")
    for name, count in counts.items():
        print(f"  {name:<14} {count:3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
