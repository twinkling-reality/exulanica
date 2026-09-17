"""Shop-sign lettering as data: glyph catalogs, their reader, and the layout rule.

Letters are exact geometry. A glyph catalog holds each letter's outline as integer rings made once
from an open-licence font by ``tools/lettering``; nothing here parses a font, and nothing in the
product may import that tool (``tests/test_lettering_boundary.py``). The layout rule places one
line of text in a box in integer millimetres, or refuses it by name. ``docs/lettering.md`` states
the rules; ``@exulanica/loom-lettering`` is the TypeScript copy tess reads, held to this one by the
shared cases.
"""

from __future__ import annotations

from exulanica.lettering.catalog import (
    CATALOG_DIRECTORY,
    CHARACTER_SET,
    GLYPH_CATALOG_PROFILE,
    Glyph,
    GlyphCatalog,
    read_committed_catalog,
    read_glyph_catalog,
)
from exulanica.lettering.layout import (
    ALIGNMENTS,
    InkBox,
    Placement,
    SignLayout,
    glyph_parts_mm,
    layout_sign,
    scale_to_mm,
)
from exulanica.lettering.refusal import CATALOG_REASONS, LAYOUT_REASONS, LetteringRefused

__all__ = [
    "ALIGNMENTS",
    "CATALOG_DIRECTORY",
    "CATALOG_REASONS",
    "CHARACTER_SET",
    "GLYPH_CATALOG_PROFILE",
    "LAYOUT_REASONS",
    "Glyph",
    "GlyphCatalog",
    "InkBox",
    "LetteringRefused",
    "Placement",
    "SignLayout",
    "glyph_parts_mm",
    "layout_sign",
    "read_committed_catalog",
    "read_glyph_catalog",
    "scale_to_mm",
]
