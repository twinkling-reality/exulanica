// @vitest-environment happy-dom
/**
 * A town made on its land, in the page: its land section is read through the world's version and
 * held to its entity tag, its world and the digest its entry names; every chunk and the backdrop it
 * names are held to their digests; land the server is still making is asked for again after the
 * seconds each 503 states, until `LAND_WAIT_MS` is spent; the land is drawn round the town's tiles
 * and never under them, and taken away with them; the look's flat plane beyond the town is not
 * drawn; and the town's people stand on the ground its tiles walk, and on the land where they walk
 * none. A saved town whose entry names its land is opened with it, in every look it is redrawn in.
 *
 * The land is synthetic, in the served shape: two chunks on land that rises 40 per mille to the
 * north and steps up 500 mm east of 8 m, and a backdrop with the sea to the south.
 */
import { createHash } from 'node:crypto';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import { isGeneratedWorld, loadGeneratedWorld } from '../src/composition/generated-world.js';
import { askForTownLand, furnitureOnLand, LAND_WAIT_MS, loadTownLand, rememberTownLand, townGround, withoutEdge, withTownLand, type TownLand } from '../src/composition/town-land.js';
import { townFurniture } from '../src/composition/town-furniture.js';
import type { GeneratedGround, SavedWorldEntry } from '../src/world-entry-api.js';

// The tile runtime, the texture library and the pack reader are replaced, as in
// generated-world.test.ts, so a test sees what the page hands the runtime; the tile look states a
// flat plane beyond the tiles, so a test sees whether it is drawn.
const loadGeneratedTile = vi.hoisted(() => vi.fn());
const TILE_LOOK_V1 = vi.hoisted(() => ({ id: 'exulanica.generated-tile-look', version: 1, edge: { dropM: 0.4 } }));
// A bench whose record stands its base 17,065 mm above the town's datum.
const BENCH = vi.hoisted(() => ({ identity: 'bench', eastMm: 60_000, southMm: -60_000, facing: [1, 0] as [number, number], parts: [], zMm: 17_065 }));
vi.mock('@exulanica/atlas-react/generated-tile', () => ({
  loadGeneratedTile, TILE_LOOK_V1, streetFurnitureOf: () => [BENCH], doorsOf: () => [], sightBlockersOf: () => [],
}));
vi.mock('../src/texture-library.js', () => ({
  committedTextureLibrary: async () => ({ textureManifest: new Uint8Array(), textureSet: async () => new Uint8Array() }),
}));
vi.mock('../src/world-look.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/world-look.js')>()),
  listedStylePacks: async () => [],
  prepareWorldLook: async () => {
    throw new Error('this test reads no pack');
  },
}));
// The land is read as the page reads it; what draws it round the tiles is replaced, so a test sees
// which chunks the tiles cover and when the land is taken away.
const drawnRound = vi.hoisted(() => ({ calls: [] as { covered: (x: number, y: number) => boolean; disposed: boolean }[] }));
vi.mock('@exulanica/atlas-react/generated-site', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-react/generated-site')>()),
  attachLandRound: (_host: unknown, _land: unknown, covered: (x: number, y: number) => boolean) => {
    const call = { covered, disposed: false };
    drawnRound.calls.push(call);
    return { drawn: { ground: [] }, dispose: () => { call.disposed = true; } };
  },
}));
vi.mock('@exulanica/atlas-core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@exulanica/atlas-core')>()),
  parseTextureSetManifest: () => ({ sets: [] }),
}));

const access = { baseUrl: 'https://exulanica.test', token: 'private' };
const WORLD = 'world:generated:town-on-land';
const entry = { entryId: 'entry', worldId: WORLD, authoredVersionId: 'version' } as unknown as SavedWorldEntry;
const sha256 = (text: string): string => createHash('sha256').update(new TextEncoder().encode(text)).digest('hex');

