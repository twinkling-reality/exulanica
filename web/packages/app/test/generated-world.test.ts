import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { groundNear, isGeneratedWorld, loadGeneratedWorld } from '../src/composition/generated-world.js';
import { townFurniture } from '../src/composition/town-furniture.js';
import type { GeneratedGround, GeneratedTile, SavedWorldEntry } from '../src/world-entry-api.js';
import { worldDidNotOpen } from '../src/ui/startup-state.js';

// The step back from the kerb a town's first view takes, as the first view's catalog states it.
const BACK_STEP_MM = (JSON.parse(readFileSync(new URL('../../../../assets/catalogs/arrival/town-first-view.v1.json', import.meta.url), 'utf8')) as
  { entries: { key: string; value: number }[] }).entries.find((entry) => entry.key === 'back_step_mm')!.value;

// The tile runtime and the texture library are replaced, so a test sees what the page hands the
// runtime: which containers, in which roles, read from where.
const loadGeneratedTile = vi.hoisted(() => vi.fn());
const TILE_LOOK_V1 = vi.hoisted(() => ({ id: 'exulanica.generated-tile-look', version: 1 }));
// A container's street furniture, as the tile module would read it from the container's records.
const streetFurnitureOf = vi.hoisted(() => vi.fn<(bytes: Uint8Array) => { identity: string }[]>(() => []));
vi.mock('@exulanica/atlas-react/generated-tile', () => ({ loadGeneratedTile, TILE_LOOK_V1, streetFurnitureOf }));
vi.mock('../src/texture-library.js', () => ({
  committedTextureLibrary: async () => ({
    textureManifest: new Uint8Array(),
    textureSet: async () => new Uint8Array(),
  }),
}));
// The host's list and the pack reader are replaced, so a test sees which pack, by which digest, a
// world is asked to be drawn in; the reader refuses, and the world opens in the tile look saying so.
const looks = vi.hoisted(() => ({ listed: [] as unknown[], asked: [] as unknown[][] }));
vi.mock('../src/world-look.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/world-look.js')>()),
  listedStylePacks: async () => looks.listed,
  prepareWorldLook: async (...asked: unknown[]) => {
    looks.asked.push(asked);
    throw new Error('this test reads no pack');
  },
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

const ground = (tiles: readonly GeneratedTile[], arrivalFacingMm: readonly [number, number] = [0, 3000]): GeneratedGround => ({
  recipeKey: 'wide_town',
  recipeLabel: 'A wide town',
  regionId: 'region:generated',
  arrivalMm: [128000, 105, -58750],
  arrivalFacingMm,
  tiles,
  specification: null,
  values: null,
});

