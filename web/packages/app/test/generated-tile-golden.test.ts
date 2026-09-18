import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// Relative to web/, where the suite runs.
const GOLDEN = resolve('packages/app/src/dev/tiles/tile-conformance.owd');
const README = resolve('packages/app/src/dev/tiles/README.md');
const FIXTURE = resolve('packages/loom-tess/test/fixtures/tile-conformance.json');
const TESS_CLI = resolve('packages/loom-tess/src/node/cli.ts');
const TESS_CONFORMANCE = resolve('packages/loom-tess/test/triangle-digest-conformance.test.ts');
const TSX = resolve('node_modules/tsx/dist/cli.mjs');

const PINNED_SHA256 = '1ef74efa8eef6844715e5b33711fccd48692ca245de133124287f3249b89c07f';
const PINNED_RENDER_BATCH = 'e906150d744f4ad12fab849c45f439e1501a3f5fd729d3e3ce716f88fcc3b455';

describe('the pinned development evaluation tile', () => {
  it('is exactly what tess\'s own bake command makes from tess\'s conformance fixture', () => {
    const directory = mkdtempSync(join(tmpdir(), 'exulanica-tile-golden-'));
    try {
      const out = join(directory, 'tile-conformance.owd');
      // Tess's bake entry, run as a command: the fence keeps its node entry out of other packages.
      const printed = JSON.parse(execFileSync(process.execPath, [TSX, TESS_CLI, 'bake', FIXTURE, out], { encoding: 'utf8' })) as {
        readonly container_sha256: string;
        readonly triangle_digests: { readonly render_batch: string };
      };
      const golden = readFileSync(GOLDEN);
      expect(Buffer.compare(readFileSync(out), golden)).toBe(0);
      expect(createHash('sha256').update(golden).digest('hex')).toBe(PINNED_SHA256);
      expect(printed.container_sha256).toBe(PINNED_SHA256);
      expect(printed.triangle_digests.render_batch).toBe(PINNED_RENDER_BATCH);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  }, 120_000);

  it('carries the render_batch digest tess\'s conformance test pins, and says so beside the file', () => {
    expect(readFileSync(TESS_CONFORMANCE, 'utf8')).toContain(`render_batch: '${PINNED_RENDER_BATCH}'`);
    const readme = readFileSync(README, 'utf8');
    expect(readme).toContain(PINNED_SHA256);
    expect(readme).toContain(PINNED_RENDER_BATCH);
    expect(readme).toContain('packages/loom-tess/test/fixtures/tile-conformance.json');
    expect(readme).toContain('Development evaluation only, never served in production.');
  });
});
