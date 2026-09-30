// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WORLD_TRAFFIC_NOTE_ATTRIBUTE, openGeneratedWorld } from '../src/composition/generated-world.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * A page that cannot load its traffic code (a chunk the network lost) still opens the world, without
 * its vehicles, and says so.
 */

const loadGeneratedTile = vi.hoisted(() => vi.fn());
vi.mock('@exulanica/atlas-react/generated-tile', () => ({ loadGeneratedTile }));
vi.mock('../src/traffic-api.js', () => { throw new Error('the traffic chunk could not be fetched'); });
vi.mock('../src/texture-library.js', () => ({
  committedTextureLibrary: async () => ({ textureManifest: new Uint8Array(), textureSet: async () => new Uint8Array() }),
}));
vi.mock('@exulanica/atlas-core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-core')>()),
  parseTextureSetManifest: () => ({ sets: [] }),
}));

afterEach(() => vi.unstubAllGlobals());

describe('a saved generated world whose traffic code does not load', () => {
  it('opens without vehicles, says so, and takes the words down with the world', async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(new Blob([bytes.slice().buffer]), {
      headers: { ETag: `"${createHash('sha256').update(bytes).digest('hex')}"` },
    })));
    const dispose = vi.fn();
    const tile = {
      navigationWorld: { eyeHeight: 1.6, surface: { sample: () => ({ height: 0 }) } },
      attach: vi.fn(() => ({ metrics: {}, animating: false, dispose })),
    };
    loadGeneratedTile.mockResolvedValue(tile);
    const shell = document.createElement('div');
    const entry = {
      entryId: 'entry', worldId: 'world:generated:town', authoredVersionId: 'version',
      generatedGround: {
        recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'region:generated',
        arrivalMm: [128000, 0, -58750], arrivalFacingMm: [0, 3000],
        tiles: [{ tileX: 0, tileY: 0, tileInputsDigest: '0'.repeat(64), bakedTileId: '11111111-0000-4000-8000-000000000000', state: 'baked' }],
      },
    } as unknown as SavedWorldEntry;
    const opened = await openGeneratedWorld({ shell } as never, { baseUrl: 'https://exulanica.test', token: 't' }, entry);
    expect(opened).not.toBeNull();
    const note = (): Element | null => shell.querySelector(`[${WORLD_TRAFFIC_NOTE_ATTRIBUTE}]`);
    expect(note()?.getAttribute(WORLD_TRAFFIC_NOTE_ATTRIBUTE)).toBe('traffic_not_loaded');
    expect(note()?.textContent).toMatch(/could not load its traffic/);
    opened!.attach({} as never).dispose();
    expect(tile.attach).toHaveBeenCalledOnce();
    expect(dispose).toHaveBeenCalledOnce();
    expect(note()).toBeNull();
  });
});
