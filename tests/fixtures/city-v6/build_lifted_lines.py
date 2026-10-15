"""Lines a town on its land raised, and the heights the grammar puts along them.

City grammar version 6 lays a town's streets on its land: each segment's crown climbs straight
between its mouths and stands level beyond them, and its centreline, kerb lines and lanes gain a
point wherever the crown bends (``exulanica.grammar.grammars.city.land``). The tessellator reads
those lines piece by piece (``web/packages/loom-tess/src/core/streets.ts``). This file is what holds
the two readings equal to the millimetre: every climbing segment's centreline and kerb lines of one
generated town, each with points along it and the height the grammar's own profile gives there,
the line's level height plus :meth:`StreetProfile.at`.

Run from the repository root to rewrite the file; ``tests/test_city_grammar_v6.py`` holds the
committed file to exactly what this produces, and ``streets-on-land.test.ts`` reads it::

    uv run python tests/fixtures/city-v6/build_lifted_lines.py
"""

from __future__ import annotations

import json
from pathlib import Path

from exulanica.grammar import generate
from exulanica.grammar.grammars.city import city_grammar_with
from exulanica.grammar.grammars.city.descriptor import (
    CITY_MIGRATION_PATHS,
    CITY_V5_SURFACE,
    CITY_V6_SURFACE,
)
from exulanica.grammar.grammars.city.generation.tiles import city_records
from exulanica.grammar.grammars.city.land import StreetProfile, street_profiles
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord, StreetSegmentRecord
from exulanica.grammar.grammars.specified import derived_identity
from exulanica.grammar.landform import land_recipes, read_land_document
from exulanica.grammar.migration import ParameterMigration
from exulanica.world.composers import seed_candidate
from exulanica.world.world_recipes import read_specification, town_recipe

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "web" / "packages" / "loom-tess" / "test" / "fixtures" / "lifted-lines.json"
PROFILE = "exulanica.test-lifted-lines/v1"
#: The town and its land: a small town on the upland recipe, first candidate of a fixed world.
WORLD = "world:generated:lifted-lines"
LAND = "upland"
#: How many climbing segments the file keeps, in segment identity order: enough to hold both ways
#: of climbing and kerb lines of two, three and four points.
SEGMENTS = 4


def _records() -> tuple[object, ...]:
    recipe = town_recipe("small_town")
    spec = read_specification(recipe.specification)
    bindings = (
        ParameterMigration.read(CITY_MIGRATION_PATHS[6])
        .migrate(CITY_V5_SURFACE, CITY_V6_SURFACE, spec.bindings)
        .bindings
    )
    [land] = [r for r in land_recipes() if r.key == LAND]
    for candidate in range(recipe.candidates):
        seed = seed_candidate(recipe, WORLD, candidate)
        try:
            generation = generate(
                city_grammar_with(6, land=read_land_document(dict(land.land))),
                seed=seed,
                subject_identity=derived_identity(seed),
                bindings=bindings,
            )
        except Exception:
            continue
        return tuple(city_records(generation))
    raise RuntimeError("no candidate of the fixture town stands on its land")


def _line(points: tuple[tuple[int, int, int], ...], profile: StreetProfile) -> dict[str, object]:
    """A line and points along it, each at the line's level height plus the profile's climb."""
    axis = profile.axis
    level = points[0][2] - profile.at(points[0][axis])
    first, last = points[0], points[-1]
    span = last[axis] - first[axis]
    places = sorted(
        {point[axis] for point in points}
        | {first[axis] + span * step // 8 for step in range(9)}
        | {profile.low_mm, profile.high_mm, (profile.low_mm + profile.high_mm) // 2 + 1}
    )
    samples = []
    for place in places:
        other = first[1 - axis]
        plan = (place, other) if axis == 0 else (other, place)
        samples.append([plan[0], plan[1], level + profile.at(place)])
    return {"points": [list(point) for point in points], "samples": samples}


def lifted_lines() -> bytes:
    records = _records()
    profiles = street_profiles(records)
    curbs: dict[str, list[CurbEdgeRecord]] = {}
    for curb in (r for r in records if isinstance(r, CurbEdgeRecord)):
        curbs.setdefault(curb.segment_identity, []).append(curb)
    climbing = sorted(
        (r for r in records if isinstance(r, StreetSegmentRecord)),
        key=lambda segment: segment.identity,
    )
    lines = []
    for segment in climbing:
        profile = profiles[segment.identity]
        if profile.low_level_mm == profile.high_level_mm:
            continue
        lines.append(_line(segment.centreline_mm, profile))
        for curb in sorted(curbs[segment.identity], key=lambda curb: curb.side):
            lines.append(_line(curb.kerb_line_mm, profile))
        if len(lines) >= SEGMENTS * 3:
            break
    document = {"profile": PROFILE, "world": WORLD, "land": LAND, "lines": lines}
    return (json.dumps(document, indent=1) + "\n").encode("utf-8")


if __name__ == "__main__":
    FIXTURE.write_bytes(lifted_lines())
    print(f"wrote {FIXTURE.relative_to(ROOT)}")
