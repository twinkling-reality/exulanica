import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { generatedTileEvaluationName, isAtlasPreview } from '../src/config.js';
import { GENERATED_TILE_EVALUATION_ATTRIBUTE } from '../src/composition/generated-tile.js';

describe('generated tile evaluation entry: who may ask', () => {
  it('names a tile only on the development preview route', () => {
    const search = '?preview=1&tile=tile-conformance';
    expect(generatedTileEvaluationName(search, isAtlasPreview(search, true))).toBe('tile-conformance');
    // A production build: isAtlasPreview is false whatever the query says.
    expect(generatedTileEvaluationName(search, isAtlasPreview(search, false))).toBeNull();
    // A workspace session: no preview flag, so no tile, even in development.
    expect(generatedTileEvaluationName('?tile=tile-conformance', isAtlasPreview('?tile=tile-conformance', true))).toBeNull();
    expect(generatedTileEvaluationName(search, false)).toBeNull();
  });

  it('accepts a plain name and nothing that could be a path or a URL', () => {
    const name = (tile: string): string | null =>
      generatedTileEvaluationName(`?preview=1&tile=${encodeURIComponent(tile)}`, true);
    expect(name('corridor-1')).toBe('corridor-1');
    expect(name('a'.repeat(64))).toBe('a'.repeat(64));
    for (const refused of [
      '', 'a'.repeat(65), '../tile', 'tile/one', 'Tile', 'tile.owd', '-tile', 'tile-', 'tile--one',
      'https://example.com/tile', '/@fs/etc/passwd', 'tile one', 'tile%2Fone',
    ]) {
      expect(name(refused)).toBeNull();
    }
    expect(generatedTileEvaluationName('?preview=1', true)).toBeNull();
  });
});

/**
 * What only the evaluation path carries: the composition's own attribute and wording, the tile
 * runtime's refusal text and sky name, and tess's triangle digest domain.
 */
const MARKERS = [
  GENERATED_TILE_EVALUATION_ATTRIBUTE,
  'Development evaluation of generated tile',
  'No surface_material record dresses this surface: the tile states that none exists.',
  'generated-tile-sky',
  'exulanica/owd-triangle-digest',
  '__exulanicaProbeProductApi',
] as const;

// Relative to web/, where the suite runs.
const APP = resolve('packages/app');
const VITE = join(APP, 'node_modules/vite/bin/vite.js');
const scratch: string[] = [];
afterAll(() => {
  for (const directory of scratch) rmSync(directory, { recursive: true, force: true });
});

function files(root: string): string[] {
  return readdirSync(root).flatMap((name) => {
    const path = join(root, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

/** The pinned tile's first bytes: its magic, header length and the start of its header. */
const TILE_PREFIX = readFileSync(join(APP, 'src/dev/tiles/tile-conformance.owd')).subarray(0, 96);

/** Build the app as `vite build` does from a shell, in its own process and environment. */
function buildApp(mode: 'production' | 'development'): {
  readonly names: readonly string[];
  readonly text: string;
  readonly holdsTileBytes: boolean;
} {
  const outDir = mkdtempSync(join(tmpdir(), `exulanica-tile-evaluation-${mode}-`));
  scratch.push(outDir);
  execFileSync(process.execPath, [VITE, 'build', '--mode', mode, '--outDir', outDir, '--emptyOutDir', '--logLevel', 'error'], {
    cwd: APP,
    env: { ...process.env, NODE_ENV: mode },
    stdio: 'pipe',
  });
  const emitted = files(outDir);
  const text = emitted
    .filter((path) => /\.(?:js|html|css|json)$/.test(path))
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n');
  // Every emitted file, whatever its name, searched for the tile's bytes, inlined or not.
  const holdsTileBytes = emitted.some((path) => readFileSync(path).includes(TILE_PREFIX))
    || text.includes(TILE_PREFIX.toString('base64').slice(0, 64));
  return { names: emitted.map((path) => relative(outDir, path)), text, holdsTileBytes };
}

describe('generated tile evaluation entry: unreachable from a production build', () => {
  it('emits no tile code, no tile and no texture set in a production build', () => {
    const production = buildApp('production');
    expect(production.names.some((name) => name.endsWith('index.html'))).toBe(true);
    for (const marker of MARKERS) expect(production.text.includes(marker), marker).toBe(false);
    expect(production.names.filter((name) => /\.(?:owd|ltex)$/.test(name))).toEqual([]);
    expect(production.names.filter((name) => /generated-tile/.test(name))).toEqual([]);
    expect(production.holdsTileBytes).toBe(false);
  }, 180_000);

  it('would see all of it if the development branch were reachable (the control)', () => {
    const development = buildApp('development');
    for (const marker of MARKERS) expect(development.text.includes(marker), marker).toBe(true);
    expect(development.names.some((name) => name.endsWith('.ltex'))).toBe(true);
    expect(development.names.some((name) => name.endsWith('.owd'))).toBe(true);
    expect(development.holdsTileBytes).toBe(true);
  }, 180_000);
});
