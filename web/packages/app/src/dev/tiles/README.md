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

- sha256: `e33e8498013fd1ebee0efec63647116d38080584d62ac214279548bc8d82fcfe` (556,364 bytes).
- render_batch triangle digest: `d91ef583dbcdd06bcc5555b8fbc8e36e473abcb50a5943397c628b5432200d74`,
  the value tess's own conformance test pins.

`test/generated-tile-golden.test.ts` rebakes the source through tess's bake command and requires
these bytes exactly, so a tess change that moves the golden fails there. Rebake this file in the
same change that moves the fixture.

The bytes moved on 2026-09-17 without the tessellator moving at all: the city's material catalog
gained the sets texture batch 3 published, the fixture pins the catalog digest in its tile record,
and the container carries that record. The render_batch digest above did not move with it, which
is the useful half of the story: the catalog pin reaches the container's header and not its
triangles.
