"""Pair kerning from GPOS, flattened to a table over the character set.

The rule, from HarfBuzz's PairPos semantics as read (UNVERIFIED against a shaper, which is neither
installed nor approved):

* The lookups are those of the ``kern`` feature in the ``latn`` script's default language system,
  or ``DFLT``'s when there is no ``latn``, in ascending lookup index.
* Within one lookup the first subtable that matches applies and the rest are skipped. A format 1
  subtable matches only when it holds a record for the pair; a format 2 subtable matches whenever
  its coverage holds the left glyph, class 0 included.
* The pair's value is the sum over lookups of the first glyph's x-advance adjustment.

Anything this rule does not describe refuses the catalog rather than being approximated: a lookup
that is not pair positioning, a value that moves anything but the first glyph's advance, a legacy
``kern`` table, or a glyph in the set that GDEF calls a mark (a mark-skipping flag would change
which glyphs pair).
"""

from __future__ import annotations

from typing import Any

from fontTools.ttLib import TTFont

from exulanica_lettering_tool.outline import OutlineRefused

_PAIR_POSITIONING = 2
_EXTENSION = 9
_X_ADVANCE = 0x0004


def _lookups(font: TTFont) -> list[Any]:
    table = font["GPOS"].table
    scripts = {record.ScriptTag: record.Script for record in table.ScriptList.ScriptRecord}
    script = scripts.get("latn") or scripts.get("DFLT")
    if script is None or script.DefaultLangSys is None:
        return []
    features = table.FeatureList.FeatureRecord
    indices = sorted(
        {
            lookup
            for feature in script.DefaultLangSys.FeatureIndex
            if features[feature].FeatureTag == "kern"
            for lookup in features[feature].Feature.LookupListIndex
        }
    )
    return [table.LookupList.Lookup[index] for index in indices]


def _subtables(lookup: Any) -> list[Any]:
    out = []
    for subtable in lookup.SubTable:
        kind = lookup.LookupType
        if kind == _EXTENSION:
            kind = subtable.ExtensionLookupType
            subtable = subtable.ExtSubTable
        if kind != _PAIR_POSITIONING:
            raise OutlineRefused(f"a kern lookup has type {kind}, not pair positioning")
        if (subtable.ValueFormat1 & ~_X_ADVANCE) or subtable.ValueFormat2:
            raise OutlineRefused("a kern pair adjusts something other than the first advance")
        out.append(subtable)
    return out


def _x_advance(value: Any) -> int:
    return int(getattr(value, "XAdvance", 0) or 0) if value is not None else 0


def _pair(subtable: Any, left: str, right: str) -> int | None:
    coverage = subtable.Coverage.glyphs
    if left not in coverage:
        return None
    if subtable.Format == 1:
        for record in subtable.PairSet[coverage.index(left)].PairValueRecord:
            if record.SecondGlyph == right:
                return _x_advance(record.Value1)
        return None
    first = subtable.ClassDef1.classDefs.get(left, 0) if subtable.ClassDef1 else 0
    second = subtable.ClassDef2.classDefs.get(right, 0) if subtable.ClassDef2 else 0
    if first >= subtable.Class1Count or second >= subtable.Class2Count:
        return None
    return _x_advance(subtable.Class1Record[first].Class2Record[second].Value1)


def kerning(font: TTFont, glyph_names: dict[str, str]) -> list[list[Any]]:
    """``[left, right, value]`` for every pair of set characters with a non-zero total, sorted."""
    if "kern" in font:
        raise OutlineRefused("the font has a legacy kern table, which this rule does not read")
    if "GDEF" in font and font["GDEF"].table.GlyphClassDef is not None:
        classes = font["GDEF"].table.GlyphClassDef.classDefs
        marks = sorted(c for c, name in glyph_names.items() if classes.get(name) == 3)
        if marks:
            raise OutlineRefused(f"GDEF calls set characters marks: {marks!r}")
    if "GPOS" not in font:
        return []
    lookups = [_subtables(lookup) for lookup in _lookups(font)]
    characters = sorted(glyph_names, key=ord)
    table = []
    for left in characters:
        for right in characters:
            total = 0
            for subtables in lookups:
                for subtable in subtables:
                    value = _pair(subtable, glyph_names[left], glyph_names[right])
                    if value is not None:
                        total += value
                        break
            if total:
                table.append([left, right, total])
    return table
