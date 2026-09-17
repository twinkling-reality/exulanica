"""The layout rule: one line of text in one catalog, placed in integer millimetres, or refused.

The rule is stated once in ``docs/lettering.md`` and twice in code, here and in
``@exulanica/loom-lettering``'s ``layout.ts``; the shared cases hold the two to the same answer.

Refusals, one reason each, in this order:

``alignment``   not ``left`` or ``centre``.
``cap_height``  not an integer inside the catalog's promise.
``tracking``    not an integer of zero or more.
``box``         a width or height that is not an integer of one or more.
``text``        empty, or a space at either end or two spaces together.
``character``   the first character outside the catalog's set, named, never substituted.
``fit``         the ink does not fit the box. Never squeezed.
``touch``       two placed glyphs share a point.

Placement, in millimetres, with ``C`` the catalog's cap height in font units and ``H`` the cap
height in millimetres:

* ``scale(v) = floor((2 v H + C) / (2 C))``: nearest, halves toward +infinity, which keeps two
  points a millimetre apart on either side of zero apart.
* The pen advances in exact font units: ``pen[0] = 0``, ``pen[i + 1] = pen[i] + advance(c[i]) +
  kern(c[i], c[i + 1])``. Character ``i``'s origin is ``scale(pen[i]) + i * tracking``, and its
  outline is scaled relative to that origin, so every copy of a letter at one size is the same
  geometry.
* The ink box is the extent of every non-space glyph's scaled outline. ``left`` puts the ink's left
  edge at 0; ``centre`` puts it at ``floor((width - ink width) / 2)``. The baseline sits at
  ``floor((height - H) / 2)``, centring the cap height as a sign writer sets capitals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from exulanica.lettering.catalog import GlyphCatalog
from exulanica.lettering.geometry import Part, glyphs_touch
from exulanica.lettering.refusal import LetteringRefused

__all__ = [
    "ALIGNMENTS",
    "InkBox",
    "Placement",
    "SignLayout",
    "glyph_parts_mm",
    "layout_sign",
    "scale_to_mm",
]

ALIGNMENTS: Final = ("left", "centre")


@dataclass(frozen=True, slots=True)
class Placement:
    #: The character's position in the text.
    index: int
    character: str
    #: The glyph origin, in box millimetres.
    x_mm: int
    baseline_mm: int


@dataclass(frozen=True, slots=True)
class InkBox:
    left_mm: int
    bottom_mm: int
    right_mm: int
    top_mm: int


@dataclass(frozen=True, slots=True)
class SignLayout:
    catalog_id: str
    catalog_version: int
    text: str
    cap_height_mm: int
    tracking_mm: int
    alignment: str
    box_width_mm: int
    box_height_mm: int
    #: One per non-space character, in text order.
    placements: tuple[Placement, ...]
    ink: InkBox


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def scale_to_mm(value: int, cap_height_mm: int, cap_height: int) -> int:
    """Font units to whole millimetres: nearest, halves toward +infinity."""
    return (2 * value * cap_height_mm + cap_height) // (2 * cap_height)


def glyph_parts_mm(catalog: GlyphCatalog, character: str, cap_height_mm: int) -> tuple[Part, ...]:
    """A glyph's parts in millimetres relative to its origin on the baseline, at a cap height."""
    glyph = catalog.glyphs[character]

    def ring(points: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
        return tuple(
            (
                scale_to_mm(x, cap_height_mm, catalog.cap_height),
                scale_to_mm(y, cap_height_mm, catalog.cap_height),
            )
            for x, y in points
        )

    return tuple((ring(outer), tuple(ring(hole) for hole in holes)) for outer, holes in glyph.parts)


def _shifted(parts: tuple[Part, ...], dx: int, dy: int) -> tuple[Part, ...]:
    def ring(points: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
        return tuple((x + dx, y + dy) for x, y in points)

    return tuple((ring(outer), tuple(ring(hole) for hole in holes)) for outer, holes in parts)


def layout_sign(
    catalog: GlyphCatalog,
    text: str,
    *,
    cap_height_mm: int,
    tracking_mm: int,
    alignment: str,
    box_width_mm: int,
    box_height_mm: int,
) -> SignLayout:
    """Where each letter of ``text`` goes in the box, or a :class:`LetteringRefused`."""
    if alignment not in ALIGNMENTS:
        raise LetteringRefused("alignment", f"{alignment!r} is not one of {ALIGNMENTS}")
    low, high = catalog.minimum_cap_height_mm, catalog.maximum_cap_height_mm
    if not _is_integer(cap_height_mm) or not low <= cap_height_mm <= high:
        raise LetteringRefused(
            "cap_height",
            f"{cap_height_mm!r} mm is outside {catalog.catalog_id} v{catalog.catalog_version}'s "
            f"promise of {low} to {high} mm",
        )
    if not _is_integer(tracking_mm) or tracking_mm < 0:
        raise LetteringRefused("tracking", f"{tracking_mm!r} is not an integer of zero or more")
    for name, value in (("width", box_width_mm), ("height", box_height_mm)):
        if not _is_integer(value) or value < 1:
            raise LetteringRefused(
                "box", f"the box {name} {value!r} is not an integer of 1 or more"
            )
    if not isinstance(text, str) or not text or text != text.strip(" ") or "  " in text:
        raise LetteringRefused(
            "text", f"{text!r} is empty, starts or ends with a space, or has two together"
        )
    for character in text:
        if character not in catalog.glyphs:
            raise LetteringRefused(
                "character",
                f"U+{ord(character):04X} {character!r} is not in "
                f"{catalog.catalog_id} v{catalog.catalog_version}",
            )

    cap = catalog.cap_height
    by_character = {
        character: glyph_parts_mm(catalog, character, cap_height_mm) for character in set(text)
    }
    pen = 0
    origins: list[int] = []
    for index, character in enumerate(text):
        origins.append(scale_to_mm(pen, cap_height_mm, cap) + index * tracking_mm)
        pen += catalog.glyphs[character].advance
        if index + 1 < len(text):
            pen += catalog.kerning.get((character, text[index + 1]), 0)

    inked = [index for index, character in enumerate(text) if by_character[character]]
    xs = [
        origins[index] + x
        for index in inked
        for outer, _ in by_character[text[index]]
        for x, _ in outer
    ]
    ys = [y for index in inked for outer, _ in by_character[text[index]] for _, y in outer]
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    width = right - left
    offset = -left if alignment == "left" else (box_width_mm - width) // 2 - left
    baseline = (box_height_mm - cap_height_mm) // 2
    if width > box_width_mm or baseline + bottom < 0 or baseline + top > box_height_mm:
        raise LetteringRefused(
            "fit",
            f"{text!r} inks {width} by {top - bottom} mm with the cap height centred, which does "
            f"not fit a {box_width_mm} by {box_height_mm} mm box",
        )

    placed = [
        _shifted(by_character[text[index]], origins[index] + offset, baseline) for index in inked
    ]
    for first in range(len(inked)):
        for second in range(first + 1, len(inked)):
            if glyphs_touch(placed[first], placed[second]):
                raise LetteringRefused(
                    "touch",
                    f"{text[inked[first]]!r} at {inked[first]} and {text[inked[second]]!r} at "
                    f"{inked[second]} share a point at {cap_height_mm} mm with tracking "
                    f"{tracking_mm} mm",
                )

    return SignLayout(
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.catalog_version,
        text=text,
        cap_height_mm=cap_height_mm,
        tracking_mm=tracking_mm,
        alignment=alignment,
        box_width_mm=box_width_mm,
        box_height_mm=box_height_mm,
        placements=tuple(
            Placement(index, text[index], origins[index] + offset, baseline) for index in inked
        ),
        ink=InkBox(left + offset, bottom + baseline, right + offset, top + baseline),
    )