const entry = (tiles: readonly GeneratedTile[], arrivalFacingMm?: readonly [number, number]) => ({
  entryId: 'entry',
  worldId: 'world:generated:wide',
  authoredVersionId: 'version',
  generatedGround: ground(tiles, arrivalFacingMm),
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
    loadGeneratedTile.mockResolvedValue({ navigationWorld: { eyeHeight: 1.6, surface: { sample: () => ({ height: 0.105 }) } } });
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

  it('says in words why the world did not open when a recorded tile\'s stored file is missing', async () => {
    // The route's own answer when a tile is recorded and its bytes are not in the store.
    const tiles = [tile(0, 'baked')];
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      code: 'bytes_missing', detail: 'baked tile is recorded and its bytes are not in the store',
    }), { status: 409, headers: { 'content-type': 'application/json' } })));
    const failed = await loadGeneratedWorld(access, entry(tiles), '?look=today').then(() => null, (error: unknown) => error);
    expect(worldDidNotOpen('A market town', failed)).toBe('A market town did not open. Part of its ground is saved, '
      + 'but the stored file that draws it is missing, so it cannot be drawn.');
    expect(loadGeneratedTile).not.toHaveBeenCalled();
  });

  it('reads every tile through the world once all are baked, and draws and stands on each', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const [west, east] = tiles.map((one) => one.bakedTileId!);
    const bytes = { [west!]: new Uint8Array([1, 2, 3]), [east!]: new Uint8Array([4, 5, 6]) };
    const { fetch, read } = tileRoute(bytes);
    vi.stubGlobal('fetch', fetch);
    // In the tile look, so what it reads is the tiles alone; a pack's reads are world-look.test.ts's.
    const loaded = await loadGeneratedWorld(access, entry(tiles), '?look=today');
    expect(isGeneratedWorld(loaded)).toBe(true);
    // Its tiles' bytes (the first view also reads the version's things and what is parked).
    expect(read.filter((url) => url.includes('/tiles/'))).toEqual([west, east].map((id) =>
      `/world/versions/version/tiles/${id}/bytes?world_id=world%3Agenerated%3Awide`));
    // The runtime draws the first container as the tile and every other as a neighbour, whose
    // ground it composes into the walk (`GeneratedTileSources.neighbours`).
    expect(loadGeneratedTile).toHaveBeenCalledTimes(1);
    const [sources] = loadGeneratedTile.mock.calls[0]!;
    expect(sources.name).toBe(west);
    expect(sources.bytes).toEqual(bytes[west!]);
    expect(sources.neighbours).toEqual([{ name: east, bytes: bytes[east!] }]);
    // A person opens one step back from the served arrival, which may lie on any of the tiles: it
    // faces south, so a step back from the kerb is a step north, off the line people walk.
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    expect(loaded.tile.start).toMatchObject({ x: 128, z: -58.75 - BACK_STEP_MM / 1000 });
  });

  it('keeps the town\'s street furniture from every tile, each piece once, for the entry it opened', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const [west, east] = tiles.map((one) => one.bakedTileId!);
    const bytes = { [west!]: new Uint8Array([1, 2, 3]), [east!]: new Uint8Array([4, 5, 6]) };
    vi.stubGlobal('fetch', tileRoute(bytes).fetch);
    streetFurnitureOf.mockClear();
    // The east tile carries a halo copy of the bench at the seam, which the west tile owns.
    streetFurnitureOf.mockImplementation((container) => (container[0] === 1
      ? [{ identity: 'bench-west' }, { identity: 'bench-seam' }]
      : [{ identity: 'bench-seam' }, { identity: 'bench-east' }]));
    try {
      await loadGeneratedWorld(access, entry(tiles), '?look=today');
      expect(streetFurnitureOf.mock.calls.map(([container]) => [...container])).toEqual([[1, 2, 3], [4, 5, 6]]);
      expect(townFurniture('entry').map((item) => item.identity)).toEqual(['bench-west', 'bench-seam', 'bench-east']);
      expect(townFurniture('another entry')).toEqual([]);
      // Records that cannot be read stop no town from opening: it opens with no furniture kept.
      streetFurnitureOf.mockImplementation(() => { throw new Error('not a container'); });
      const opened = await loadGeneratedWorld(access, entry(tiles), '?look=today');
      expect(isGeneratedWorld(opened)).toBe(true);
      expect(townFurniture('entry')).toEqual([]);
    } finally {
      streetFurnitureOf.mockImplementation(() => []);
    }
  });

  it('draws itself in another look from the tiles it loaded, reading and loading nothing again', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const bytes = Object.fromEntries(tiles.map((one, at) => [one.bakedTileId!, new Uint8Array([at + 1])]));
    const { fetch, read } = tileRoute(bytes);
    vi.stubGlobal('fetch', fetch);
    const looks: unknown[] = [];
    const plain = {
      navigationWorld: { eyeHeight: 1.6, surface: { sample: () => ({ height: 0.105 }) } },
      inLook(look: unknown) {
        looks.push(look);
        return { ...plain, look };
      },
    };
    loadGeneratedTile.mockResolvedValue(plain);
    const loaded = await loadGeneratedWorld(access, entry(tiles), '?look=today');
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    const reads = read.length;
    const again = await loaded.relook({ packId: null, manifestSha256: null, source: 'redraw' });
    expect(loadGeneratedTile).toHaveBeenCalledTimes(1);
    expect(read).toHaveLength(reads);
    expect(looks).toEqual([TILE_LOOK_V1]);
    expect(again.tile).toMatchObject({ look: TILE_LOOK_V1, start: loaded.tile.start });
    expect(again.look).toEqual({ pack: null, source: 'redraw', drawn: false, reason: null });
  });

  it('draws a world naming no pack in the pack the host lists as its default, by the digest the list names', async () => {
    const tiles = [tile(0, 'baked')];
    vi.stubGlobal('fetch', tileRoute({ [tiles[0]!.bakedTileId!]: new Uint8Array([1]) }).fetch);
    looks.listed = [
      { pack_id: 'exulanica.cozy-town', manifest_sha256: 'c'.repeat(64), default: false },
      { pack_id: 'exulanica.toon-town', manifest_sha256: 'b'.repeat(64), default: true },
    ];
    looks.asked = [];
    const loaded = await loadGeneratedWorld(access, entry(tiles), '');
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    expect(looks.asked.map((asked) => [asked[1], asked[4]])).toEqual([['exulanica.toon-town', 'b'.repeat(64)]]);
    expect(loaded.look).toEqual({ pack: 'exulanica.toon-town', source: 'default', drawn: false, reason: 'this test reads no pack' });
  });

  it('opens a step back whichever way the served arrival faces', async () => {
    const tiles = [tile(0, 'baked')];
    vi.stubGlobal('fetch', tileRoute({ [tiles[0]!.bakedTileId!]: new Uint8Array([1]) }).fetch);
    // Facing east, a step back from the kerb is a step west, and nothing moves north or south.
    const loaded = await loadGeneratedWorld(access, entry(tiles, [3000, 0]), '?look=today');
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    expect(loaded.tile.start).toMatchObject({ x: 128 - BACK_STEP_MM / 1000, z: -58.75 });
  });

  it('opens beside the served arrival when the drawn ground carves the point itself', async () => {
    const tiles = [tile(0, 'baked'), tile(1, 'baked')];
    const [west, east] = tiles.map((one) => one.bakedTileId!);
    const { fetch } = tileRoute({ [west!]: new Uint8Array([1]), [east!]: new Uint8Array([2]) });
    vi.stubGlobal('fetch', fetch);
    // No ground within 300 mm of the arrival (128,000, -58,750), ground everywhere else.
    loadGeneratedTile.mockResolvedValue({ navigationWorld: { eyeHeight: 1.6, surface: {
      sample: (x: number, z: number) => (Math.hypot(x * 1000 - 128000, z * 1000 + 58750) < 300 ? null : { height: 0.2 }),
    } } });
    const loaded = await loadGeneratedWorld(access, entry(tiles));
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    const { x, y, z } = loaded.tile.start as { x: number; y: number; z: number };
    expect(Math.hypot(x * 1000 - 128000, z * 1000 + 58750)).toBeGreaterThanOrEqual(300);
    // On the nearest drawn ground (within 350 mm of the carve), or the one step back from there.
    expect(Math.hypot(x * 1000 - 128000, z * 1000 + 58750)).toBeLessThanOrEqual(350 + BACK_STEP_MM);
    expect(y).toBeCloseTo(0.2 + 1.6, 9);
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

describe('where a person opens in a generated world', () => {
  it('opens on the served arrival where ground is drawn there, else on the nearest drawn ground', () => {
    // Ground everywhere but a carve 1,150 mm east to west and 2,500 mm north to south round the
    // served point, as a tree pit's carve lay round a three-tile town's arrival.
    const carve = { west: 193556, east: 194706, north: -71084, south: -68584 };
    const surface = {
      sample: (x: number, z: number) => {
        const [east, south] = [x * 1000, z * 1000];
        const inside = east > carve.west && east < carve.east && south > carve.north && south < carve.south;
        return inside ? null : { height: 0.035 };
      },
    };
    expect(groundNear(surface, 100000, -50000, [0, 1])).toEqual({ eastMm: 100000, southMm: -50000, heightM: 0.035 });
    const stand = groundNear(surface, 194126, -70184, [0, 6184])!;
    expect(stand).not.toBeNull();
    expect(surface.sample(stand.eastMm / 1000, stand.southMm / 1000)).not.toBeNull();
    // The nearest ground lies east or west of the point, 580 mm at most, within a ring's step.
    expect(Math.hypot(stand.eastMm - 194126, stand.southMm + 70184)).toBeLessThanOrEqual(650);
    expect(groundNear({ sample: () => null }, 0, 0, [1, 0])).toBeNull();
  });
});
