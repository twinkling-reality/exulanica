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
        3_693,
        "alternate world versions and the objects, environments, point maps and things "
        "authored in them, and the changes made to a site world's made parts, their "
        "buildings' storeys among them",
    ),
    "web/packages/app/src/composition/environment-selection.ts": (
        3_335,
        "the people, picking and society views of a mounted world, in one closure",
    ),
    "web/packages/atlas-react/src/playcanvas/atlas-binding.ts": (
        3_282,
        "the PlayCanvas binding: creation, residency, camera, inspection, map mode, "
        "the frame and the segment overlay",
    ),
    "exulanica/world/society_planner.py": (
        2_664,
        "the v2 society's input, graph, spots, talk and minute",
    ),
    "exulanica/api/society_runtime.py": (
        2_421,
        "society composition for districts and for authored worlds, and the site reads, "
        "with the version's changes to a site's made parts",
    ),
    "exulanica/world/society_things.py": (2_291, "the society of things, exulanica-society/v7"),
    "exulanica/evaluation/visual_gate.py": (
        2_257,
        "a visual gate record built from measured inputs",
    ),
    "exulanica/world/repository.py": (2_225, "protected world topology and appearance versions"),
    "exulanica/graph/reconstruction_scenes.py": (
        2_185,
        "validated multi-photograph reconstruction scenes for the graph snapshot",
    ),
    "exulanica/reconstruction/standpoint.py": (
        2_163,
        "photographs from one standpoint, joined by the rotation between them",
    ),
    "web/packages/app/src/main.ts": (2_012, "the legacy app shell's boot and world mount"),
    "exulanica/orchestration/judge_seed.py": (
        2_021,
        "a workspace sealed into a verified archive; its refusals include a workspace that keeps "
        "web pictures (0215)",
    ),
    "exulanica/grammar/grammars/city/document.py": (
        1_986,
        "a city tile document and the checks that span its records",
    ),
    "exulanica/world/saved_entries.py": (1_932, "reopening a personal world at a saved state"),
    "exulanica/traffic/simulation.py": (1_915, "the traffic simulation's pure step"),
    "exulanica/world/society_authored_ground.py": (
        1_914,
        "the society projection of a saved world that has no district",
    ),
    "web/packages/app/src/composition/objects.ts": (
        1_888,
        "the authored objects surface: place, move, run, remove, undo",
    ),
    "exulanica/world/society_repository.py": (1_789, "deterministic societies and their inputs"),
    "exulanica/store/object.py": (1_764, "S3-compatible content-addressed storage"),
    "exulanica/world/project_context.py": (
        1_721,
        "what a person keeps about their work in a world",
    ),
    "exulanica/selection/society_question.py": (
        1_693,
        "the Companion's answers about a world's simulated people",
    ),
    "exulanica/world/static_glb.py": (
        1_624,
        "a workspace's static glTF binary, admitted and prepared",
    ),
    "exulanica/ingest/scene_segments.py": (
        1_561,
        "segments lifted into the scene they reconstructed",
    ),
    "exulanica/world/society_decision_contract.py": (
        1_537,
        "the contract a model answers under when it runs a person",
    ),
    "exulanica/selection/kind_brief.py": (1_529, "a kind of world as a model drafts it"),
    "exulanica/world/society_catalogs.py": (1_509, "the living society routine model as data"),
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
