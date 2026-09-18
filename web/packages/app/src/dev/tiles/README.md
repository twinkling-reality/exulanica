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

- sha256: `dbe071f7615326b70f7c7f0b1739f42f21ba771e1e22aba98b295eac139e4395` (701,276 bytes).
- render_batch triangle digest: `d4ebae2fe31d5fb7564af26e6e81388184d25478f4ff29a495057edf97f04188`,
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
