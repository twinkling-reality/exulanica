// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  WORLD_TRAFFIC_NOTE_ATTRIBUTE,
  openGeneratedWorld,
  trafficRefusalWords,
} from '../src/composition/generated-world.js';
import { TILE_TRAFFIC_ATTRIBUTE } from '../src/composition/tile-traffic.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * A saved generated world draws its own traffic while its tiles are attached, read through the
 * world's version; when the server refuses its roads by name, the page says why in words chosen by
 * the refusal's code, and never leaves the reason blank.
 */

const loadGeneratedTile = vi.hoisted(() => vi.fn());
vi.mock('@exulanica/atlas-react/generated-tile', () => ({
  loadGeneratedTile,
  tileToRenderer: (x: number, y: number, z: number) => [x / 1000, z / 1000, -y / 1000],
}));
vi.mock('@exulanica/atlas-react/traffic', () => ({
  TrafficLayer: class {
    drawnCount = 0;
    hidden = 0;
    animating = false;
    nextSecond = null;
    setWindow(): void {}
    update(): void {}
    secondAt(): null { return null; }
    destroy(): void {}
  },
}));
vi.mock('../src/texture-library.js', () => ({
  committedTextureLibrary: async () => ({ textureManifest: new Uint8Array(), textureSet: async () => new Uint8Array() }),
}));
vi.mock('@exulanica/atlas-core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-core')>()),
  parseTextureSetManifest: () => ({ sets: [] }),
}));

const access = { baseUrl: 'https://exulanica.test', token: 'private' };
const bakedTileId = '11111111-0000-4000-8000-000000000000';
const entry = {
  entryId: 'entry',
  worldId: 'world:generated:town',
  authoredVersionId: 'version',
  generatedGround: {
    recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'region:generated',
    arrivalMm: [128000, 105, -58750], arrivalFacingMm: [0, 3000],
    tiles: [{ tileX: 0, tileY: 0, tileInputsDigest: '0'.repeat(64), bakedTileId, state: 'baked' }],
  },
} as unknown as SavedWorldEntry;

afterEach(() => vi.unstubAllGlobals());

describe('a saved generated world\'s traffic', () => {
  it('says why a world shows no vehicles, in words for every refusal and never blank', () => {
    expect(trafficRefusalWords('roads_unavailable')).toMatch(/cannot use one of its junctions/);
    expect(trafficRefusalWords('roads_not_stated')).toMatch(/no roads/);
    expect(trafficRefusalWords('roads_world_too_large')).toMatch(/more parking places/);
    for (const code of ['generated_world_grammar_changed', 'generated_world_unreadable']) {
      expect(trafficRefusalWords(code)).toMatch(/could not be read/);
    }
    const other = trafficRefusalWords('a_refusal_nobody_named');
    expect(other).toContain('a_refusal_nobody_named');
    expect(other.startsWith('No cars drive this world')).toBe(true);
  });

  it('reads the traffic through the world, says a refusal in words, and clears it when the tiles go', async () => {
    const shell = document.createElement('div');
    const env = { shell } as never;
    const traffic: string[] = [];
    const tileBytes = new Uint8Array([1, 2, 3]);
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith('/traffic')) {
        traffic.push(`${url.pathname}?${url.searchParams.toString()}`);
        return new Response(JSON.stringify({ code: 'roads_unavailable', detail: 'a turn passes a stop line' }), {
          status: 409, headers: { 'content-type': 'application/json' },
        });
      }
      const etag = createHash('sha256').update(tileBytes).digest('hex');
      return new Response(new Blob([tileBytes.slice().buffer]), { headers: { ETag: `"${etag}"` } });
    }));
    let tileDisposed = false;
    loadGeneratedTile.mockResolvedValue({
      navigationWorld: { eyeHeight: 1.6, surface: { sample: () => null } },
      attach: () => ({ metrics: {}, animating: false, dispose: () => { tileDisposed = true; } }),
    });
    const tile = await openGeneratedWorld(env, access, entry);
    expect(tile).not.toBeNull();
    const listeners = new Set<() => void>();
    const host = {
      app: { on: (_: string, callback: () => void) => listeners.add(callback), off: (_: string, callback: () => void) => listeners.delete(callback) },
      environmentRoot: { addChild: () => undefined },
      camera: null,
    } as never;
    const attachment = tile!.attach(host);
    await vi.waitFor(() => expect(shell.querySelector(`[${WORLD_TRAFFIC_NOTE_ATTRIBUTE}]`)).not.toBeNull(), { timeout: 10_000 });
    expect(traffic).toEqual(['/world/versions/version/traffic?world_id=world%3Agenerated%3Atown&seconds=60']);
    const note = shell.querySelector(`[${WORLD_TRAFFIC_NOTE_ATTRIBUTE}]`)!;
    expect(note.getAttribute(WORLD_TRAFFIC_NOTE_ATTRIBUTE)).toBe('roads_unavailable');
    expect(note.textContent).toBe(trafficRefusalWords('roads_unavailable'));
    expect(JSON.parse(shell.getAttribute(TILE_TRAFFIC_ATTRIBUTE) ?? '{}')).toMatchObject({ state: 'refused', reason: 'roads_unavailable' });
    attachment.dispose();
    expect(tileDisposed).toBe(true);
    expect(shell.querySelector(`[${WORLD_TRAFFIC_NOTE_ATTRIBUTE}]`)).toBeNull();
    expect(shell.hasAttribute(TILE_TRAFFIC_ATTRIBUTE)).toBe(false);
    expect(listeners.size).toBe(0);
  });
});