/** JSON with every object's keys sorted and no blank space, written here apart from the page's reader. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, one]) => `${JSON.stringify(key)}:${canonical(one)}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

const lattice = (east: number, north: number): number => 6000 + (40 * north) / 1000 + (east >= 8000 ? 500 : 0);
function chunk(chunkX: number, chunkY: number): string {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(lattice(chunkX * 128_000 + i * 1000, chunkY * 128_000 + j * 1000));
  return canonical({ profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height });
}
function backdrop(): string {
  const xs = [-400_000, -128_000, 0, 128_000, 400_000], ys = [-400_000, 0, 128_000, 400_000];
  return canonical({
    profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, 0, 128_000, 128_000], x_mm: xs, y_mm: ys,
    height_mm: ys.flatMap((y) => xs.map((x) => (y < 0 ? -20_000 : y > 128_000 ? 150_000 : lattice(x, y)))),
    water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
  });
}
const LAND_SHA256 = 'a'.repeat(64);
const DOCUMENTS = new Map([['land/chunks/-1/0', chunk(-1, 0)], ['land/chunks/0/0', chunk(0, 0)], ['land/backdrop', backdrop()]]);

/** The town's land section as the server states it, changed by `more`. */
function section(more: { world?: string; profile?: string; landSha256?: string } = {}): string {
  return canonical({
    profile: more.profile ?? 'exulanica.town-land/v1',
    world_id: more.world ?? WORLD,
    receipt_sha256: 'b'.repeat(64),
    land: {
      land_sha256: more.landSha256 ?? LAND_SHA256,
      chunk_mm: 128_000,
      chunks: [{ chunk: [-1, 0], sha256: sha256(chunk(-1, 0)) }, { chunk: [0, 0], sha256: sha256(chunk(0, 0)) }],
      backdrop_sha256: sha256(backdrop()),
      water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
    },
  });
}

/** A host serving the town's land; `tag` states another entity tag for that path. */
function host(body = section(), tag: { path: string; etag: string } | null = null) {
  const asked: string[] = [];
  const fetched = vi.fn(async (input: string): Promise<Response> => {
    const at = /^\/world\/versions\/version\/(land[^?]*)\?world_id=world%3Agenerated%3Atown-on-land$/.exec(input.slice(access.baseUrl.length));
    if (at === null) return new Response('{}', { status: 404 });
    asked.push(at[1]!);
    const served = at[1] === 'land' ? body : DOCUMENTS.get(at[1]!)!;
    const etag = tag !== null && tag.path === at[1] ? tag.etag : sha256(served);
    return new Response(served, { status: 200, headers: { ETag: `"${etag}"` } });
  });
  return { fetched, asked };
}

/** A host whose land section answers 503 with `retry` as its Retry-After (none when null) to its first `refusals` asks; when each was asked. */
function making(refusals: number, retry: string | null = '2') {
  const served = host();
  const asks: number[] = [];
  const fetched = vi.fn(async (input: string): Promise<Response> => {
    if (input.includes('/land?')) {
      asks.push(Date.now());
      if (asks.length <= refusals) {
        return new Response('{"code":"kind_work_overran"}', { status: 503, headers: retry === null ? {} : { 'Retry-After': retry } });
      }
    }
    return served.fetched(input);
  });
  return { fetched, asks };
}

// The page loads what reads and draws land only when a town on land opens; loading it the first
// time takes seconds, so it is loaded once here, apart from what any test holds to its time.
beforeAll(async () => {
  await Promise.all([import('@exulanica/atlas-react/generated-site'), import('@exulanica/atlas-react/playcanvas'), import('../src/land-surfaces.js')]);
}, 60_000);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  rememberTownLand('entry', null);
});

