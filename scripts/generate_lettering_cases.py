"""Generate the shared lettering cases, and the small test catalog they lean on.

    uv run python scripts/generate_lettering_cases.py           # rewrite both files
    uv run python scripts/generate_lettering_cases.py --check    # exit 1 if either is out of date

Two readers run these cases: `exulanica.lettering` (tests/test_lettering_cases.py) and
`@exulanica/loom-lettering` (web/packages/loom-lettering/test/cases.test.ts). Every case is
accepted by both or refused by both for the same one reason, and every refused case has exactly one
defect, so the order a reader checks in cannot change the reason it gives.

The expected values come from the Python rule, which is the reference; the TypeScript side has to
agree. Accepted layouts carry their placements, so a disagreement names the letter that moved.

`cases/boxes.v1.json` is a catalog of rectangles, written here rather than made from a font: it
holds the cases a real typeface cannot show, such as a pair of letters that touch only because
their millimetre rounding brings them together, and a kerning pair that overlaps outright.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exulanica.canonical import canonical_json
from exulanica.lettering import (
    CHARACTER_SET,
    GLYPH_CATALOG_PROFILE,
    GlyphCatalog,
    LetteringRefused,
    glyph_parts_mm,
    layout_sign,
    read_glyph_catalog,
)
from exulanica.lettering.geometry import parts_problem

ROOT = Path(__file__).resolve().parents[1]
CASE_DIRECTORY = ROOT / "web" / "packages" / "loom-lettering" / "test"
CASES = CASE_DIRECTORY / "lettering-cases.json"
BOXES = CASE_DIRECTORY / "cases" / "boxes.v1.json"
#: Where the committed catalogs sit, relative to the case file.
COMMITTED = "../../../../assets/catalogs/lettering"
#: The committed catalogs, read from the directory rather than listed here. A list would be a second
#: statement of what `assets/catalogs/lettering` holds, and the two would part company silently: a
#: fifth catalog would simply get no cases, which is not an error or a skip but an absence.
#: `tests/test_lettering_cases.py` holds the generated file to this directory in both directions.
def committed_catalogs() -> dict[str, str]:
    """Catalog id to file name, for every catalog in the committed directory."""
    directory = ROOT / "assets" / "catalogs" / "lettering"
    return {path.name.split(".v")[0]: path.name for path in sorted(directory.glob("*.json"))}

BOX_CAP_HEIGHT = 1000
BOX_MINIMUM_MM = 100
BOX_MAXIMUM_MM = 1200


def _rectangle(x0: int, y0: int, x1: int, y1: int) -> list[int]:
    """A counter-clockwise rectangle, starting at its lowest then leftmost corner."""
    return [x0, y0, x1, y0, x1, y1, x0, y1]


def _box_glyphs() -> list[dict[str, Any]]:
    """Every character as rectangles: the default is a 500 by 1000 slab in a 600 advance."""
    #: character: (advance, parts as (outer, holes))
    special: dict[str, tuple[int, list[tuple[list[int], list[list[int]]]]]] = {
        # The x-height and the descender the metrics must agree with.
        "x": (600, [(_rectangle(50, 0, 550, 500), [])]),
        "p": (600, [(_rectangle(50, -200, 550, 500), [])]),
        # The tallest glyph, so the ascender is not the cap height.
        "l": (300, [(_rectangle(50, 0, 250, 1100), [])]),
        # A counter, so a hole is exercised.
        "O": (700, [(_rectangle(50, 0, 650, 1000), [_rectangle(200, 200, 500, 800)])]),
        # Two parts, as i and j have.
        "i": (300, [(_rectangle(50, 0, 250, 500), []), (_rectangle(50, 600, 250, 800), [])]),
        ".": (200, [(_rectangle(50, 0, 150, 100), [])]),
        # 105 wide in a 106 advance: a tenth of a millimetre apart at a 100 mm cap height, which
        # the millimetre rounding closes. Nothing in a real face is spaced that tightly.
        "I": (106, [(_rectangle(0, 0, 105, 1000), [])]),
    }
    glyphs = []
    for character in CHARACTER_SET:
        if character == " ":
            glyphs.append({"character": character, "advance": 400, "parts": []})
            continue
        advance, parts = special.get(character, (600, [(_rectangle(50, 0, 550, 1000), [])]))
        glyphs.append(
            {
                "character": character,
                "advance": advance,
                "parts": [{"outer": outer, "holes": holes} for outer, holes in parts],
            }
        )
    return glyphs


def _box_catalog() -> bytes:
    glyphs = _box_glyphs()
    ys = [
        value
        for glyph in glyphs
        for part in glyph["parts"]
        for ring in [part["outer"], *part["holes"]]
        for value in ring[1::2]
    ]
    by_character = {glyph["character"]: glyph for glyph in glyphs}

    def tops(character: str) -> int:
        glyph = by_character[character]
        return max(
            value
            for part in glyph["parts"]
            for ring in [part["outer"], *part["holes"]]
            for value in ring[1::2]
        )

    document: dict[str, Any] = {
        "profile": GLYPH_CATALOG_PROFILE,
        "catalog_id": "boxes",
        "catalog_version": 1,
        "source": {
            "repository": "exulanica/exulanica",
            "commit": "0" * 40,
            "path": "scripts/generate_lettering_cases.py",
            "url": "https://example.invalid/not-a-font",
            "file": "scripts/generate_lettering_cases.py",
            "sha256": "0" * 64,
            "byte_size": 1,
            "family": "Test Boxes",
            "style": "Regular",
            "font_version": "Version 1.000",
            "licence": {
                "spdx": "OFL-1.1",
                "copyright": [
                    "Rectangles drawn by scripts/generate_lettering_cases.py, from no font at all.",
                    "The licence field carries the value a real catalog carries; nothing here is",
                    "font software.",
                ],
                "file": "assets/fonts/barlow/OFL.txt",
                "url": "https://example.invalid/not-a-font",
                "sha256": "0" * 64,
            },
        },
        "tool": {
            "name": "scripts/generate_lettering_cases.py",
            "rules_version": 1,
            "fonttools": "none: no font was read",
        },
        "units_per_em": 1000,
        "metrics": {
            "cap_height": tops("H"),
            "x_height": tops("x"),
            "ascender": max(ys),
            "descender": min(ys),
        },
        "conversion": {
            "flattening_tolerance_cap_height_divisor": BOX_MAXIMUM_MM,
            "minimum_edge_cap_height_divisor": BOX_MINIMUM_MM,
            "minimum_edge": -(-BOX_CAP_HEIGHT // BOX_MINIMUM_MM),
            "vertices_removed": 0,
            "largest_shift": 0,
        },
        "cap_height_mm": {"minimum": BOX_MINIMUM_MM, "maximum": BOX_MAXIMUM_MM},
        "scan": {"from_mm": BOX_MAXIMUM_MM, "largest_failing_mm": 0},
        "glyphs": glyphs,
        "kerning": [
            # Enough negative kerning to overlap outright, at every size.
            ["A", "V", -200],
            # Positive kerning, which the placements must show.
            ["L", "T", 100],
        ],
    }
    largest, failure = _scan(read_glyph_catalog(canonical_json(document)))
    document["scan"] = {"from_mm": BOX_MAXIMUM_MM, "largest_failing_mm": largest}
    if failure is not None:
        document["scan"]["failure"] = failure
    raw = canonical_json(document)
    read_glyph_catalog(raw)
    return raw


def _scan(catalog: GlyphCatalog) -> tuple[int, str | None]:
    """The same scan the tool records: the largest cap height at which a glyph fails, top down."""
    for size in range(catalog.maximum_cap_height_mm, 0, -1):
        for character in CHARACTER_SET:
            problem = parts_problem(glyph_parts_mm(catalog, character, size))
            if problem:
                return size, f"{character!r} {problem}"
    return 0, None


def _catalogs() -> dict[str, str]:
    paths = {name: f"{COMMITTED}/{file}" for name, file in committed_catalogs().items()}
    paths["boxes"] = "cases/boxes.v1.json"
    return paths


def _read(path: str) -> bytes:
    return (CASE_DIRECTORY / path).read_bytes()


def _apply(document: Any, changes: list[dict[str, Any]]) -> Any:
    changed = copy.deepcopy(document)
    for change in changes:
        parent = changed
        for step in change["path"][:-1]:
            parent = parent[step]
        last = change["path"][-1]
        if change.get("remove"):
            del parent[last]
        else:
            parent[last] = copy.deepcopy(change["value"])
    return changed


def catalog_bytes(case: dict[str, Any], catalogs: dict[str, str]) -> bytes:
    """The bytes a catalog case hands its reader: changes, then edits to the canonical text."""
    raw = _read(catalogs[case["catalog"]])
    if case.get("changes"):
        raw = canonical_json(_apply(json.loads(raw.decode("utf-8")), case["changes"]))
    text = raw.decode("utf-8")
    for old, new in case.get("text_edits", []):
        if text.count(old) != 1:
            raise AssertionError(f"{case['name']}: {old!r} occurs {text.count(old)} times")
        text = text.replace(old, new)
    return text.encode("utf-8") + case.get("append", "").encode("utf-8")


def _catalog_cases() -> list[dict[str, Any]]:
    """Every catalog refusal reason, and every committed catalog accepted."""
    cases: list[dict[str, Any]] = [
        {"name": f"the committed {name} catalog is accepted", "catalog": name, "reason": None}
        for name in (*committed_catalogs(), "boxes")
    ]
    index = {character: position for position, character in enumerate(CHARACTER_SET)}

    def case(name: str, reason: str | None, **rest: Any) -> dict[str, Any]:
        return {"name": name, "catalog": "boxes", "reason": reason, **rest}

    cases += [
        case(
            "indented JSON is not canonical",
            "json",
            text_edits=[['{"cap_height_mm"', '{ "cap_height_mm"']],
        ),
        case("a trailing newline is not canonical", "json", append="\n"),
        case(
            "a float where an integer belongs",
            "json",
            text_edits=[['"units_per_em":1000', '"units_per_em":1000.0']],
        ),
        case(
            "a repeated key",
            "json",
            text_edits=[['"units_per_em":1000', '"units_per_em":1000,"units_per_em":1000']],
        ),
        case("a missing block", "shape", changes=[{"path": ["tool"], "remove": True}]),
        case("a field nothing reads", "shape", changes=[{"path": ["notes"], "value": "hello"}]),
        case(
            "another profile",
            "shape",
            changes=[{"path": ["profile"], "value": "exulanica.lettering.glyph-catalog/v2"}],
        ),
        case("a catalog id in capitals", "shape", changes=[{"path": ["catalog_id"], "value": "Boxes"}]),
        case("a boolean", "shape", changes=[{"path": ["units_per_em"], "value": True}]),
        case("a null", "shape", changes=[{"path": ["metrics", "x_height"], "value": None}]),
        case(
            "a licence that is not the OFL",
            "shape",
            changes=[{"path": ["source", "licence", "spdx"], "value": "Apache-2.0"}],
        ),
        case(
            "a commit that is not a hash",
            "shape",
            changes=[{"path": ["source", "commit"], "value": "main"}],
        ),
        case(
            "a copyright with no line",
            "shape",
            changes=[{"path": ["source", "licence", "copyright"], "value": []}],
        ),
        case(
            "a ring with an odd count of numbers",
            "shape",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": [50, 0, 550, 0, 550, 1000, 50],
                }
            ],
        ),
        case(
            "a coordinate outside sixteen bits",
            "shape",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": _rectangle(50, 0, 40000, 1000),
                }
            ],
        ),
        case(
            "a kerning entry that is not a triple",
            "shape",
            changes=[{"path": ["kerning", 0], "value": ["A", "V"]}],
        ),
        case(
            "a promised minimum above the maximum",
            "promise",
            changes=[{"path": ["cap_height_mm", "minimum"], "value": 1300}],
        ),
        case(
            "a minimum edge that is not a millimetre at the smallest size",
            "promise",
            changes=[{"path": ["conversion", "minimum_edge"], "value": 9}],
        ),
        case(
            "a flattening tolerance not taken at the largest size",
            "promise",
            changes=[
                {"path": ["conversion", "flattening_tolerance_cap_height_divisor"], "value": 1000}
            ],
        ),
        case(
            "a scan that failed inside the promise",
            "promise",
            changes=[
                {"path": ["scan", "largest_failing_mm"], "value": 150},
                {"path": ["scan", "failure"], "value": "'H' part 0 outer ring edge 0 has zero length"},
            ],
        ),
        case(
            "a scan that starts below the promised maximum",
            "promise",
            changes=[{"path": ["scan", "from_mm"], "value": 1000}],
        ),
        case(
            "a glyph missing from the set",
            "characters",
            changes=[{"path": ["glyphs", index["z"]], "remove": True}],
        ),
        case(
            "the set out of code point order",
            "characters",
            changes=[
                {"path": ["glyphs", index["A"], "character"], "value": "B"},
                {"path": ["glyphs", index["B"], "character"], "value": "A"},
            ],
        ),
        case(
            "a character outside the set",
            "characters",
            changes=[{"path": ["glyphs", index["e"], "character"], "value": "é"}],
        ),
        case(
            "a kerning pair outside the set",
            "kerning",
            changes=[{"path": ["kerning", 0, 0], "value": "é"}],
        ),
        case(
            "kerning out of order",
            "kerning",
            changes=[
                {"path": ["kerning", 0], "value": ["L", "T", 100]},
                {"path": ["kerning", 1], "value": ["A", "V", -200]},
            ],
        ),
        case("a kerning pair worth nothing", "kerning", changes=[{"path": ["kerning", 0, 2], "value": 0}]),
        case(
            "a ring not starting at its lowest vertex",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": [550, 0, 550, 1000, 50, 1000, 50, 0],
                }
            ],
        ),
        case(
            "a ring wound clockwise",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": [50, 0, 50, 1000, 550, 1000, 550, 0],
                }
            ],
        ),
        case(
            "an edge below the minimum edge",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": [50, 0, 550, 0, 550, 1000, 54, 1000, 50, 996],
                }
            ],
        ),
        case(
            "a ring that crosses itself",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["H"], "parts", 0, "outer"],
                    "value": [50, 0, 550, 0, 50, 1000, 550, 1000],
                }
            ],
        ),
        case(
            "a hole touching its outer ring",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["O"], "parts", 0, "holes", 0],
                    "value": _rectangle(200, 0, 500, 800),
                }
            ],
        ),
        case(
            "two parts overlapping",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["i"], "parts", 1, "outer"],
                    "value": _rectangle(50, 400, 250, 800),
                }
            ],
        ),
        case(
            "parts out of order",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index["i"], "parts", 0, "outer"],
                    "value": _rectangle(50, 600, 250, 800),
                },
                {
                    "path": ["glyphs", index["i"], "parts", 1, "outer"],
                    "value": _rectangle(50, 0, 250, 500),
                },
            ],
        ),
        case(
            "an outline on the space",
            "ring",
            changes=[
                {
                    "path": ["glyphs", index[" "], "parts"],
                    "value": [{"outer": _rectangle(50, 0, 350, 1000), "holes": []}],
                }
            ],
        ),
        case(
            "a letter with no outline",
            "ring",
            changes=[{"path": ["glyphs", index["k"], "parts"], "value": []}],
        ),
        case(
            "an x-height the rings do not show",
            "metrics",
            changes=[{"path": ["metrics", "x_height"], "value": 520}],
        ),
        case(
            "a descender the rings do not show",
            "metrics",
            changes=[{"path": ["metrics", "descender"], "value": -300}],
        ),
    ]
    return cases


def _layout_case(
    name: str,
    catalog: str,
    text: str,
    reason: str | None,
    *,
    cap_height_mm: Any = 200,
    tracking_mm: Any = 0,
    alignment: Any = "left",
    box_width_mm: Any = 4000,
    box_height_mm: Any = 600,
) -> dict[str, Any]:
    return {
        "name": name,
        "catalog": catalog,
        "text": text,
        "cap_height_mm": cap_height_mm,
        "tracking_mm": tracking_mm,
        "alignment": alignment,
        "box_width_mm": box_width_mm,
        "box_height_mm": box_height_mm,
        "reason": reason,
    }


def _lexicon() -> list[str]:
    catalog = json.loads((ROOT / "assets" / "catalogs" / "signage-lexicon.v2.json").read_text())
    return [entry["text"] for entry in catalog["entries"]]


def _layout_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for text in _lexicon():
        for name in committed_catalogs():
            cases.append(
                _layout_case(
                    f"{text!r} centred in {name}",
                    name,
                    text,
                    None,
                    cap_height_mm=200,
                    alignment="centre",
                )
            )
    cases += [
        _layout_case("the smallest promised cap height", "grotesque", "Bakery", None, cap_height_mm=100),
        _layout_case(
            "the largest promised cap height",
            "grotesque",
            "Bakery",
            None,
            cap_height_mm=1200,
            box_width_mm=12000,
            box_height_mm=2000,
        ),
        _layout_case("tracking pushes the letters apart", "slab", "Bread", None, tracking_mm=37),
        _layout_case(
            "a positive kerning pair moves what follows it",
            "boxes",
            "LT",
            None,
            cap_height_mm=500,
            box_height_mm=1000,
        ),
        _layout_case(
            "a word with a descender, centred",
            "modern_serif",
            "Grocery",
            None,
            cap_height_mm=300,
            alignment="centre",
            box_height_mm=800,
        ),
        _layout_case("an alignment nobody sets", "grotesque", "Bakery", "alignment", alignment="right"),
        _layout_case("a cap height below the promise", "grotesque", "Bakery", "cap_height", cap_height_mm=99),
        _layout_case(
            "a cap height above the promise", "grotesque", "Bakery", "cap_height", cap_height_mm=1201
        ),
        _layout_case(
            "a cap height that is not whole", "grotesque", "Bakery", "cap_height", cap_height_mm=250.5
        ),
        _layout_case(
            "a cap height that is a boolean", "grotesque", "Bakery", "cap_height", cap_height_mm=True
        ),
        _layout_case("tracking below zero", "grotesque", "Bakery", "tracking", tracking_mm=-1),
        _layout_case("tracking that is not whole", "grotesque", "Bakery", "tracking", tracking_mm=2.5),
        _layout_case("a box with no width", "grotesque", "Bakery", "box", box_width_mm=0),
        _layout_case("a box height below zero", "grotesque", "Bakery", "box", box_height_mm=-5),
        _layout_case("no text at all", "grotesque", "", "text"),
        _layout_case("a space before the text", "grotesque", " Bakery", "text"),
        _layout_case("a space after the text", "grotesque", "Bakery ", "text"),
        _layout_case("two spaces between words", "grotesque", "Public  Library", "text"),
        _layout_case("an accented character", "grotesque", "Café", "character"),
        _layout_case("a mark outside the set", "grotesque", "Bakery!", "character"),
        _layout_case(
            "a tab between words", "grotesque", "Public\tLibrary", "character", box_width_mm=6000
        ),
    ]
    return cases


def _fit_cases(catalogs: dict[str, str]) -> list[dict[str, Any]]:
    """A sign that fits its box exactly, and the same sign in a box one millimetre smaller."""
    catalog = read_glyph_catalog(_read(catalogs["slab"]))
    text = "Public Library"
    wide = layout_sign(
        catalog,
        text,
        cap_height_mm=200,
        tracking_mm=0,
        alignment="left",
        box_width_mm=9000,
        box_height_mm=900,
    )
    width = wide.ink.right_mm - wide.ink.left_mm
    tall = wide.ink.top_mm - wide.ink.bottom_mm
    # The ink is centred on the cap height, so the box that fits exactly is the ink plus the
    # room the rounding leaves below the baseline, which the layout puts at (height - cap) / 2.
    height = next(
        size
        for size in range(tall, tall + 400)
        if _accepts(catalog, text, box_width_mm=width, box_height_mm=size)
    )
    return [
        {
            **_layout_case(
                "a sign that fits its box exactly",
                "slab",
                text,
                None,
                box_width_mm=width,
                box_height_mm=height,
            )
        },
        {
            **_layout_case(
                "a box a millimetre too narrow",
                "slab",
                text,
                "fit",
                box_width_mm=width - 1,
                box_height_mm=height,
            )
        },
        {
            **_layout_case(
                "a box a millimetre too short",
                "slab",
                text,
                "fit",
                box_width_mm=width,
                box_height_mm=height - 1,
            )
        },
    ]


def _accepts(catalog: GlyphCatalog, text: str, **rest: Any) -> bool:
    try:
        layout_sign(
            catalog, text, cap_height_mm=200, tracking_mm=0, alignment="left", **rest
        )
    except LetteringRefused:
        return False
    return True


def _touch_cases() -> list[dict[str, Any]]:
    """Letters that share a point: in the font's own units, and only after the rounding."""
    return [
        _layout_case(
            "a kerning pair that overlaps outright",
            "boxes",
            "AV",
            "touch",
            cap_height_mm=500,
            box_height_mm=1000,
        ),
        _layout_case(
            "letters a tenth of a millimetre apart that the rounding brings together",
            "boxes",
            "II",
            "touch",
            cap_height_mm=100,
        ),
        _layout_case(
            "the same pair stays apart with a millimetre of tracking",
            "boxes",
            "II",
            None,
            cap_height_mm=100,
            tracking_mm=1,
        ),
        _layout_case(
            "a pair that touches in the font's own units",
            "modern_serif",
            "fb",
            "touch",
            cap_height_mm=200,
        ),
        _layout_case(
            "a pair that touches only after the rounding",
            "modern_serif",
            "Qj",
            "touch",
            cap_height_mm=107,
        ),
        # Rounding-driven touching flickers with size: this pair touches from 101 to 110 mm and
        # again from 117 to 122, and stays apart at 111.
        _layout_case(
            "the same pair four millimetres larger, which stays apart",
            "modern_serif",
            "Qj",
            None,
            cap_height_mm=111,
        ),
        _layout_case(
            "a condensed pair that touches only after the rounding",
            "condensed",
            "vy",
            "touch",
            cap_height_mm=114,
        ),
        _layout_case(
            "a slab pair that touches only after the rounding",
            "slab",
            "fV",
            "touch",
            cap_height_mm=100,
        ),
    ]


