# Development evaluation tiles

Development evaluation only, never served in production. These are pinned golden bakes, not
product inputs. The app's development preview route loads one by name
(`?preview=1&tile=<name>`), and `test/generated-tile-evaluation.test.ts` builds the app and proves
that no production build emits these bytes or the code that reads them.

## `tile-conformance.owd`

- Source: `web/packages/loom-tess/test/fixtures/tile-conformance.json`, tess's conformance tile.
- Made with, from `web/`:

  ```bash
  pnpm tess bake packages/loom-tess/test/fixtures/tile-conformance.json packages/app/src/dev/tiles/tile-conformance.owd
  ```

- sha256: `7b7c9fe9464a2de7264a56ae830ca0dd7ed59b1f8a51150dde415a1792e51678` (703,588 bytes).
- render_batch triangle digest: `185d7be67689db9b290e5c8571b09485a822ba843dae9cd80b85922bcc6ccec4`,
  the value tess's own conformance test pins.

`test/generated-tile-golden.test.ts` rebakes the source through tess's bake command and requires
these bytes exactly, so a tess change that moves the golden fails there. Rebake this file in the
same change that moves the fixture.

The bytes moved on 2026-09-17 without the tessellator moving at all: the city's material catalog
gained the sets texture batch 3 published, the fixture pins the catalog digest in its tile record,
and the container carries that record. The render_batch digest above did not move with it, which
is the useful half of the story: the catalog pin reaches the container's header and not its
triangles.

They moved again on 2026-09-18, from 564,788 bytes to 701,276, when tessellator 18 began cutting a
facade's openings out of its face and returning the wall into each. This time the render_batch
digest moved with them and the nav_envelope digest did NOT, holding at
`dcd548bde8d8ca988c1e3b433c9515fe6531c95d7a5f4085d627e1b54e7eb811` across both bakes. That pair is
the useful half of this story: `city.facade` carries navigation ground `none`, so an opening
changes what is drawn and cannot change what a person stands on. `tile_inputs_digest` held at
`5dd2dcb5de5b684fc485e4c2ad3b25bdc89c0f9ce3a73e4af043e13ec4b75b22` as well, because a tile's inputs
are its document's and not its tessellator's.

And again at tessellator 19, from 701,276 bytes to 703,556, when a ground bay's own panels gained
the returns across the steps in depth between them: a door set back as much as 1.79 m had nothing
drawn between it and the face, which is why it read as a rectangle floating behind a wall.
render_batch moved, nav_envelope held at
`dcd548bde8d8ca988c1e3b433c9515fe6531c95d7a5f4085d627e1b54e7eb811` for the third version running,
and `tile_inputs_digest` held at `5dd2dcb5de5b684fc485e4c2ad3b25bdc89c0f9ce3a73e4af043e13ec4b75b22`.

And again at tessellator 20, from 703,556 bytes to 703,588, when ADR-0024 put a coordinate unit in
the tile record at city grammar version 3. EVERY DIGEST MOVED THIS TIME, including the two that had
held for three versions, and the reason is worth reading before the next schema change: not one
triangle of the drawn world changed. Measured as multisets, `render_batch`'s 8,435 vertices and
4,072 triangles and `nav_envelope`'s 4,414 and 5,755 are identical either side. `render_batch`
emits them in a DIFFERENT ORDER, because `tessellate` sorts records by `(kind, sha256)`: nine
`city.facade` records carry the grammar version that wrote them, so nine digests moved, so those
nine reordered and their triangles with them. `nav_envelope` holds its ORDER too, since a facade
draws nothing there, and moved only through the record digests every entry carries.

And again on 2026-09-19, WITHOUT THE TESSELLATOR MOVING, when the street-name catalog stopped being
a list of twelve authored names and became the composition of authored elements and street types.
This is the same class as the 2026-09-17 move above and it came out the same way: the container's
bytes moved from `4c76b9e0e20030883af478e932ca561e91ba79e6f45e881b31f017d91168637c` to
`7b7c9fe9464a2de7264a56ae830ca0dd7ed59b1f8a51150dde415a1792e51678`, THE SIZE DID NOT MOVE AT ALL, at 703,588 bytes, because a
catalog digest is a fixed number of bytes wherever it appears, and `render_batch` held at
`185d7be67689db9b290e5c8571b09485a822ba843dae9cd80b85922bcc6ccec4` for the second time. The catalog
pin reaches the container's header and not its triangles, and this is now the second independent
occasion on which that was predicted in advance and measured afterwards.

The lesson for whoever moves a schema next: on this format a record's place is content-addressed, so
"a schema change moves no geometry" is true of the geometry and false of its order. The check that
tells them apart is the triangle multiset, not the section digest.