describe("a town on its land's land, read", () => {
  it('reads its section and every chunk and the backdrop it names, each held to its digest', async () => {
    const { fetched, asked } = host();
    vi.stubGlobal('fetch', fetched);
    const town = await loadTownLand(access, entry, LAND_SHA256);
    expect(asked.sort()).toEqual(['land', 'land/backdrop', 'land/chunks/-1/0', 'land/chunks/0/0']);
    expect(town.land.chunks.map((one) => [one.chunkX, one.chunkY])).toEqual([[-1, 0], [0, 0]]);
    expect(town.land.groundMm(4000, 8000)).toBe(6320);
    expect(town.land.section.water.map((body) => body.kind)).toEqual(['sea']);
  });

  it.each([
    ['a section its tag does not name', host(section(), { path: 'land', etag: 'c'.repeat(64) }), 'a document its section does not name'],
    ['a chunk its section does not name', host(section(), { path: 'land/chunks/0/0', etag: 'c'.repeat(64) }), 'a document its section does not name'],
    ["another world's section", host(section({ world: 'world:generated:other' })), 'for another world'],
    ['a section of another profile', host(section({ profile: 'exulanica.site-drawing/v5' })), 'is not stated as exulanica.town-land/v1'],
    ['land other than its entry names', host(section({ landSha256: 'd'.repeat(64) })), 'not the land its entry names'],
  ])('refuses %s', async (_case, served, words) => {
    vi.stubGlobal('fetch', served.fetched);
    await expect(loadTownLand(access, entry, LAND_SHA256)).rejects.toThrow(words);
  });

  it('reads land the server is still making, asking again after the seconds each 503 states', async () => {
    vi.useFakeTimers();
    const { fetched, asks } = making(2);
    vi.stubGlobal('fetch', fetched);
    const start = Date.now();
    const town = loadTownLand(access, entry, LAND_SHA256);
    await vi.advanceTimersByTimeAsync(LAND_WAIT_MS);
    expect((await town).land.groundMm(4000, 8000)).toBe(6320);
    expect(asks.map((at) => at - start)).toEqual([0, 2000, 4000]);
  });

  it('refuses land still being made once the wait is spent, having asked until then', async () => {
    vi.useFakeTimers();
    const { fetched, asks } = making(Number.POSITIVE_INFINITY);
    vi.stubGlobal('fetch', fetched);
    const start = Date.now();
    const refused = expect(loadTownLand(access, entry, LAND_SHA256)).rejects.toThrow('HTTP 503');
    await vi.advanceTimersByTimeAsync(LAND_WAIT_MS);
    await refused;
    expect(asks.at(-1)! - start).toBeGreaterThanOrEqual(LAND_WAIT_MS - 2000);
  });

  it('asks once for the land of a town whose tiles still bake, reading nothing, and nothing for a town on level ground', async () => {
    const onLand = { ...entry, generatedGround: { landSha256: LAND_SHA256 } } as unknown as SavedWorldEntry;
    const level = { ...entry, generatedGround: {} } as unknown as SavedWorldEntry;
    const asked = vi.fn(async (_input: string, _init?: RequestInit) => new Response('{}', { status: 503, headers: { 'Retry-After': '2' } }));
    vi.stubGlobal('fetch', asked);
    askForTownLand(access, level);
    expect(asked).not.toHaveBeenCalled();
    askForTownLand(access, onLand);
    expect(asked.mock.calls.map(([input]) => input)).toEqual([`${access.baseUrl}/world/versions/version/land?world_id=world%3Agenerated%3Atown-on-land`]);
    expect(asked.mock.calls[0]![1]!.headers).toMatchObject({ Authorization: 'Bearer private' });
    // A host that cannot be reached is not the opening's to say: the ask throws nothing.
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    expect(() => askForTownLand(access, onLand)).not.toThrow();
    await new Promise((done) => { setTimeout(done, 0); });
  });

  it.each([
    ['a 503 that states no Retry-After', making(1, null).fetched, 503],
    ['a 404', vi.fn(async () => new Response('{}', { status: 404, headers: { 'Retry-After': '2' } })), 404],
  ])('refuses at once %s', async (_case, fetched, status) => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', fetched);
    await expect(loadTownLand(access, entry, LAND_SHA256)).rejects.toThrow(`HTTP ${status}`);
  });
});

