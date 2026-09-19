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

## Result

Filled in after the rebake, in the record named in this file's own commit, not by editing the
prediction above.
