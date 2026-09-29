import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isGeneratedWorld, loadGeneratedWorld } from '../src/composition/generated-world.js';
import type { GeneratedGround, GeneratedTile, SavedWorldEntry } from '../src/world-entry-api.js';

// The tile runtime and the texture library are replaced, so a test sees what the page hands the
// runtime: which containers, in which roles, read from where.
const loadGeneratedTile = vi.hoisted(() => vi.fn());
vi.mock('@exulanica/atlas-react/generated-tile', () => ({ loadGeneratedTile }));
vi.mock('../src/texture-library.js', () => ({
  committedTextureLibrary: async () => ({
    textureManifest: new Uint8Array(),
    textureSet: async () => new Uint8Array(),
  }),
}));
vi.mock('@exulanica/atlas-core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-core')>()),
  parseTextureSetManifest: () => ({ sets: [] }),
}));

const access = { baseUrl: 'https://exulanica.test', token: 'private' };

const tile = (x: number, state: GeneratedTile['state']): GeneratedTile => ({
  tileX: x,
  tileY: 0,
  tileInputsDigest: String(x).repeat(64),
  bakedTileId: state === 'baking' ? null : `${String(x + 1).repeat(8)}-0000-4000-8000-000000000000`,
  state,
});

const ground = (tiles: readonly GeneratedTile[]): GeneratedGround => ({
  recipeKey: 'wide_town',
  recipeLabel: 'A wide town',
  regionId: 'region:generated',
  arrivalMm: [128000, 105, -58750],
  arrivalFacingMm: [0, 3000],
  tiles,
});

const entry = (tiles: readonly GeneratedTile[]) => ({
  entryId: 'entry',
  worldId: 'world:generated:wide',
  authoredVersionId: 'version',
  generatedGround: ground(tiles),
}) as unknown as SavedWorldEntry;

/** A route that serves each tile's bytes with the digest it names, or another digest if told. */
function tileRoute(bytes: Readonly<Record<string, Uint8Array>>, stated: (id: string) => string | null = () => null) {
  const read: string[] = [];
  const fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input));
    read.push(`${url.pathname}?${url.searchParams.toString()}`);
    const id = url.pathname.split('/')[5]!;
    const body = bytes[id]!;
    const etag = stated(id) ?? createHash('sha256').update(body).digest('hex');
    return new Response(new Blob([body.slice().buffer]), { headers: { ETag: `"${etag}"` } });
  });
  return { fetch, read };
}

describe('a saved generated world of several tiles', () => {
  beforeEach(() => {
    loadGeneratedTile.mockReset();
    loadGeneratedTile.mockResolvedValue({ navigationWorld: { eyeHeight: 1.6 } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('draws nothing and reads no tile while any of its tiles is still baking or failed', async () => {
    const { fetch } = tileRoute({});
    vi.stubGlobal('fetch', fetch);
    const cases: readonly [readonly GeneratedTile[], 'baking' | 'failed'][] = [
      [[tile(0, 'baked'), tile(1, 'baking')], 'baking'],
      [[tile(0, 'baking'), tile(1, 'baked')], 'baking'],
      [[tile(0, 'baked'), tile(1, 'failed')], 'failed'],
    ];
    for (const [tiles, waiting] of cases) {
      const loaded = await loadGeneratedWorld(access, entry(tiles));
      expect(isGeneratedWorld(loaded)).toBe(false);
      expect(loaded).toEqual({ waiting, ground: ground(tiles) });
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(loadGeneratedTile).not.toHaveBeenCalled();
  });

  it('reads every tile through the world once all are baked, and draws and stands on each', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const [west, east] = tiles.map((one) => one.bakedTileId!);
    const bytes = { [west!]: new Uint8Array([1, 2, 3]), [east!]: new Uint8Array([4, 5, 6]) };
    const { fetch, read } = tileRoute(bytes);
    vi.stubGlobal('fetch', fetch);
    const loaded = await loadGeneratedWorld(access, entry(tiles));
    expect(isGeneratedWorld(loaded)).toBe(true);
    expect(read).toEqual([west, east].map((id) =>
      `/world/versions/version/tiles/${id}/bytes?world_id=world%3Agenerated%3Awide`));
    // The runtime draws the first container as the tile and every other as a neighbour, whose
    // ground it composes into the walk (`GeneratedTileSources.neighbours`).
    expect(loadGeneratedTile).toHaveBeenCalledTimes(1);
    const [sources] = loadGeneratedTile.mock.calls[0]!;
    expect(sources.name).toBe(west);
    expect(sources.bytes).toEqual(bytes[west!]);
    expect(sources.neighbours).toEqual([{ name: east, bytes: bytes[east!] }]);
    // A person opens at the served arrival, which may lie on any of the tiles.
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    expect(loaded.tile.start).toMatchObject({ x: 128, z: -58.75 });
  });

  it('refuses a tile whose bytes are not the ones the route named', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const [west, east] = tiles.map((one) => one.bakedTileId!);
    const { fetch } = tileRoute(
      { [west!]: new Uint8Array([1]), [east!]: new Uint8Array([2]) },
      (id) => (id === east ? 'e'.repeat(64) : null),
    );
    vi.stubGlobal('fetch', fetch);
    await expect(loadGeneratedWorld(access, entry(tiles))).rejects.toThrow('not the ones the route named');
    expect(loadGeneratedTile).not.toHaveBeenCalled();
  });
});
