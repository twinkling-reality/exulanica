"""The glyph catalog reader: canonical JSON in, a checked catalog out, or one refusal.

A catalog is made once by ``tools/lettering`` from an open-licence font and read here with no font
parser. It is trusted for nothing it can be checked for. The reader refuses, in this order:

``json``
    The bytes are not exactly what ``exulanica.canonical.canonical_json`` writes.
``shape``
    A field is missing, extra, of the wrong type or outside its range, or the profile is not
    version 1's.
``promise``
    The cap-height promise does not hold together: the minimum edge is not one millimetre at the
    smallest promised size, the conversion does not name the promised range, or the recorded scan
    failed at a size inside the promise.
``characters``
    The glyphs are not exactly the version 1 character set, in code point order.
``kerning``
    A pair names a character outside the set, repeats or is out of order, or has a zero value.
``ring``
    A ring is not stored as the tool stores it (counter-clockwise, starting at its lowest then
    leftmost vertex, parts and holes in that order), has an edge shorter than the minimum edge, or
    breaks the ring rule, the hole rule or the part rule; or a glyph other than the space has no
    outline.
``metrics``
    The cap height, x-height, ascender or descender is not what the rings say.

Every check runs on every read. ``read_committed_catalog`` caches by catalog id, so a validator
that reads the same catalog for every sign pays once per process.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.lettering.geometry import Part, Point, parts_problem
from exulanica.lettering.refusal import LetteringRefused

__all__ = [
    "CATALOG_DIRECTORY",
    "CHARACTER_SET",
    "GLYPH_CATALOG_PROFILE",
    "Glyph",
    "GlyphCatalog",
    "read_committed_catalog",
    "read_glyph_catalog",
]

GLYPH_CATALOG_PROFILE: Final = "exulanica.lettering.glyph-catalog/v1"
#: Space, five marks, digits, capitals and small letters, in code point order.
CHARACTER_SET: Final = " &',-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "lettering")
)

#: TrueType stores coordinates, advances and kerning values in 16 bits.
_COORDINATE: Final = (-32768, 32767)
_ADVANCE: Final = (0, 65535)
#: The font's em is 16 to 16384 units (the OpenType head table's range).
_UNITS_PER_EM: Final = (16, 16384)
#: Keeps 2 * coordinate * cap height in millimetres well inside 2^53, the TypeScript bound.
_LARGEST_CAP_HEIGHT_MM: Final = 1_000_000
_CATALOG_ID: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
_HEX_40: Final = re.compile(r"[0-9a-f]{40}")
_HEX_64: Final = re.compile(r"[0-9a-f]{64}")
_PRINTABLE: Final = re.compile(r"[\x20-\x7e]+")


@dataclass(frozen=True, slots=True)
class Glyph:
    character: str
    advance: int
    #: Counter-clockwise parts in font units, each an outer ring and its holes.
    parts: tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class GlyphCatalog:
    catalog_id: str
    catalog_version: int
    units_per_em: int
    cap_height: int
    x_height: int
    ascender: int
    descender: int
    minimum_edge: int
    minimum_cap_height_mm: int
    maximum_cap_height_mm: int
    largest_failing_mm: int
    family: str
    style: str
    glyphs: dict[str, Glyph]
    kerning: dict[tuple[str, str], int]
    #: The source block as read, for provenance: repository, commit, file, digests and licence.
    source: dict[str, Any]


def _refuse(reason: str, message: str) -> LetteringRefused:
    return LetteringRefused(reason, message)


def _object(value: Any, keys: tuple[str, ...], where: str, optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(value, dict):
        raise _refuse("shape", f"{where} is not an object")
    required = set(keys)
    present = set(value)
    if not required <= present or not present <= required | set(optional):
        raise _refuse(
            "shape",
            f"{where} has fields {sorted(present)}, not {sorted(required)}"
            + (f" and optionally {sorted(optional)}" if optional else ""),
        )
    return value


def _integer(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _refuse("shape", f"{where} is {value!r}, not an integer from {low} to {high}")
    return value


def _text(value: Any, where: str, pattern: re.Pattern[str] = _PRINTABLE) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _refuse("shape", f"{where} is {value!r}, not {pattern.pattern}")
    return value


def _list(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise _refuse("shape", f"{where} is not a list")
    return value


def _flat_ring(value: Any, where: str) -> tuple[Point, ...]:
    values = _list(value, where)
    if len(values) < 6 or len(values) % 2:
        raise _refuse("shape", f"{where} has {len(values)} numbers, not an even count of 6 or more")
    for index, number in enumerate(values):
        _integer(number, f"{where}[{index}]", *_COORDINATE)
    return tuple((values[i], values[i + 1]) for i in range(0, len(values), 2))


def _source(value: Any) -> dict[str, Any]:
    source = _object(
        value,
        (
            "repository",
            "commit",
            "path",
            "url",
            "file",
            "sha256",
            "byte_size",
            "family",
            "style",
            "font_version",
            "licence",
        ),
        "source",
    )
    for key in ("repository", "path", "url", "file", "family", "style", "font_version"):
        _text(source[key], f"source.{key}")
    _text(source["commit"], "source.commit", _HEX_40)
    _text(source["sha256"], "source.sha256", _HEX_64)
    _integer(source["byte_size"], "source.byte_size", 1, 2**31 - 1)
    licence = _object(source["licence"], ("spdx", "copyright", "file", "url", "sha256"), "licence")
    if licence["spdx"] != "OFL-1.1":
        raise _refuse("shape", f"source.licence.spdx is {licence['spdx']!r}, not 'OFL-1.1'")
    lines = _list(licence["copyright"], "source.licence.copyright")
    if not lines:
        raise _refuse("shape", "source.licence.copyright has no line")
    for index, line in enumerate(lines):
        _text(line, f"source.licence.copyright[{index}]")
    _text(licence["file"], "source.licence.file")
    _text(licence["url"], "source.licence.url")
    _text(licence["sha256"], "source.licence.sha256", _HEX_64)
    return source


def _shape(document: Any) -> dict[str, Any]:
    root = _object(
        document,
        (
            "profile",
            "catalog_id",
            "catalog_version",
            "source",
            "tool",
            "units_per_em",
            "metrics",
            "conversion",
            "cap_height_mm",
            "scan",
            "glyphs",
            "kerning",
        ),
        "the catalog",
    )
    if root["profile"] != GLYPH_CATALOG_PROFILE:
        raise _refuse("shape", f"profile is {root['profile']!r}, not {GLYPH_CATALOG_PROFILE!r}")
    _text(root["catalog_id"], "catalog_id", _CATALOG_ID)
    _integer(root["catalog_version"], "catalog_version", 1, 2**31 - 1)
    _source(root["source"])
    tool = _object(root["tool"], ("name", "rules_version", "fonttools"), "tool")
    _text(tool["name"], "tool.name")
    _integer(tool["rules_version"], "tool.rules_version", 1, 2**31 - 1)
    _text(tool["fonttools"], "tool.fonttools")
    _integer(root["units_per_em"], "units_per_em", *_UNITS_PER_EM)
    metrics = _object(
        root["metrics"], ("cap_height", "x_height", "ascender", "descender"), "metrics"
    )
    _integer(metrics["cap_height"], "metrics.cap_height", 1, _COORDINATE[1])
    for key in ("x_height", "ascender", "descender"):
        _integer(metrics[key], f"metrics.{key}", *_COORDINATE)
    conversion = _object(
        root["conversion"],
        (
            "flattening_tolerance_cap_height_divisor",
            "minimum_edge_cap_height_divisor",
            "minimum_edge",
            "vertices_removed",
            "largest_shift",
        ),
        "conversion",
    )
    for key in ("flattening_tolerance_cap_height_divisor", "minimum_edge_cap_height_divisor"):
        _integer(conversion[key], f"conversion.{key}", 1, _LARGEST_CAP_HEIGHT_MM)
    _integer(conversion["minimum_edge"], "conversion.minimum_edge", 1, _COORDINATE[1])
    _integer(conversion["vertices_removed"], "conversion.vertices_removed", 0, 2**31 - 1)
    _integer(conversion["largest_shift"], "conversion.largest_shift", 0, _COORDINATE[1])
    promise = _object(root["cap_height_mm"], ("minimum", "maximum"), "cap_height_mm")
    for key in ("minimum", "maximum"):
        _integer(promise[key], f"cap_height_mm.{key}", 1, _LARGEST_CAP_HEIGHT_MM)
    scan = _object(root["scan"], ("from_mm", "largest_failing_mm"), "scan", optional=("failure",))
    _integer(scan["from_mm"], "scan.from_mm", 1, _LARGEST_CAP_HEIGHT_MM)
    _integer(scan["largest_failing_mm"], "scan.largest_failing_mm", 0, _LARGEST_CAP_HEIGHT_MM)
    if "failure" in scan:
        _text(scan["failure"], "scan.failure")
    for index, glyph in enumerate(_list(root["glyphs"], "glyphs")):
        where = f"glyphs[{index}]"
        _object(glyph, ("character", "advance", "parts"), where)
        if not isinstance(glyph["character"], str) or len(glyph["character"]) != 1:
            raise _refuse("shape", f"{where}.character is not one character")
        _integer(glyph["advance"], f"{where}.advance", *_ADVANCE)
        for part_index, part in enumerate(_list(glyph["parts"], f"{where}.parts")):
            part_where = f"{where}.parts[{part_index}]"
            _object(part, ("outer", "holes"), part_where)
            _flat_ring(part["outer"], f"{part_where}.outer")
            for hole_index, hole in enumerate(_list(part["holes"], f"{part_where}.holes")):
                _flat_ring(hole, f"{part_where}.holes[{hole_index}]")
    for index, pair in enumerate(_list(root["kerning"], "kerning")):
        where = f"kerning[{index}]"
        if not isinstance(pair, list) or len(pair) != 3:
            raise _refuse("shape", f"{where} is not [left, right, value]")
        for side in (0, 1):
            if not isinstance(pair[side], str) or len(pair[side]) != 1:
                raise _refuse("shape", f"{where}[{side}] is not one character")
        _integer(pair[2], f"{where}[2]", *_COORDINATE)
    return root


def _promise(root: dict[str, Any]) -> None:
    promise = root["cap_height_mm"]
    conversion = root["conversion"]
    scan = root["scan"]
    minimum, maximum = promise["minimum"], promise["maximum"]
    cap_height = root["metrics"]["cap_height"]
    if minimum > maximum:
        raise _refuse("promise", f"the promised minimum {minimum} exceeds the maximum {maximum}")
    if conversion["minimum_edge_cap_height_divisor"] != minimum:
        raise _refuse("promise", "the minimum edge is not taken at the promised minimum")
    if conversion["flattening_tolerance_cap_height_divisor"] != maximum:
        raise _refuse("promise", "the flattening tolerance is not taken at the promised maximum")
    expected_edge = -(-cap_height // minimum)
    if conversion["minimum_edge"] != expected_edge:
        raise _refuse(
            "promise",
            f"the minimum edge is {conversion['minimum_edge']}, not ceil({cap_height} / {minimum})"
            f" = {expected_edge}: one millimetre at the smallest promised cap height",
        )
    if scan["from_mm"] != maximum:
        raise _refuse("promise", f"the scan starts at {scan['from_mm']}, not at {maximum}")
    largest = scan["largest_failing_mm"]
    if largest >= minimum:
        raise _refuse("promise", f"the scan failed at {largest} mm, inside the promise")
    if (largest > 0) != ("failure" in scan):
        raise _refuse("promise", "the scan names a failure exactly when it failed at some size")


def _characters(root: dict[str, Any]) -> None:
    characters = "".join(glyph["character"] for glyph in root["glyphs"])
    if characters != CHARACTER_SET:
        raise _refuse("characters", f"the glyphs are {characters!r}, not the version 1 set")


def _kerning(root: dict[str, Any]) -> dict[tuple[str, str], int]:
    table: dict[tuple[str, str], int] = {}
    previous: tuple[int, int] | None = None
    for left, right, value in root["kerning"]:
        if left not in CHARACTER_SET or right not in CHARACTER_SET:
            raise _refuse("kerning", f"the pair {left!r} {right!r} leaves the character set")
        order = (ord(left), ord(right))
        if previous is not None and order <= previous:
            raise _refuse("kerning", f"the pair {left!r} {right!r} repeats or is out of order")
        if value == 0:
            raise _refuse("kerning", f"the pair {left!r} {right!r} is zero, which is omitted")
        previous = order
        table[(left, right)] = value
    return table


def _start(ring: tuple[Point, ...]) -> tuple[int, int]:
    return ring[0][1], ring[0][0]


def _glyphs(root: dict[str, Any], minimum_edge: int) -> dict[str, Glyph]:
    glyphs: dict[str, Glyph] = {}
    for glyph in root["glyphs"]:
        character = glyph["character"]
        parts: list[Part] = []
        for part_index, part in enumerate(glyph["parts"]):
            where = f"{character!r} part {part_index}"
            outer = _flat_ring(part["outer"], where)
            holes = tuple(_flat_ring(hole, where) for hole in part["holes"])
            for ring in (outer, *holes):
                if min(ring, key=lambda point: (point[1], point[0])) != ring[0]:
                    raise _refuse("ring", f"{where} has a ring not starting at its lowest vertex")
                count = len(ring)
                for i in range(count):
                    a, b = ring[i], ring[(i + 1) % count]
                    if max(abs(a[0] - b[0]), abs(a[1] - b[1])) < minimum_edge:
                        raise _refuse("ring", f"{where} has edge {i} shorter than the minimum edge")
            starts = [_start(hole) for hole in holes]
            if starts != sorted(set(starts)):
                raise _refuse("ring", f"{where} has its holes out of order")
            parts.append((outer, holes))
        starts = [_start(outer) for outer, _ in parts]
        if starts != sorted(set(starts)):
            raise _refuse("ring", f"{character!r} has its parts out of order")
        if (character == " ") != (not parts):
            raise _refuse("ring", f"{character!r} has the wrong outline: only the space has none")
        problem = parts_problem(parts)
        if problem:
            raise _refuse("ring", f"{character!r} {problem}")
        glyphs[character] = Glyph(character, glyph["advance"], tuple(parts))
    return glyphs


def _metrics(root: dict[str, Any], glyphs: dict[str, Glyph]) -> None:
    def ys(glyph: Glyph) -> list[int]:
        return [y for outer, holes in glyph.parts for ring in (outer, *holes) for _, y in ring]

    everything = [y for glyph in glyphs.values() for y in ys(glyph)]
    measured = {
        "cap_height": max(ys(glyphs["H"])),
        "x_height": max(ys(glyphs["x"])),
        "ascender": max(everything),
        "descender": min(everything),
    }
    if measured != root["metrics"]:
        raise _refuse("metrics", f"the rings measure {measured}, not {root['metrics']}")


def read_glyph_catalog(raw: bytes) -> GlyphCatalog:
    """A checked glyph catalog, or a :class:`LetteringRefused` naming the first failing check."""
    try:
        document = json.loads(raw.decode("utf-8"))
        canonical = canonical_json(document)
    except (UnicodeDecodeError, ValueError, CanonicalisationError) as error:
        raise _refuse("json", f"the catalog is not JSON with a canonical form: {error}") from error
    if canonical != raw:
        raise _refuse("json", "the catalog is not exactly its canonical JSON")
    root = _shape(document)
    _promise(root)
    _characters(root)
    kerning = _kerning(root)
    minimum_edge = root["conversion"]["minimum_edge"]
    glyphs = _glyphs(root, minimum_edge)
    _metrics(root, glyphs)
    metrics = root["metrics"]
    return GlyphCatalog(
        catalog_id=root["catalog_id"],
        catalog_version=root["catalog_version"],
        units_per_em=root["units_per_em"],
        cap_height=metrics["cap_height"],
        x_height=metrics["x_height"],
        ascender=metrics["ascender"],
        descender=metrics["descender"],
        minimum_edge=minimum_edge,
        minimum_cap_height_mm=root["cap_height_mm"]["minimum"],
        maximum_cap_height_mm=root["cap_height_mm"]["maximum"],
        largest_failing_mm=root["scan"]["largest_failing_mm"],
        family=root["source"]["family"],
        style=root["source"]["style"],
        glyphs=glyphs,
        kerning=kerning,
        source=root["source"],
    )


@lru_cache(maxsize=16)
def read_committed_catalog(catalog_id: str, catalog_version: int = 1) -> GlyphCatalog:
    """The committed catalog ``assets/catalogs/lettering/<id>.v<version>.json``, checked."""
    if not _CATALOG_ID.fullmatch(catalog_id):
        raise _refuse("shape", f"{catalog_id!r} is not a catalog id")
    path = CATALOG_DIRECTORY / f"{catalog_id}.v{catalog_version}.json"
    catalog = read_glyph_catalog(path.read_bytes())
    if (catalog.catalog_id, catalog.catalog_version) != (catalog_id, catalog_version):
        raise _refuse("shape", f"{path.name} holds {catalog.catalog_id} v{catalog.catalog_version}")
    return catalog
