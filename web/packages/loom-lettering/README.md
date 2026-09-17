# loom-lettering

Shop-sign lettering as data, in TypeScript: the glyph catalog reader and the layout rule.

The catalogs under `assets/catalogs/lettering/` are made once from four open-licence typefaces by
`tools/lettering`, a Python tool in its own environment. Nothing in the product parses a font, here
or in the backend. `docs/lettering.md` states the rules; `exulanica.lettering` is the Python copy of
these same two, and `test/lettering-cases.json` holds the two languages to the same answers: the
same placements to the millimetre, and the same one reason for every refusal.

The package is core only: `src/core` compiles with no `lib.dom` and no `@types/node`, so a host
global is a type error, and the dependency-cruiser fence stops it importing a host module or any
other workspace package. tess reads `@exulanica/loom-lettering/core` to turn a placed sign into
triangles: a letter is its outline as integer rings with holes, which is exactly what tess's ring
rule triangulates.

    pnpm --filter @exulanica/loom-lettering typecheck
    pnpm vitest run packages/loom-lettering

`test/cases/boxes.v1.json` is a catalog of rectangles written by the case generator, not made from a
font. It carries the cases a real typeface cannot show: a kerning pair that overlaps outright, and a
pair of letters a tenth of a millimetre apart that the millimetre rounding brings together.
