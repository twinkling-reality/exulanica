# Which digests the coordinate unit moves, predicted before anything was rebuilt

Written 2026-09-18 on `lane/coordinate-unit`, at lane head `6d9e3a58` with the Python grammar
already at city version 3 and NOTHING regenerated yet: the fixture document, the grammar table and
the golden container on disk are all still the version 2 artefacts. Written first so the result
cannot be read back onto it.

## The values as they stand, before the rebuild

| | value |
| --- | --- |
| container sha256 | `bd07246dbeb9b1116498a233ede7790da2cbcf8eeef1024b4e33682460f351c1` |
| `tile_inputs_digest` | `5dd2dcb5de5b684fc485e4c2ad3b25bdc89c0f9ce3a73e4af043e13ec4b75b22` |
| `render_batch` triangle digest | `3aee7162da258e98e1de96ba73a551d0b578a97263eda013d9a7608fb0b1cd7e` |
| `nav_envelope` triangle digest | `dcd548bde8d8ca988c1e3b433c9515fe6531c95d7a5f4085d627e1b54e7eb811` |
| city v2 descriptor sha256 | `c82ac5e7d39e95abbeef0d3ead599d87d5421fab7727341ae0df620ef208a7f1` |
| city v3 descriptor sha256 | `e771deef96b49ba35f8a145acbd67dda4d939f93f7730a2b50da78e1727ab41f` |

## What changes in the document

Read from the committed fixture rather than assumed. The tile document carries 180 records in one
grammar entry. The changes are:

- the tile record's own version, 2 to 3, and its new `coordinate_unit` field;
- its grammar pin, version 2 to 3 and descriptor `c82ac5e7` to `e771deef`;
- the grammar entry's matching version and descriptor;
- **nine `city.facade` records**, each carrying a `grammar_version` field bounded to the grammar
  version that wrote it, moving 2 to 3. They are the only records in the document with such a field.

## The prediction

**1. `tile_inputs_digest` MOVES.** It is the SHA-256 of the tile record's own canonical payload, and
three things in that payload change: the record version, the new field, and the grammar pin.

**2. The container sha256 MOVES.** Its header carries the tile record, the grammar entries and
`tessellator_version`, and this change bumps the tessellator source version as well.

**3. BOTH triangle digests MOVE, and this is the one worth stating, because the obvious answer is
that they do not.** The tile record is not an entry: `readList` refuses a tile record in `owned` or
`halo`, so a tile document's own head never reaches a projection. On the coordinate unit alone the
triangle digests would hold. They move because of the FACADE, not because of the unit. The triangle
digest's own definition, item 5b, puts the SHA-256 of each record's canonical payload into every
entry, in every projection, whatever that entry's state. Nine facade payloads change, so nine entry
record-digests change, in `render_batch` and in `nav_envelope` alike.

**4. No triangle coordinate moves.** No geometry rule changes and no parameter changes: the v2 to v3
migration carries all 91 parameters with multiply 1 and add 0 and maps every choice to itself. So
the vertex integers in both projections should be identical, and the digests move only through the
record digests in item 3.

Item 4 is the falsifiable half. If a vertex moves, something in this change was not a schema change
and I want to know before anything is pinned.

## How it will be checked

The rebake prints all four values. Item 4 is checked separately by comparing the decoded
projections' vertex arrays before and after, not by comparing the digests, since a digest that moves
for the reason in item 3 cannot tell me anything about item 4.

## Result: three of four, and the fourth was wrong in a way worth keeping

Measured after the rebuild. Nothing above this line was edited.

| | before | after |
| --- | --- | --- |
| container sha256 | `bd07246d…` | `4c76b9e0e20030883af478e932ca561e91ba79e6f45e881b31f017d91168637c` |
| `tile_inputs_digest` | `5dd2dcb5…` | `915fef63f3291278573dadcb1102968f82f8997cdc1bb63020ef72516ee0a68f` |
| `render_batch` | `3aee7162…` | `185d7be67689db9b290e5c8571b09485a822ba843dae9cd80b85922bcc6ccec4` |
| `nav_envelope` | `dcd548bd…` | `f6158941949203038233d445a8a5aeaa9bdb5ce524a092ec6faf7e19f64424a2` |

**Items 1, 2 and 3 hold.** All four digests moved, and item 3's reasoning was the right one: the
tile record is not an entry, so the unit alone moves no triangle digest, and both moved because nine
facade payloads did.

**ITEM 4 WAS WRONG AS STATED, and its correction is the finding.** I predicted the vertex integers
would be identical. The right statement, measured rather than reasoned:

| projection | vertices | triangles | sequence identical | triangle MULTISET identical |
| --- | --- | --- | --- | --- |
| `render_batch` | 8,435 | 4,072 | **no** | **yes** |
| `nav_envelope` | 4,414 | 5,755 | yes | yes |

Not one triangle of the drawn world changed. They are EMITTED IN A DIFFERENT ORDER, and the reason
is a property of the format I had not accounted for: `tessellate` sorts records by `(kind, sha256)`,
so a record's place among its siblings is CONTENT-ADDRESSED. Nine facades changed one field, so nine
digests moved, so those nine reordered, and every triangle they draw moved with them.
`nav_envelope` is untouched because a facade contributes no triangle to it.

So "a schema change moves no geometry" is true of the geometry and false of its order, and on this
format the order is part of the bytes. The check that separates them is the triangle multiset, not
the section digest.

## Two ways to isolate it, because one measurement could not

The comparison above mixes a tessellator bump with a document change. Split, holding one fixed:

- **the tessellator bump alone** (the version 2 document baked at tessellator 20 against the
  committed version 19 golden): ALL SEVEN SECTIONS BYTE-IDENTICAL, and `tessellator_version` is the
  only header key that differs. Both triangle digests and `tile_inputs_digest` are unchanged
  (`3aee7162…`, `dcd548bd…`, `5dd2dcb5…`). Every code change in this lane is inert on geometry.
- **the document change alone** (version 2 document against version 3 document, both at tessellator
  20): `nav_envelope`'s three sections identical; all four `render_batch` sections moved.

That first line is also ADR-0024's third rule proved end to end rather than asserted: a version 2
document, which states no unit, is read at millimetres and produces exactly the geometry it always
produced.

## An instrument fault found in the middle of this, and how

The first section comparison keyed sections by NAME. There are seven sections across two
projections, and `render_batch` and `nav_envelope` each have a `position_mm`, so one silently
overwrote the other and the tool reported four sections instead of seven. It said `position_mm` was
identical, which was true of `nav_envelope` and false of `render_batch`.

Nothing failed. What caught it was reading the output and asking whether it could be true: the same
run said entry 15 changed from 258 triangles to 136 while claiming the vertex array had not moved,
and both cannot hold. Re-keyed by projection AND name, with a duplicate-key assertion so the
collapse cannot happen silently again, the picture above is the corrected one.