describe("a town on its land's land, drawn", () => {
  it("is drawn round the town's tiles whenever they are attached, never under them, and taken away first", () => {
    const order: string[] = [];
    let covered: ((x: number, y: number) => boolean) | null = null;
    const town = { land: {}, draw: (_host: unknown, under: (x: number, y: number) => boolean) => {
      covered = under;
      order.push('land drawn');
      return { dispose: () => order.push('land taken away') };
    } } as unknown as TownLand;
    const attachment = { metrics: {}, dispose: () => order.push('tiles taken away') } as unknown as GeneratedTileAttachment;
    const tile = { attach: () => { order.push('tiles drawn'); return attachment; } } as unknown as LoadedGeneratedTile;
    const drawn = withTownLand(tile, town, [{ tileX: 0, tileY: 0 }, { tileX: 1, tileY: 0 }]).attach({} as GeneratedTileHost);
    expect([covered!(0, 0), covered!(1, 0), covered!(-1, 0), covered!(0, 1)]).toEqual([true, true, false, false]);
    drawn.dispose();
    expect(order).toEqual(['tiles drawn', 'land drawn', 'land taken away', 'tiles taken away']);
  });

  it("dresses the town's own unbuilt ground in what its land wears, and gives the tiles theirs back first", () => {
    const order: string[] = [];
    const soil = { name: 'tree pit soil' }, paving = { name: 'footway paving' }, land = { name: 'the land round the town' };
    // Two tiles' batches drawn in the terrain's texture set, one in the footway's.
    const batch = (name: string, material: object) => ({ name, render: { meshInstances: [{ material }] } });
    const batches = [batch('generated-tile:soil', soil), batch('generated-tile:soil', soil), batch('generated-tile:paving', paving)];
    const host = { environmentRoot: { find: (test: (node: { name: string }) => boolean) => batches.filter(test) } } as unknown as GeneratedTileHost;
    const surface = (role: string, textureSetId: string) => ({ role, textureSetId });
    const ranges = [
      { state: 'drawn', surfaces: [surface('terrain', 'soil'), surface('terrain', 'soil')] },
      { state: 'drawn', surfaces: [surface('footway', 'paving'), surface('tree_pit', 'soil')] },
      { state: 'halo' },
    ];
    const tile = { ranges, attach: () => ({ metrics: {}, dispose: () => order.push('tiles taken away') }) } as unknown as LoadedGeneratedTile;
    const worn = (): object[] => batches.map((one) => one.render.meshInstances[0]!.material);
    const town = { land: {}, draw: () => ({
      ground: land,
      dispose: () => order.push(`land taken away, the tiles wearing ${worn().map((m) => (m as { name: string }).name).join(', ')}`),
    }) } as unknown as TownLand;
    const drawn = withTownLand(tile, town, [{ tileX: 0, tileY: 0 }]).attach(host);
    expect(worn()).toEqual([land, land, paving]);
    drawn.dispose();
    expect(worn()).toEqual([soil, soil, paving]);
    expect(order).toEqual(['land taken away, the tiles wearing tree pit soil, tree pit soil, footway paving', 'tiles taken away']);
    // Where the land round the town drew no near chunk, the tiles wear their own.
    const bare = { land: {}, draw: () => ({ ground: null, dispose: () => {} }) } as unknown as TownLand;
    withTownLand(tile, bare, [{ tileX: 0, tileY: 0 }]).attach(host);
    expect(worn()).toEqual([soil, soil, paving]);
  });

  it("stands its street furniture at each piece's own height, its people's region being at the land's datum", () => {
    const stated = [{ identity: 'bench', zMm: 17_065 }, { identity: 'sign' }];
    expect(furnitureOnLand(stated)).toEqual([{ identity: 'bench', zMm: 17_065, baseMm: 17_065 }, { identity: 'sign' }]);
  });

  it("draws no flat plane beyond a town whose land is its edge, and leaves a look with none as it is", () => {
    const edged = { id: 'look', edge: { ground: [0.5, 0.5, 0.5], dropM: 0.4, reachM: 3000 } };
    expect(withoutEdge(edged)).toEqual({ id: 'look', edge: null });
    expect(edged.edge).not.toBeNull();
    const plain = { id: 'tile look' };
    expect(withoutEdge(plain)).toBe(plain);
  });
});

