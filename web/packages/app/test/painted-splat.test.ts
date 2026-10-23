import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createSceneSplatAsset, splatsAfterToneMapping, validateSogBundle } from '@exulanica/atlas-react/playcanvas';
import { afterAll, describe, expect, it, vi } from 'vitest';
import {
  PAINTED_FRAME_ROUTE,
  PAINTED_LAB_MARKER,
  PAINTED_SPLAT_ROUTE,
  layoutUndrawn,
  openPaintedLab,
  paintedColour,
  paintedLabAsked,
  paintedLayout,
  paintedPush,
  readPaintedFrame,
} from '../src/dev/painted-splat.js';

// The display itself is atlas-react's (splat-display.test.ts); here only that the lab hands it its splat.
// Loading a SOG at its base colour is atlas-react's too (scene-splats.test.ts); here only what the lab asks for.
vi.mock('@exulanica/atlas-react/playcanvas', async (original) => ({
  ...await original<typeof import('@exulanica/atlas-react/playcanvas')>(),
  splatsAfterToneMapping: vi.fn(),
  createSceneSplatAsset: vi.fn(),
  validateSogBundle: vi.fn(),
}));

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

describe('painted lab: the layout under the splat', () => {
  it('is held undrawn unless the page asks for exactly layout=depth', () => {
    expect(paintedLayout('?painted=1')).toBe('undrawn');
    expect(paintedLayout('?painted=1&layout=depth')).toBe('depth');
    for (const other of ['?layout=', '?layout=undrawn', '?layout=Depth', '?layout=depth&layout=depth', '?layout=depth%20']) {
      expect(paintedLayout(other), other).toBe('undrawn');
    }
  });

  it('hides only opaque surfaces for each frame and gives every one back', () => {
    const handlers = new Map<string, () => void>();
    const app = {
      on: (name: string, handler: () => void) => { handlers.set(name, handler); },
      off: (name: string, handler: () => void) => { if (handlers.get(name) === handler) handlers.delete(name); },
    };
    const surface = (transparent: boolean, depthWrite: boolean, visible = true) => ({ visible, material: { transparent, depthWrite } });
    const wall = surface(false, true), water = surface(true, false), glass = surface(true, true), decal = surface(false, false);
    const hidden = surface(false, true, false);
    const render = { meshInstances: [wall, water, glass, decal, hidden, { visible: true, material: null }] };
    const root = { findComponents: (name: string) => (name === 'render' ? [render] : []) };
    const held = layoutUndrawn([root] as never, app as never);
    handlers.get('prerender')!();
    expect([wall.visible, water.visible, glass.visible, decal.visible, hidden.visible]).toEqual([false, true, true, true, false]);
    expect(held.instances).toBe(1);
    handlers.get('postrender')!();
    expect([wall.visible, hidden.visible]).toEqual([true, false]);
    handlers.get('prerender')!();
    held.dispose();
    expect(wall.visible).toBe(true);
    expect(handlers.size).toBe(0);
  });
});

describe('painted lab: the splat on the screen', () => {
  it('is drawn after the camera frame\'s tone mapping, and given back when the lab closes', async () => {
    const shown = { active: true, splats: 1, refresh: vi.fn(), dispose: vi.fn() };
    vi.mocked(splatsAfterToneMapping).mockReturnValue(shown);
    class Piece {
      constructor(readonly name: string) {}
      setLocalPosition(): void {}
      setLocalRotation(): void {}
      addChild(): void {}
      addComponent(): void {}
      destroy(): void {}
    }
    const app = {
      on: () => undefined, off: () => undefined,
      assets: { loadFromUrlAndFilename: (...args: unknown[]) => (args[3] as (e: null, a: object) => void)(null, { unload: () => undefined }), remove: () => undefined },
    };
    const camera = { camera: { name: 'the scene camera' } };
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', async (url: string) => (url === PAINTED_FRAME_ROUTE
      ? new Response(null, { status: 404 })
      : new Response(null, { status: 200, headers: { 'x-painted-lab-format': 'ply' } })));
    try {
      const lab = openPaintedLab({ app, environmentRoot: new Piece('environment'), camera } as never, [], '?painted=1')!;
      await vi.waitFor(() => expect(lab.state().phase).toBe('drawn'));
      expect(splatsAfterToneMapping).toHaveBeenCalledWith(lab.splat(), camera.camera);
      expect(lab.state().display).toBe(true);
      lab.dispose();
      expect(shown.dispose).toHaveBeenCalledOnce();
      expect(lab.state().display).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('painted lab: the splat\'s colour', () => {
  it('is the base colour unless the page asks for exactly bands=3', () => {
    expect(paintedColour('?painted=1')).toBe('base');
    expect(paintedColour('?painted=1&bands=3')).toBe('stored');
    for (const other of ['?bands=', '?bands=0', '?bands=1', '?bands=2', '?bands=03', '?bands=3&bands=3', '?bands=3%20', '?bands=all']) {
      expect(paintedColour(other), other).toBe('base');
    }
  });

  it('loads a SOG in the colour asked and names the degree its resource draws', async () => {
    vi.mocked(splatsAfterToneMapping).mockReturnValue({ active: true, splats: 1, refresh: vi.fn(), dispose: vi.fn() });
    vi.mocked(validateSogBundle).mockReturnValue({ pointCount: 512 });
    vi.mocked(createSceneSplatAsset).mockImplementation(async (_app, _value, colour) =>
      ({ resource: { gsplatData: { shBands: colour === 'base' ? 0 : 3 } }, unload: () => undefined }) as never);
    class Piece {
      constructor(readonly name: string) {}
      setLocalPosition(): void {}
      setLocalRotation(): void {}
      addChild(): void {}
      addComponent(): void {}
      destroy(): void {}
    }
    const app = { on: () => undefined, off: () => undefined, assets: { remove: () => undefined } };
    const camera = { camera: { name: 'the scene camera' } };
    vi.stubGlobal('window', {});
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => (url === PAINTED_FRAME_ROUTE
      ? new Response(null, { status: 404 })
      : new Response(init?.method === 'HEAD' ? null : new ArrayBuffer(8), { status: 200, headers: { 'x-painted-lab-format': 'sog' } })));
    try {
      for (const [search, colour, degree] of [['?painted=1', 'base', 0], ['?painted=1&bands=3', 'stored', 3]] as const) {
        const lab = openPaintedLab({ app, environmentRoot: new Piece('environment'), camera } as never, [], search)!;
        await vi.waitFor(() => expect(lab.state().phase).toBe('drawn'));
        expect(vi.mocked(createSceneSplatAsset).mock.lastCall?.[2], search).toBe(colour);
        expect(lab.state(), search).toMatchObject({ format: 'sog', colour, colourDegree: degree });
        lab.dispose();
      }
    } finally {
      vi.unstubAllGlobals();
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
