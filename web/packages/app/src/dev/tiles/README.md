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

- sha256: `bd07246dbeb9b1116498a233ede7790da2cbcf8eeef1024b4e33682460f351c1` (703,556 bytes).
- render_batch triangle digest: `3aee7162da258e98e1de96ba73a551d0b578a97263eda013d9a7608fb0b1cd7e`,
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
