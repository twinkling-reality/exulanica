import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import {
  PAINTED_FRAME_ROUTE,
  PAINTED_LAB_MARKER,
  PAINTED_SPLAT_ROUTE,
  paintedLabAsked,
  paintedPush,
  readPaintedFrame,
} from '../src/dev/painted-splat.js';

describe('painted lab: who may ask', () => {
  it('opens only for the plain word on a development build', () => {
    expect(paintedLabAsked('?painted=1', true)).toBe(true);
    expect(paintedLabAsked('?entry=01a13bd3-fa95-7c62-8683-42e78f2a0e2c&painted=1', true)).toBe(true);
    expect(paintedLabAsked('?painted=1', false)).toBe(false);
    for (const refused of ['', '?painted', '?painted=', '?painted=0', '?painted=true', '?painted=01', '?painted=1&painted=1',
      '?painted=/tmp/splat.ply', '?painted=..%2Fsplat.sog', '?painted=http://example.test/x.sog', '?painted=1%20']) {
      expect(paintedLabAsked(refused, true), refused).toBe(false);
    }
  });
});

describe('painted lab: how far the layout is pushed back', () => {
  it('takes one plain distance of at most 10 m, else the look keeps its own', () => {
    expect(paintedPush('?painted=1&push=0.6')).toBe(0.6);
    expect(paintedPush('?push=2')).toBe(2);
    expect(paintedPush('?push=10')).toBe(10);
    for (const refused of ['', '?push', '?push=', '?push=-1', '?push=.5', '?push=1e1', '?push=10.5', '?push=11',
      '?push=0.125', '?push=0.6&push=0.7', '?push=metres', '?push=0x1']) {
      expect(paintedPush(refused), refused).toBeNull();
    }
  });
});

describe('painted lab: the splat frame', () => {
  const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  it('takes a rotation and a translation', () => {
    expect(readPaintedFrame({ sceneFromAssetRowMajor: identity })).toEqual(identity);
    const c = Math.cos(0.7), s = Math.sin(0.7);
    const turned = [c, 0, s, 12.5, 0, 1, 0, -3, -s, 0, c, 40, 0, 0, 0, 1];
    expect(readPaintedFrame({ sceneFromAssetRowMajor: turned })).toEqual(turned);
  });

  it('refuses anything that is not rigid and finite', () => {
    const refused: Record<string, unknown> = {
      missing: {},
      'not an object': 'identity',
      'fifteen numbers': { sceneFromAssetRowMajor: identity.slice(1) },
      'a string inside': { sceneFromAssetRowMajor: identity.map((n, i) => (i === 0 ? '1' : n)) },
      'not finite': { sceneFromAssetRowMajor: identity.map((n, i) => (i === 3 ? Number.POSITIVE_INFINITY : n)) },
      'not a number': { sceneFromAssetRowMajor: identity.map((n, i) => (i === 5 ? Number.NaN : n)) },
      projective: { sceneFromAssetRowMajor: identity.map((n, i) => (i === 14 ? 0.5 : n)) },
      scaled: { sceneFromAssetRowMajor: identity.map((n, i) => ([0, 5, 10].includes(i) ? 2 : n)) },
      sheared: { sceneFromAssetRowMajor: identity.map((n, i) => (i === 1 ? 0.2 : n)) },
      reflected: { sceneFromAssetRowMajor: identity.map((n, i) => (i === 0 ? -1 : n)) },
    };
    for (const [what, value] of Object.entries(refused)) expect(() => readPaintedFrame(value), what).toThrow(TypeError);
  });
});

// Relative to web/, where the suite runs.
const APP = resolve('packages/app');
const VITE = join(APP, 'node_modules/vite/bin/vite.js');
const scratch: string[] = [];
afterAll(() => {
  for (const directory of scratch) rmSync(directory, { recursive: true, force: true });
});

function files(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

function builtText(mode: 'production' | 'development'): string {
  const outDir = mkdtempSync(join(tmpdir(), `exulanica-painted-lab-${mode}-`));
  scratch.push(outDir);
  execFileSync(process.execPath, [VITE, 'build', '--mode', mode, '--outDir', outDir, '--emptyOutDir', '--logLevel', 'error'], {
    cwd: APP, env: { ...process.env, NODE_ENV: mode }, stdio: 'pipe',
  });
  return files(outDir).filter((path) => /\.(?:js|html)$/.test(path)).map((path) => readFileSync(path, 'utf8')).join('\n');
}

describe('painted lab: never in a production build', () => {
  it('emits neither the lab nor its routes in production', () => {
    const text = builtText('production');
    expect(text.length).toBeGreaterThan(0);
    for (const marker of [PAINTED_LAB_MARKER, PAINTED_SPLAT_ROUTE, PAINTED_FRAME_ROUTE, '__paintedLab']) expect(text.includes(marker), marker).toBe(false);
  }, 300_000);

  it('would carry them if the development branch were reachable (the control)', () => {
    const text = builtText('development');
    for (const marker of [PAINTED_LAB_MARKER, PAINTED_SPLAT_ROUTE, '__paintedLab']) expect(text.includes(marker), marker).toBe(true);
  }, 300_000);
});