describe("a town on its land's people", () => {
  it('stand on the ground its tiles walk, on its land where they walk none, and at the arrival for any other town', async () => {
    vi.stubGlobal('fetch', host().fetched);
    const town = await loadTownLand(access, entry, LAND_SHA256);
    const walked = { surface: { sample: (east: number) => (east < 2 ? { height: 9.25 } : null) } };
    expect(townGround('entry', walked)).toBeUndefined();
    rememberTownLand('entry', town);
    const ground = townGround('entry', walked)!;
    expect(ground(1, -8)).toBe(9.25);
    expect(ground(4, -8)).toBeCloseTo(6.32, 6);
    expect(townGround('another entry', walked)).toBeUndefined();
  });
});

describe('a saved town on its land, opened', () => {
  it('reads its land beside its tiles and draws it round them, in every look it is redrawn in, with no flat plane', async () => {
    const id = '11111111-0000-4000-8000-000000000000';
    const ground: GeneratedGround = {
      recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'region:generated',
      arrivalMm: [64000, 6500, -64000], arrivalFacingMm: [0, 3000], specification: null, values: null,
      tiles: [{ tileX: 0, tileY: 0, tileInputsDigest: '0'.repeat(64), bakedTileId: id, state: 'baked' }],
      landSha256: LAND_SHA256,
    };
    const land = host();
    const bytes = new Uint8Array([1, 2, 3]);
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      if (input.includes(`/tiles/${id}/bytes`)) {
        return new Response(new Blob([bytes.slice().buffer]), { headers: { ETag: `"${createHash('sha256').update(bytes).digest('hex')}"` } });
      }
      return land.fetched(input);
    }));
    const looks: unknown[] = [];
    const attached: string[] = [];
    const plain = {
      navigationWorld: { eyeHeight: 1.6, surface: { sample: () => ({ height: 6.5 }) } },
      attach: () => {
        attached.push('tiles');
        return { metrics: {}, dispose: () => undefined };
      },
      inLook(look: unknown) {
        looks.push(look);
        return { ...plain, look };
      },
    };
    loadGeneratedTile.mockReset();
    loadGeneratedTile.mockResolvedValue(plain);
    const loaded = await loadGeneratedWorld(access, { ...entry, generatedGround: ground } as SavedWorldEntry, '?look=today');
    if (!isGeneratedWorld(loaded)) throw new Error('not loaded');
    expect(land.asked.sort()).toEqual(['land', 'land/backdrop', 'land/chunks/-1/0', 'land/chunks/0/0']);
    /** Which of the land's chunks the tiles cover, as drawn round them, and taken away with them. */
    const coveredIn = (tile: LoadedGeneratedTile): boolean[] => {
      drawnRound.calls.length = 0;
      tile.attach({} as GeneratedTileHost).dispose();
      expect(drawnRound.calls).toHaveLength(1);
      expect(drawnRound.calls[0]!.disposed).toBe(true);
      return [[-1, 0], [0, 0]].map(([x, y]) => drawnRound.calls[0]!.covered(x!, y!));
    };
    // The town's tile covers chunk (0, 0): the land is drawn round it, never under it.
    expect(coveredIn(loaded.tile)).toEqual([false, true]);
    // Redrawn in another look, the same land is drawn round it, and the look draws no flat plane.
    const again = await loaded.relook({ packId: null, manifestSha256: null, source: 'redraw' });
    expect(looks).toEqual([{ ...TILE_LOOK_V1, edge: null }]);
    expect(coveredIn(again.tile)).toEqual([false, true]);
    expect(attached).toEqual(['tiles', 'tiles']);
    expect(land.asked).toHaveLength(4);
    // Its people stand on the ground its tiles walk, and sit on its benches at the benches' heights.
    expect(townGround('entry', plain.navigationWorld)!(1, -1)).toBe(6.5);
    expect(townFurniture('entry').map((piece) => piece.baseMm)).toEqual([17_065]);
  });
});
