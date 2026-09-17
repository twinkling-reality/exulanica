"""A glyph catalog from one committed font, as canonical JSON bytes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fontTools
from fontTools.ttLib import TTFont

from exulanica_lettering_tool.kerning import kerning
from exulanica_lettering_tool.outline import (
    Conversion,
    GlyphParts,
    OutlineRefused,
    OutlineStatistics,
    glyph_parts,
)
from exulanica_lettering_tool.scan import largest_failing_size

PROFILE = "exulanica.lettering.glyph-catalog/v1"
TOOL_NAME = "exulanica-lettering-tool"
#: Bumped whenever a rule here changes the bytes a font converts to.
RULES_VERSION = 1
#: Space, five marks, digits, capitals and small letters: the version 1 set, in code point order.
CHARACTER_SET = " &',-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
#: The smallest promised cap height. The minimum edge is one millimetre at this size.
MINIMUM_CAP_HEIGHT_MM = 100
#: The city grammar's largest fascia height: a cap height cannot exceed the fascia it sits in.
MAXIMUM_CAP_HEIGHT_MM = 1200

_LICENCE_STATEMENT = "This Font Software is licensed under the SIL Open Font License, Version 1.1."


class CatalogRefused(Exception):
    """A font this tool will not turn into a catalog."""


def canonical_json(value: Any) -> bytes:
    """``exulanica.canonical.canonical_json``'s form: sorted keys, no whitespace, integers only."""

    def check(item: Any, path: str) -> None:
        if isinstance(item, bool) or item is None or isinstance(item, float):
            raise CatalogRefused(f"{path} is {item!r}, which has no canonical form here")
        if isinstance(item, dict):
            for key, sub in item.items():
                check(sub, f"{path}.{key}")
        elif isinstance(item, list):
            for index, sub in enumerate(item):
                check(sub, f"{path}[{index}]")
        elif not isinstance(item, int | str):
            raise CatalogRefused(f"{path} has type {type(item).__name__}")

    check(value, "$")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_record(root: Path, font_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The font's and its OFL.txt's entries in SOURCE.json, each checked against the file."""
    directory = font_path.parent
    source = json.loads((directory / "SOURCE.json").read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in source["files"]}
    for name in (font_path.name, "OFL.txt"):
        entry = entries[name]
        file = directory / name
        if _sha256(file) != entry["sha256"] or file.stat().st_size != entry["byte_size"]:
            raise CatalogRefused(f"{file.relative_to(root)} is not the file SOURCE.json records")
    return source, entries


def _licence(root: Path, directory: Path, entry: dict[str, Any]) -> dict[str, Any]:
    text = (directory / "OFL.txt").read_bytes().decode("utf-8").replace("\r\n", "\n")
    head, statement, _ = text.partition(_LICENCE_STATEMENT)
    if not statement:
        raise CatalogRefused(f"{directory.relative_to(root)}/OFL.txt is not the SIL OFL 1.1")
    # The licence body defines the term; only the copyright statement above it can declare one.
    if re.search(r"reserved\s+font\s+names?", head, flags=re.IGNORECASE):
        raise CatalogRefused(f"{directory.relative_to(root)}/OFL.txt declares a Reserved Font Name")
    copyright_lines = [line.rstrip() for line in head.strip().splitlines() if line.strip()]
    return {
        "spdx": "OFL-1.1",
        "copyright": copyright_lines,
        "file": f"{directory.relative_to(root).as_posix()}/OFL.txt",
        "url": entry["url"],
        "sha256": entry["sha256"],
    }


def _name(font: TTFont, *ids: int) -> str:
    for name_id in ids:
        value = font["name"].getDebugName(name_id)
        if value:
            return value
    raise CatalogRefused(f"the font has no name record {ids}")


def _contours(font: TTFont, glyph_name: str) -> list[tuple[list[tuple[int, int]], list[int]]]:
    table = font["glyf"]
    glyph = table[glyph_name]
    if glyph.isComposite():
        for component in glyph.components:
            if hasattr(component, "transform"):
                raise OutlineRefused(f"component {component.glyphName} is scaled or rotated")
            if component.flags & 0x0400:
                raise OutlineRefused(f"component {component.glyphName} is marked overlapping")
    coordinates, ends, flags = glyph.getCoordinates(table)
    contours = []
    start = 0
    for end in ends:
        points = []
        for index in range(start, end + 1):
            x, y = coordinates[index]
            if x != int(x) or y != int(y):
                raise OutlineRefused("a point is not on the font-unit grid")
            points.append((int(x), int(y)))
        contours.append((points, [int(flags[index]) for index in range(start, end + 1)]))
        start = end + 1
    return contours


def _extremes(glyphs: list[tuple[str, GlyphParts]]) -> dict[str, int]:
    def ys(parts: GlyphParts) -> list[int]:
        return [y for outer, holes in parts for ring in (outer, *holes) for _, y in ring]

    by_character = dict(glyphs)
    everything = [y for _, parts in glyphs for y in ys(parts)]
    return {
        "cap_height": max(ys(by_character["H"])),
        "x_height": max(ys(by_character["x"])),
        "ascender": max(everything),
        "descender": min(everything),
    }


def _flat(ring: tuple[tuple[int, int], ...]) -> list[int]:
    return [value for point in ring for value in point]


def build_catalog(root: Path, catalog_id: str, font_file: str, workers: int) -> bytes:
    """The catalog for ``font_file`` (relative to the repository root), or a refusal naming why."""
    font_path = root / font_file
    source, entries = _source_record(root, font_path)
    licence = _licence(root, font_path.parent, entries["OFL.txt"])
    font = TTFont(font_path)
    if "glyf" not in font:
        raise CatalogRefused(f"{font_file} has no glyf outlines")
    if "fvar" in font:
        raise CatalogRefused(f"{font_file} is a variable font")
    cmap = font.getBestCmap()
    missing = [character for character in CHARACTER_SET if ord(character) not in cmap]
    if missing:
        raise CatalogRefused(f"{font_file} lacks {missing!r}")
    names = {character: cmap[ord(character)] for character in CHARACTER_SET}
    cap_height = font["glyf"][names["H"]].yMax
    rule = Conversion(cap_height, MINIMUM_CAP_HEIGHT_MM, MAXIMUM_CAP_HEIGHT_MM)
    statistics = OutlineStatistics()
    glyphs: list[tuple[str, GlyphParts]] = []
    for character in CHARACTER_SET:
        try:
            glyphs.append(
                (character, glyph_parts(_contours(font, names[character]), rule, statistics))
            )
        except OutlineRefused as refused:
            raise CatalogRefused(f"{font_file} glyph {character!r}: {refused}") from refused
    if glyphs[0][1]:
        raise CatalogRefused(f"{font_file}: the space has an outline")
    metrics = _extremes(glyphs)
    if metrics["cap_height"] != cap_height:
        raise CatalogRefused(
            f"{font_file}: H's rings reach {metrics['cap_height']}, not {cap_height}"
        )
    try:
        kerning_table = kerning(font, names)
    except OutlineRefused as refused:
        raise CatalogRefused(f"{font_file} kerning: {refused}") from refused
    largest, failure = largest_failing_size(glyphs, MAXIMUM_CAP_HEIGHT_MM, cap_height, workers)
    if largest >= MINIMUM_CAP_HEIGHT_MM:
        raise CatalogRefused(f"{font_file} fails at {largest} mm, inside the promise: {failure}")
    scan: dict[str, Any] = {"from_mm": MAXIMUM_CAP_HEIGHT_MM, "largest_failing_mm": largest}
    if failure is not None:
        scan["failure"] = failure
    entry = entries[font_path.name]
    document = {
        "profile": PROFILE,
        "catalog_id": catalog_id,
        "catalog_version": 1,
        "source": {
            "repository": source["repository"],
            "commit": source["commit"],
            "path": entry["repository_path"],
            "url": entry["url"],
            "file": font_file,
            "sha256": entry["sha256"],
            "byte_size": entry["byte_size"],
            "family": _name(font, 16, 1),
            "style": _name(font, 17, 2),
            "font_version": _name(font, 5),
            "licence": licence,
        },
        "tool": {
            "name": TOOL_NAME,
            "rules_version": RULES_VERSION,
            "fonttools": fontTools.version,
        },
        "units_per_em": font["head"].unitsPerEm,
        "metrics": metrics,
        "conversion": {
            "flattening_tolerance_cap_height_divisor": MAXIMUM_CAP_HEIGHT_MM,
            "minimum_edge_cap_height_divisor": MINIMUM_CAP_HEIGHT_MM,
            "minimum_edge": rule.minimum_edge,
            "vertices_removed": statistics.vertices_removed,
            "largest_shift": statistics.largest_shift,
        },
        "cap_height_mm": {"minimum": MINIMUM_CAP_HEIGHT_MM, "maximum": MAXIMUM_CAP_HEIGHT_MM},
        "scan": scan,
        "glyphs": [
            {
                "character": character,
                "advance": font["hmtx"][names[character]][0],
                "parts": [
                    {"outer": _flat(outer), "holes": [_flat(hole) for hole in holes]}
                    for outer, holes in parts
                ],
            }
            for character, parts in glyphs
        ],
        "kerning": kerning_table,
    }
    return canonical_json(document)