def _glyph_cases(catalogs: dict[str, str]) -> list[dict[str, Any]]:
    """Rings in millimetres, so both sides round the same way at the same sizes."""
    wanted = [
        ("grotesque", "g", 100),
        ("grotesque", "g", 1200),
        ("slab", "&", 333),
        ("modern_serif", "B", 777),
        ("boxes", "O", 150),
        ("boxes", "p", 101),
    ]
    cases = []
    for name, character, size in wanted:
        catalog = read_glyph_catalog(_read(catalogs[name]))
        parts = glyph_parts_mm(catalog, character, size)
        cases.append(
            {
                "name": f"{character!r} in {name} at {size} mm",
                "catalog": name,
                "character": character,
                "cap_height_mm": size,
                "parts": [
                    {
                        "outer": [value for point in outer for value in point],
                        "holes": [[value for point in hole for value in point] for hole in holes],
                    }
                    for outer, holes in parts
                ],
            }
        )
    return cases


def _outcome(catalog: GlyphCatalog, case: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    try:
        layout = layout_sign(
            catalog,
            case["text"],
            cap_height_mm=case["cap_height_mm"],
            tracking_mm=case["tracking_mm"],
            alignment=case["alignment"],
            box_width_mm=case["box_width_mm"],
            box_height_mm=case["box_height_mm"],
        )
    except LetteringRefused as refused:
        return refused.reason, None
    return None, {
        "placements": [
            [placement.index, placement.character, placement.x_mm, placement.baseline_mm]
            for placement in layout.placements
        ],
        "ink": [
            layout.ink.left_mm,
            layout.ink.bottom_mm,
            layout.ink.right_mm,
            layout.ink.top_mm,
        ],
    }


def render() -> tuple[str, bytes]:
    """The case file's text and the test catalog's bytes."""
    catalogs = _catalogs()
    boxes = _box_catalog()
    catalog_cases = _catalog_cases()
    for case in catalog_cases:
        reason = None
        try:
            read_glyph_catalog(catalog_bytes(case, catalogs))
        except LetteringRefused as refused:
            reason = refused.reason
        if reason != case["reason"]:
            raise AssertionError(f"{case['name']}: the reader says {reason}, not {case['reason']}")
    layout_cases = _layout_cases() + _fit_cases(catalogs) + _touch_cases()
    read = {name: read_glyph_catalog(_read(path)) for name, path in catalogs.items()}
    for case in layout_cases:
        reason, layout = _outcome(read[case["catalog"]], case)
        if reason != case["reason"]:
            raise AssertionError(f"{case['name']}: the rule says {reason}, not {case['reason']}")
        if layout is not None:
            case["layout"] = layout
    document = {
        "about": (
            "Cases every lettering reader runs: tests/test_lettering_cases.py in the backend and "
            "cases.test.ts beside this file. Paths are relative to this file. A catalog case reads "
            "its catalog with the listed changes applied and the listed text edits made to the "
            "canonical bytes; reason is null when every reader accepts it, and otherwise the one "
            "reason every reader refuses it for. A layout case lays its text out and must give the "
            "recorded placements, or refuse for the recorded reason. A glyph case pins the rings in "
            "millimetres at a cap height. Generated by scripts/generate_lettering_cases.py; do not "
            "edit by hand."
        ),
        "catalogs": catalogs,
        "catalog_cases": catalog_cases,
        "layout_cases": layout_cases,
        "glyph_cases": _glyph_cases(catalogs),
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n", boxes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    BOXES.parent.mkdir(parents=True, exist_ok=True)
    if arguments.check:
        text, boxes = render()
        stale = [
            path
            for path, wanted in ((CASES, text.encode("utf-8")), (BOXES, boxes))
            if not path.is_file() or path.read_bytes() != wanted
        ]
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    # The cases lean on the test catalog, so it is written first and the cases read it back.
    BOXES.write_bytes(_box_catalog())
    CASES.write_text(render()[0], encoding="utf-8")
    print(f"wrote {CASES.relative_to(ROOT)} and {BOXES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
