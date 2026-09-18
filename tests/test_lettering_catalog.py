"""The committed glyph catalogs, their fonts, and what the catalogs promise about small sizes.

The cap-height promise is the load-bearing claim: every glyph in every catalog survives rounding to
whole millimetres at every cap height from 100 to 1200 mm. The tool proves it exhaustively before
it writes a catalog, which costs about 90 seconds for the four of them; this file re-checks a
sample of sizes with the product's own reader, so a catalog whose promise was never true fails here
rather than in a bake. The sizes are the two ends, the size below the promise where the tool
recorded a failure, and every 97th millimetre in between: 97 is prime, so the sample is not a
multiple of any size that the rounding repeats on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.lettering import (
    CHARACTER_SET,
    LetteringRefused,
    glyph_parts_mm,
    layout_sign,
    read_committed_catalog,
)
from exulanica.lettering.catalog import CATALOG_DIRECTORY
from exulanica.lettering.geometry import parts_problem

ROOT = Path(__file__).resolve().parents[1]
FONT_DIRECTORY = ROOT / "assets" / "fonts"
SPECIFICATION = json.loads(
    (ROOT / "tools" / "lettering" / "catalogs.json").read_text(encoding="utf-8")
)
CATALOG_IDS = sorted(entry["catalog_id"] for entry in SPECIFICATION["catalogs"])
LEXICON = [
    entry["text"]
    for entry in json.loads(
        (ROOT / "assets" / "catalogs" / "signage-lexicon.v2.json").read_text(encoding="utf-8")
    )["entries"]
]


def test_the_catalogs_on_disk_are_the_ones_the_tool_is_told_to_build():
    assert sorted(path.name for path in CATALOG_DIRECTORY.glob("*.json")) == [
        f"{catalog_id}.v1.json" for catalog_id in CATALOG_IDS
    ]
    # A speed bump, not the guard. A fifth catalog is caught without this line: by the comparison
    # above if it was never built, and by test_the_cases_cover_every_committed_catalog_in_both_
    # directions in tests/test_lettering_cases.py if its shared cases were never generated. What
    # the pin adds is that adding a catalog has to touch a test on purpose, beside the font, the
    # licence and the notices entry it also brings. So do not read it as the thing that notices a
    # fifth, and do not delete it as duplication of the line above: it is neither.
    assert CATALOG_IDS == ["condensed", "grotesque", "modern_serif", "slab"]


def test_every_committed_font_is_converted_by_exactly_one_catalog():
    """`catalogs.json` is a deliberate list in one half only, and this holds the other half.

    Which role a typeface serves is a judgement nothing under `assets/fonts` states, so it is
    written by hand. Which fonts are committed is no judgement, and nothing derived it: the tool
    builds what the file names and never looks at what else is there, so a fifth family used to
    arrive converted to nothing, caught only by the notices test, whose message sends the reader
    to `THIRD_PARTY_NOTICES.md` when the fact is that a font is committed which nothing converts.
    A diligent person adds the notices entry and then nothing failed at all.

    Three messages rather than one, because the reader is sent somewhere by whichever fires: a
    font nothing names is an addition half made, an entry naming nothing committed is a removal
    half made, and one font under two entries is a typeface asked to serve two roles.
    """
    named = [entry["font"] for entry in SPECIFICATION["catalogs"]]
    twice = sorted({font for font in named if named.count(font) > 1})
    assert twice == [], f"one font, more than one catalog entry: {twice}"
    # Everything committed there that is not a licence or a source record, which are the two names
    # the tool itself opens by name. No list of fonts, so a second style, a second format or a
    # stray file cannot be a class this goes quiet about.
    committed = sorted(
        path.relative_to(ROOT).as_posix()
        for path in FONT_DIRECTORY.rglob("*")
        if path.is_file() and path.name not in {"OFL.txt", "SOURCE.json"}
    )
    assert committed, "no fonts are committed, so neither direction below means anything"
    unnamed = sorted(set(committed) - set(named))
    assert unnamed == [], (
        f"under assets/fonts and named by no catalog entry: {unnamed}. Every file there that is "
        "not an OFL.txt or a SOURCE.json is a font the tool converts; give it an entry in "
        "tools/lettering/catalogs.json, or do not commit it."
    )
    absent = sorted(set(named) - set(committed))
    assert absent == [], f"tools/lettering/catalogs.json names an uncommitted font: {absent}"


@pytest.mark.parametrize("catalog_id", CATALOG_IDS)
def test_a_catalog_names_the_font_it_was_made_from(catalog_id):
    catalog = read_committed_catalog(catalog_id)
    font = ROOT / catalog.source["file"]
    assert hashlib.sha256(font.read_bytes()).hexdigest() == catalog.source["sha256"]
    assert font.stat().st_size == catalog.source["byte_size"]
    record = json.loads((font.parent / "SOURCE.json").read_text(encoding="utf-8"))
    entry = next(item for item in record["files"] if item["path"] == font.name)
    assert entry["sha256"] == catalog.source["sha256"]
    assert catalog.source["commit"] == record["commit"]
    assert catalog.source["url"] == entry["url"]
    licence = catalog.source["licence"]
    text = (ROOT / licence["file"]).read_bytes()
    assert hashlib.sha256(text).hexdigest() == licence["sha256"]
    head = text.decode("utf-8").replace("\r\n", "\n").split("This Font Software is licensed")[0]
    assert licence["copyright"] == [line.rstrip() for line in head.strip().splitlines() if line]
    # The four families were chosen for having no Reserved Font Name, which the OFL would let the
    # licensor use to forbid a modified version from carrying the name.
    assert "reserved font name" not in head.lower()
    assert licence["spdx"] == "OFL-1.1"


@pytest.mark.parametrize("catalog_id", CATALOG_IDS)
def test_a_catalog_promises_the_same_range_and_holds_it_at_the_sizes_sampled(catalog_id):
    catalog = read_committed_catalog(catalog_id)
    assert (catalog.minimum_cap_height_mm, catalog.maximum_cap_height_mm) == (100, 1200)
    assert catalog.minimum_edge == -(-catalog.cap_height // 100)
    assert catalog.largest_failing_mm < catalog.minimum_cap_height_mm
    sizes = [100, 101, 1200, *range(100, 1200, 97)]
    for size in sizes:
        for character in CHARACTER_SET:
            problem = parts_problem(glyph_parts_mm(catalog, character, size))
            assert problem is None, f"{character!r} at {size} mm: {problem}"


@pytest.mark.parametrize("catalog_id", CATALOG_IDS)
def test_the_size_the_tool_recorded_as_failing_really_fails(catalog_id):
    """The recorded failure is evidence, so it is checked rather than trusted."""
    catalog = read_committed_catalog(catalog_id)
    size = catalog.largest_failing_mm
    assert size > 0
    problems = [
        parts_problem(glyph_parts_mm(catalog, character, size)) for character in CHARACTER_SET
    ]
    assert any(problems), f"{catalog_id} records a failure at {size} mm that does not happen"


@pytest.mark.parametrize("catalog_id", CATALOG_IDS)
def test_every_reviewed_sign_text_lays_out_in_every_catalog(catalog_id):
    """A sign the lexicon offers must be drawable: it fits, and no two letters touch."""
    catalog = read_committed_catalog(catalog_id)
    for text in LEXICON:
        assert set(text) <= set(CHARACTER_SET), text
        for size in (100, 150, 200, 300, 500, 1000, 1200):
            layout = layout_sign(
                catalog,
                text,
                cap_height_mm=size,
                tracking_mm=0,
                alignment="centre",
                box_width_mm=20_000,
                box_height_mm=4_000,
            )
            assert len(layout.placements) == len(text.replace(" ", ""))


def test_letters_that_touch_are_refused_by_name_rather_than_drawn():
    """Measured 2026-09-17: these pairs share a point, and the rule names them."""
    for catalog_id, pair, size in (
        ("condensed", "XX", 200),
        ("slab", "fY", 200),
        ("modern_serif", "fb", 200),
        # Only the rounding brings this pair together: it is apart at 111 mm.
        ("modern_serif", "Qj", 107),
    ):
        catalog = read_committed_catalog(catalog_id)
        with pytest.raises(LetteringRefused) as refused:
            layout_sign(
                catalog,
                pair,
                cap_height_mm=size,
                tracking_mm=0,
                alignment="left",
                box_width_mm=9_000,
                box_height_mm=9_000,
            )
        assert refused.value.reason == "touch"
    # Barlow, the grotesque, has no such pair at any size in the promise (measured over all 4,489
    # ordered pairs at every size from 100 to 1200 in steps of 7).
    catalog = read_committed_catalog("grotesque")
    for pair in ("XX", "fb", "Qj", "gy"):
        layout_sign(
            catalog,
            pair,
            cap_height_mm=200,
            tracking_mm=0,
            alignment="left",
            box_width_mm=9_000,
            box_height_mm=9_000,
        )


def test_the_notices_name_every_file_under_assets_fonts():
    """`THIRD_PARTY_NOTICES.md` goes stale silently; the fonts are the newest thing in it."""
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    files = sorted(path for path in FONT_DIRECTORY.rglob("*") if path.is_file())
    assert files, "no fonts are committed"
    missing = [
        str(path.relative_to(ROOT)) for path in files if str(path.relative_to(ROOT)) not in notices
    ]
    assert missing == [], f"THIRD_PARTY_NOTICES.md does not name {missing}"
    for catalog_id in CATALOG_IDS:
        assert f"assets/catalogs/lettering/{catalog_id}.v1.json" in notices
