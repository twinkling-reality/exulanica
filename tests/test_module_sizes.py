"""The largest modules may not grow, and no other module may pass the line for a listing.

A module this long holds several responsibilities, and every change that adds to it makes the next
split dearer. So each product module of more than :data:`LISTED_ABOVE` lines is listed with the most
lines it may have and what it holds. A change that needs one to grow raises its number in the same
edit, with the reason in the commit; a split lowers it. A listed module that falls more than
:data:`SLACK` lines below its number lowers the number too, so the room a split freed is not used
again without anyone deciding it. A generated file is listed apart, with the command that writes it,
and is never limited: its size is its generator's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The line count above which a product module is listed here.
LISTED_ABOVE = 1_500
#: How far below its number a listed module may fall before its number is lowered.
SLACK = 100
#: Where product modules live.
SOURCES = (
    "exulanica",
    "exulanica_pieces",
    "tools/previews",
    *sorted(str(path.relative_to(ROOT)) for path in (ROOT / "web" / "packages").glob("*/src")),
)
SUFFIXES = (".py", ".ts", ".tsx", ".mjs")

#: Each listed module, the most lines it may have, and what it holds.
LIMITS: dict[str, tuple[int, str]] = {
    "exulanica/world/object_repository.py": (
        3_717,
        "alternate world versions and the objects, environments, point maps and things "
        "authored in them, and the changes made to a site world's made parts, their "
        "buildings' storeys among them",
    ),
    "web/packages/app/src/composition/environment-selection.ts": (
        3_361,
        "the people, picking and society views of a mounted world, in one closure, with the "
        "world's clock and population, the seats its placed things give and the people spacing, "
        "walkers' included, a host page's names for its beings, and a pick that stops at the one "
        "chosen",
    ),
    "web/packages/atlas-react/src/playcanvas/atlas-binding.ts": (
        3_282,
        "the PlayCanvas binding: creation, residency, camera, inspection, map mode, "
        "the frame and the segment overlay",
    ),
    "exulanica/world/society_planner.py": (
        2_684,
        "the v2 society's input, graph, spots, talk and minute, and where residents start",
    ),
    "exulanica/api/society_runtime.py": (
        2_433,
        "society composition for districts and for authored worlds, and the site reads, "
        "with the version's changes to a site's made parts, and a first input's day start from "
        "the world's setting and its world's title",
    ),
    "exulanica/world/society_things.py": (
        2_295,
        "the society of things, exulanica-society/v7, and its outdoors take-in (purposeful/v4)",
    ),
    "exulanica/reconstruction/standpoint.py": (
        2_163,
        "photographs from one standpoint, joined by the rotation between them",
    ),
    "web/packages/app/src/main.ts": (
        2_045,
        "the legacy app shell's boot and world mount, the picture of a saved world it keeps "
        "on the server once a frame holds the drawn world, a site redrawn after a part changes, "
        "and the traffic read again after a thing's edit and held while its world does not run",
    ),
    "exulanica/world/saved_entries.py": (
        1_966,
        "reopening a personal world at a saved state, making a town on its land, and the title a "
        "society made now records",
    ),
    "exulanica/world/society_decision_contract.py": (
        1_637,
        "the contract a model answers under when it runs a person, with the request's own contract "
        "threaded through its context builders, the minute told as the world's clock, the "
        "town's premises told by name, each line said told with whether it was answered and "
        "where the being lives",
    ),
    "web/packages/atlas-react/src/playcanvas/society/crowd.ts": (
        1_622,
        "a society's people as drawn near and far: where each stands, faces and sits (two who "
        "spoke facing each other, a placed being walking in from where it was put down, no two "
        "standing or walking inside each other), whether one is drawn in full yet, and which one "
        "a ray picks (the one it passes through the middle of over one it grazes, stopping at "
        "the one chosen)",
    ),
    "exulanica/selection/kind_brief.py": (
        1_532,
        "a kind of world as a model drafts it, its look pattern written so a provider's grammar "
        "compiler accepts it",
    ),
    "tools/previews/world-workspace/contextual-world.ts": (
        1_526,
        "the world view's host: its corners, people, speech, building (which lets go of a chosen "
        "person as it starts), History and chosen-character hooks; the record pages' states are "
        "record-host.ts's",
    ),
    "exulanica/api/routes/world_kinds.py": (
        1_537,
        "the world kinds library, its drafts and the worlds made of it, and a site world's "
        "drawing, land, graded top and landscape reads",
    ),
    "exulanica/world/society_catalogs.py": (
        1_539,
        "the living society routine model as data, and the day-start and told place catalogs' "
        "schemas",
    ),
}

#: What writes the generated files below.
API_REFERENCE = "node web/packages/landing/scripts/sync-api-reference.mjs"
GRAMMAR_TABLES = "web/packages/loom-tess/test/write-grammar-table.ts"
#: Generated files, never limited, with what writes each.
GENERATED: dict[str, str] = {
    "web/packages/landing/src/content/api-inventory.ts": API_REFERENCE,
    "web/packages/landing/src/content/api-schema.ts": API_REFERENCE,
    "web/packages/loom-tess/src/core/city-v2.ts": GRAMMAR_TABLES,
    "web/packages/loom-tess/src/core/city-v3.ts": GRAMMAR_TABLES,
    "web/packages/loom-tess/src/core/city-v4.ts": GRAMMAR_TABLES,
    "web/packages/loom-tess/src/core/city-v5.ts": GRAMMAR_TABLES,
    "web/packages/loom-tess/src/core/city-v6.ts": GRAMMAR_TABLES,
}


def lines(path: str) -> int:
    return (ROOT / path).read_text(encoding="utf-8").count("\n")


def modules() -> dict[str, int]:
    """Every product module and its line count."""
    found: dict[str, int] = {}
    for source in SOURCES:
        for path in (ROOT / source).rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if {"node_modules", "dist", "__pycache__"} & set(path.parts):
                continue
            relative = str(path.relative_to(ROOT))
            found[relative] = lines(relative)
    return found


@pytest.mark.parametrize("path", sorted(LIMITS))
def test_no_listed_module_grows_past_its_number(path):
    most, _holds = LIMITS[path]
    assert lines(path) <= most, (
        f"{path} has {lines(path)} lines, more than its {most}: split it, or raise its number in "
        "this file in the same patch as the growth, with the reason, so the growth is reviewed"
    )


@pytest.mark.parametrize("path", sorted(LIMITS))
def test_a_listed_module_that_shrank_lowers_its_number(path):
    most, _holds = LIMITS[path]
    assert lines(path) >= most - SLACK, (
        f"{path} has {lines(path)} lines, more than {SLACK} below its {most}: lower its number to "
        f"{lines(path)}"
    )


def test_no_other_module_passes_the_line():
    unlisted = sorted(
        f"{path} ({count} lines)"
        for path, count in modules().items()
        if count > LISTED_ABOVE and path not in LIMITS and path not in GENERATED
    )
    assert not unlisted, (
        f"modules over {LISTED_ABOVE} lines that are not listed: split them, or list each with "
        f"its number and what it holds: {unlisted}"
    )


def test_every_entry_names_a_module_and_says_what_it_holds():
    found = modules()
    for path, (most, holds) in LIMITS.items():
        assert path in found, f"{path} is listed and is no product module"
        assert most > LISTED_ABOVE, f"{path} is at or under {LISTED_ABOVE}: remove it from the list"
        assert holds.strip() and "\n" not in holds, path
    for path, command in GENERATED.items():
        assert path in found and command.strip(), path
