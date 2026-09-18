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

- sha256: `74e4524558b1e7ebcb533cb4bd7238f440652e460ce4e74335bf79e32b17b0c9` (393,840 bytes).
- render_batch triangle digest: `00d9a4d792cb2a7eb414268ecc9a25e4ec935ca65910144c78b0d9f5c3642ac9`,
  the value tess's own conformance test pins.

`test/generated-tile-golden.test.ts` rebakes the source through tess's bake command and requires
these bytes exactly, so a tess change that moves the golden fails there. Rebake this file in the
same change that moves the fixture.

The bytes moved on 2026-09-17 without the tessellator moving at all: the city's material catalog
gained the sets texture batch 3 published, the fixture pins the catalog digest in its tile record,
and the container carries that record. The render_batch digest above did not move with it, which
is the useful half of the story: the catalog pin reaches the container's header and not its
triangles.
