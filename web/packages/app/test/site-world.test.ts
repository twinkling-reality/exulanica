// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GeneratedTileHost } from '@exulanica/atlas-react/generated-tile';
import type { GeneratedSiteMount } from '@exulanica/atlas-react/generated-site';
import { DRAWING_ASKS, loadSiteWorld, openSiteWorld, switchableSite, type SiteWorld } from '../src/composition/site-world.js';
import { redrawWorldLook } from '../src/composition/world-look-redraw.js';
import { siteSightRings } from '../src/composition/sight.js';
import { GROUND_BORDERS } from '../src/ground-borders.js';
import { LAND_SURFACES } from '../src/land-surfaces.js';
import { ROOF_FORMS } from '../src/roof-forms.js';
import { SITE_INTERIOR } from '../src/site-interior.js';
import { RENDER_BUDGET } from '../src/render-budget.js';
import { SITE_SCENERY } from '../src/site-scenery.js';
import { SURFACE_MATERIALS } from '../src/surface-materials.js';
import { SURFACE_PATTERNS } from '../src/surface-patterns.js';
import { STYLE_PACK_LIST_PROFILE, type WorldLookChoice } from '../src/world-look.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

// The site's mount is wrapped, so a test sees the light and dresser the page hands it; the texture
// library is the committed manifest, read from its file.
const mounts = vi.hoisted(() => ({ asked: [] as { look?: { id: string }; dress?: unknown; materials?: unknown; roofForms?: unknown }[] }));
vi.mock('@exulanica/atlas-react/generated-site', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@exulanica/atlas-react/generated-site')>();
  return {
    ...actual,
    siteMount: (...asked: Parameters<typeof actual.siteMount>) => {
      mounts.asked.push(asked[1]);
      return actual.siteMount(...asked);
    },
  };
});
// The pack's dresser is wrapped the same way, so a test sees the catalogs the page hands it.
const dressers = vi.hoisted(() => ({ asked: [] as { materials?: unknown; patterns?: unknown; borders?: unknown }[] }));
vi.mock('@exulanica/atlas-react/style-pack', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@exulanica/atlas-react/style-pack')>();
  return {
    ...actual,
    packSiteDresser: (...asked: Parameters<typeof actual.packSiteDresser>) => {
      dressers.asked.push(asked[0]);
      return actual.packSiteDresser(...asked);
    },
  };
});
vi.mock('../src/texture-library.js', async () => {
  const { readFileSync: read } = await import('node:fs');
  return {
    committedTextureLibrary: async () => ({
      textureManifest: new Uint8Array(read('../assets/textures/manifest.json')),
      textureSet: async () => new Uint8Array(),
    }),
  };
});

/**
 * A site world's drawing is made in the server's kind worker. While the worker is busy the route
 * answers 503 `kind_work_overran` or `kind_work_busy` with a `Retry-After`; the page waits that
 * long and asks again, a bounded number of times, and asks no more for any other answer.
 */

const entry = {
  entryId: 'entry-farm', worldId: 'world:generated:farm', authoredVersionId: 'version',
  generatedSite: {
    kind: 'fixture_farm', kindVersion: 1, kindLabel: 'A test farm', regionId: 'region:generated',
    arrivalMm: [48000, 0, -4000], arrivalFacingMm: [0, -1],
  },
} as unknown as SavedWorldEntry;
const access = { baseUrl: 'https://exulanica.test', token: 't' };

function refused(status: number, code: string, retryAfter?: string): Response {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (retryAfter !== undefined) headers['Retry-After'] = retryAfter;
  return new Response(JSON.stringify({ code, detail: 'words' }), { status, headers });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('loadSiteWorld', () => {
  it('waits out a drawing still being made and asks again', async () => {
    const answers = [refused(503, 'kind_work_overran', '1'), refused(503, 'kind_work_busy', '3'), refused(404, 'unknown_reference')];
    const fetched = vi.fn(async () => answers.shift() ?? refused(404, 'unknown_reference'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    const told = vi.fn();
    await expect(loadSiteWorld(access, entry, told, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 404');
    expect(fetched).toHaveBeenCalledTimes(3);
    expect(waits).toEqual([1_000, 3_000]);
    expect(told).toHaveBeenCalledTimes(2);
  });

  it('asks a bounded number of times, and never longer apart than ten seconds', async () => {
    const fetched = vi.fn(async () => refused(503, 'kind_work_busy', '600'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    await expect(loadSiteWorld(access, entry, () => {}, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 503');
    expect(fetched).toHaveBeenCalledTimes(DRAWING_ASKS);
    expect(waits).toEqual(Array(DRAWING_ASKS - 1).fill(10_000));
  });

  it('does not ask again when the worker could not take the work at all', async () => {
    const fetched = vi.fn(async () => refused(503, 'kind_work_unavailable', '5'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    await expect(loadSiteWorld(access, entry, () => {}, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 503');
    expect(fetched).toHaveBeenCalledTimes(1);
    expect(waits).toEqual([]);
  });
});

// Relative to web/, where the suite runs.
const PACKS = '../assets/style-packs/packs';
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

/** JSON with every object's keys sorted and no blank space: the drawing's canonical bytes, written here apart from the page's reader. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, one]) => `${JSON.stringify(key)}:${canonical(one)}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

/** A yard of tilled ground, one plastered wall and a crate a metre high, in the served shape. */
const DRAWING = canonical({
  profile: 'exulanica.site-drawing/v1',
  world_id: entry.worldId,
  receipt_sha256: 'a'.repeat(64),
  kind: { kind: 'fixture_farm', version: 1, label: 'A test farm' },
  extent: { widthMm: 10_000, depthMm: 10_000, enclosure: 'open' },
  arrival: { positionMm: [5000, 2000, 0], facingMm: [0, 1] },
  slots: [
    { identity: 'ground', part: 'ground', label: 'Ground', lookRole: 'ground.tilled_soil', positionMm: [5000, 5000, 0], yawQuarterTurns: 0, boxMm: [10_000, 10_000, 0], front: '+y', fit: 'surface', primitive: 'plane' },
    { identity: 'wall', part: 'wall', label: 'Wall', lookRole: 'wall.plaster', positionMm: [5000, 8000, 0], yawQuarterTurns: 0, boxMm: [4000, 200, 2400], front: '+y', fit: 'surface', primitive: 'box' },
    { identity: 'crate', part: 'crate', label: 'Crate', lookRole: 'fixture.crate', positionMm: [2000, 3000, 0], yawQuarterTurns: 0, boxMm: [800, 800, 1000], front: '+y', fit: 'surface', primitive: 'box' },
  ],
  walk: { floorMm: [0, 0, 10_000, 10_000], blockersMm: [], keepOutMm: [] },
  seats: [],
});

/**
 * The committed library as a host serves it, built here from the files: each manifest is its file
 * without the last newline, each piece its file, all by the SHA-256 of those bytes; the cozy town is
 * listed as the default.
 */
function committedLibrary(): { list: unknown; content: Map<string, Uint8Array<ArrayBuffer>> } {
  const content = new Map<string, Uint8Array<ArrayBuffer>>();
  const packs = readdirSync(PACKS).sort().map((folder) => {
    const file = readFileSync(`${PACKS}/${folder}/manifest.json`);
    const bytes = new Uint8Array(file.subarray(0, file.length - 1));
    const manifest = JSON.parse(new TextDecoder().decode(bytes)) as { pack_id: string; version: number; title: string; licence: unknown; files: { path: string }[] };
    content.set(sha256(bytes), bytes);
    for (const listed of manifest.files) {
      const piece = new Uint8Array(readFileSync(`${PACKS}/${folder}/${listed.path}`));
      content.set(sha256(piece), piece);
    }
    return {
      pack_id: manifest.pack_id, version: manifest.version, manifest_sha256: sha256(bytes), title: manifest.title,
      description: '', authors: [], licence: manifest.licence, default: manifest.pack_id === 'exulanica.cozy-town',
    };
  });
  return { list: { profile: STYLE_PACK_LIST_PROFILE, packs }, content };
}

/** A host serving a drawing (the yard's unless another is given) and, unless `listStatus` says otherwise, the committed packs. */
function host(listStatus = 200, served: string = DRAWING) {
  const library = committedLibrary();
  const asked: string[] = [];
  const fetched = vi.fn(async (input: string): Promise<Response> => {
    const path = input.slice(access.baseUrl.length);
    asked.push(path);
    if (path.startsWith('/world/versions/')) {
      return new Response(served, { status: 200, headers: { ETag: `"${sha256(new TextEncoder().encode(served))}"` } });
    }
    if (path === '/world/style-packs') return new Response(JSON.stringify(library.list), { status: listStatus });
    const digest = /^\/world\/style-packs\/([0-9a-f]{64})$/.exec(path)?.[1];
    const bytes = digest === undefined ? undefined : library.content.get(digest);
    return bytes === undefined ? refused(404, 'unknown_reference') : new Response(bytes, { status: 200 });
  });
  return { fetched, asked };
}

describe('the look a site world is drawn in', () => {
  it('is the pack the host lists as its default, whose light lights the site and whose dresser dresses it', async () => {
    vi.stubGlobal('fetch', host().fetched);
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '', null);
    expect(world?.look).toEqual({ pack: 'exulanica.cozy-town', source: 'default', drawn: true, reason: null });
    const options = mounts.asked.at(-1)!;
    expect(options.look?.id).toBe('exulanica.render-look');
    expect(typeof options.dress).toBe('function');
    // The surface material catalog the page bundles goes with it, so a leaf the pack does not state is read by its words.
    expect(options.materials).toBe(SURFACE_MATERIALS);
    expect(SURFACE_MATERIALS.materials.some((material) => material.key === 'sand')).toBe(true);
    // And the roof forms a roof is shaped by, through its material.
    expect(options.roofForms).toBe(ROOF_FORMS);
    // And the scenery catalog, so what stands beyond a place is drawn in the pack's look too.
    expect((options as { scenery?: unknown }).scenery).toBe(SITE_SCENERY);
    // And the interior catalog, so an indoor place has its ceiling and light in the pack's look too.
    expect((options as { interior?: unknown }).interior).toBe(SITE_INTERIOR);
    // And the render budget, so the pack's look is drawn within the caps of the site's form.
    expect((options as { renderBudget?: unknown }).renderBudget).toBe(RENDER_BUDGET);
    // The dresser reads a leaf by the same materials, patterns each and breaks the borders between grounds.
    expect(dressers.asked.at(-1)).toMatchObject({ materials: SURFACE_MATERIALS, patterns: SURFACE_PATTERNS, borders: GROUND_BORDERS });
    expect(GROUND_BORDERS.byMaterial.get('lake')?.lies).toBe('under');
    expect(ROOF_FORMS.byMaterial.get('canvas')?.ridge?.eaves).toBe('ground');
  });

  it('is the workspace\'s own look on the library pack it is drawn on, where the world\'s appearance names one', async () => {
    // A look of the workspace's own: one generated piece (the cozy town's tree file standing in for
    // one) in place of the cozy town's plants, served by the workspace's route and by no library route.
    const library = committedLibrary();
    const cozy = (library.list as { packs: { pack_id: string; version: number; manifest_sha256: string }[] }).packs.find((pack) => pack.pack_id === 'exulanica.cozy-town')!;
    const piece = new Uint8Array(readFileSync(`${PACKS}/exulanica.cozy-town/pieces/tree.glb`));
    const path = `generated/${sha256(piece)}.glb`;
    const manifest = {
      profile: 'exulanica.style-pack/v1', pack_id: 'generated.cozy-town', version: 1, title: 'Cozy town, with new pieces',
      description: 'Cozy town with generated pieces for 1 part in place of its own.', tags: [], origin: 'generated',
      provenance: { kind: 'generated', receipts: ['f'.repeat(64)] }, licence: { id: 'CC0-1.0', attribution: null },
      authors: ['TRELLIS-image-large'], preview: null,
      base: { pack_id: cozy.pack_id, version: cozy.version, manifest_sha256: cozy.manifest_sha256 },
      light: null, shading: null, edge: null, palette: { encoding: 'exulanica.srgb8-linear16/v1', swatches: [] }, surfaces: {},
      modules: { 'plant.default': { variants: [{ file: path, lod1: null, size_mm: [3000, 3000, 5500], stretch_mm: [null, null, null] }] } },
      files: [{ path, sha256: sha256(piece), bytes: piece.length, media_type: 'model/gltf-binary' }],
    };
    const digest = sha256(new TextEncoder().encode(canonical(manifest)));
    const { fetched, asked } = host();
    vi.stubGlobal('fetch', vi.fn(async (input: string): Promise<Response> => {
      const asking = input.slice(access.baseUrl.length);
      if (asking.startsWith('/workspace-style-packs/')) asked.push(asking);
      if (asking === `/workspace-style-packs/${digest}`) {
        return new Response(JSON.stringify({ manifest_sha256: digest, pack_id: 'generated.cozy-town', ready: true, manifest }), { status: 200 });
      }
      if (asking === `/workspace-style-packs/${digest}/files/${sha256(piece)}`) return new Response(piece, { status: 200 });
      return fetched(input);
    }));
    const base = { packId: cozy.pack_id, version: cozy.version, manifestSha256: cozy.manifest_sha256 };
    const bound = { packId: 'generated.cozy-town', version: 1, manifestSha256: digest, own: { base, wearable: true } };
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '', bound);
    // Drawn in it, not in the tile look with a reason why not.
    expect(world?.look).toEqual({ pack: 'generated.cozy-town', source: 'world', drawn: true, reason: null });
    expect(typeof mounts.asked.at(-1)!.dress).toBe('function');
    // Its own manifest from the workspace, its base from the library; its digest is never asked of the library.
    expect(asked).toContain(`/workspace-style-packs/${digest}`);
    expect(asked).toContain(`/world/style-packs/${cozy.manifest_sha256}`);
    expect(asked).not.toContain(`/world/style-packs/${digest}`);
    // Changed to another look and back while mounted, it is read the same way.
    const again = await world!.relook({ packId: 'generated.cozy-town', manifestSha256: digest, source: 'world', ownBase: base });
    expect(again.look).toEqual({ pack: 'generated.cozy-town', source: 'world', drawn: true, reason: null });
  });

  it('is the tile look in the engine\'s own colours when the pack cannot be read, saying why', async () => {
    vi.stubGlobal('fetch', host(503).fetched);
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '', null);
    expect(world?.look).toEqual({ pack: 'exulanica.cozy-town', source: 'default', drawn: false, reason: 'The style pack list unavailable: HTTP 503' });
    // With no pack the engine's own colours are still read from the catalog, leaf by leaf.
    expect(mounts.asked.at(-1)).toEqual({ seated: expect.any(Function), servedBytes: new TextEncoder().encode(DRAWING).byteLength, materials: SURFACE_MATERIALS, roofForms: ROOF_FORMS, scenery: SITE_SCENERY, interior: SITE_INTERIOR, renderBudget: RENDER_BUDGET });
  });

  it('is the tile look, with no pack read, when the address asks for today\'s look', async () => {
    const { fetched, asked } = host();
    vi.stubGlobal('fetch', fetched);
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '?look=today', null);
    expect(world?.look).toEqual({ pack: null, source: 'address', drawn: false, reason: null });
    expect(asked.filter((path) => path.startsWith('/world/style-packs'))).toEqual([]);
  });
});

describe('what stands in a sight line in a site world', () => {
  it('is handed over once when the site opens: the boxes its drawing draws across the eye height it is walked at', async () => {
    const { fetched } = host();
    vi.stubGlobal('fetch', fetched);
    const standing = vi.fn();
    const shell = document.createElement('div');
    const mount = await openSiteWorld({ shell } as never, access, entry, null, standing);
    expect(mount).not.toBeNull();
    // The yard's one wall, 4 m long and 20 cm thick about (5000, 8000) north, 2.4 m high: east 3000 to
    // 7000, south -8100 to -7900. The ground under it is a plane and the crate is lower than the eye
    // a person walks the yard at: neither is part of the plan.
    expect(standing.mock.calls).toEqual([[[[[3000, -8100], [7000, -8100], [7000, -7900], [3000, -7900]]]]]);
    // The same yard on a forest's floor has trees beyond it (the scenery catalog names them for that
    // ground). They are scenery and no part of the place: what stands in a sight line is the same wall
    // and nothing more, so no tree hides a person or stops a click.
    const wooded = DRAWING.replace('ground.tilled_soil', 'ground.forest_floor');
    expect(wooded).not.toBe(DRAWING);
    vi.stubGlobal('fetch', host(200, wooded).fetched);
    const inAWood = vi.fn();
    const forestMount = await openSiteWorld({ shell } as never, access, entry, null, inAWood);
    expect(forestMount).not.toBeNull();
    expect(mounts.asked.at(-1)).toMatchObject({ scenery: SITE_SCENERY });
    expect(inAWood.mock.calls).toEqual(standing.mock.calls);
    // A site that cannot be read hands nothing over (the page says why in words and warns the console).
    vi.stubGlobal('fetch', vi.fn(async () => refused(404, 'unknown_reference')));
    const warned = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const none = vi.fn();
    expect(await openSiteWorld({ shell } as never, access, entry, null, none)).toBeNull();
    expect(none).not.toHaveBeenCalled();
    expect(warned).toHaveBeenCalledTimes(1);
    warned.mockRestore();
  });
});

describe('redrawing an open site in another pack', () => {
  it('takes the old look down before the new one goes up on the same host, and states it', async () => {
    const log: string[] = [];
    const mount = (name: string) => ({
      attach() {
        log.push(`attach ${name}`);
        return { metrics: { lookId: name }, animating: false, dispose: () => log.push(`take down ${name}`) };
      },
    }) as unknown as GeneratedSiteMount;
    const world: SiteWorld = {
      mount: mount('first'),
      look: { pack: 'exulanica.cozy-town', source: 'default', drawn: true, reason: null },
      async relook(choice: WorldLookChoice) {
        return { mount: mount(choice.packId ?? 'tile look'), look: { pack: choice.packId, source: choice.source, drawn: true, reason: null } };
      },
    };
    const stated: unknown[] = [];
    const mounted = switchableSite(world, (look) => stated.push(look), document.createElement('div'));
    const attachment = mounted.attach({} as GeneratedTileHost);
    const done = await redrawWorldLook({ packId: 'exulanica.toon-town', version: 2, manifestSha256: 'b'.repeat(64) });
    expect(done).toMatchObject({ pack: 'exulanica.toon-town', drawn: true, reason: null });
    expect(log).toEqual(['attach first', 'take down first', 'attach exulanica.toon-town']);
    expect(stated).toEqual([{ pack: 'exulanica.toon-town', source: 'redraw', drawn: true, reason: null }]);
    attachment.dispose();
    expect(log.at(-1)).toBe('take down exulanica.toon-town');
  });
});

/**
 * A site made on land (`exulanica.site-drawing/v5`): the synthetic yard on a slope the atlas-react
 * tests read (`fixtures/site-land.v5.json`), its two chunks and backdrop rebuilt from the same
 * formula, each served by the digest its drawing names.
 */
const LAND_DRAWING = canonical(JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')));
const landEntry = { ...entry, worldId: 'world:generated:land-fixture' } as unknown as SavedWorldEntry;
const lattice = (east: number, north: number): number => 6000 + (40 * north) / 1000 + (east >= 8000 ? 500 : 0);
function landChunk(chunkX: number, chunkY: number): string {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(lattice(chunkX * 128_000 + i * 1000, chunkY * 128_000 + j * 1000));
  return canonical({ profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height });
}
function landBackdrop(): string {
  const xs = [-400_000, -128_000, 0, 128_000, 400_000], ys = [-400_000, 0, 128_000, 400_000];
  return canonical({
    profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, 0, 128_000, 128_000], x_mm: xs, y_mm: ys,
    height_mm: ys.flatMap((y) => xs.map((x) => (y < 0 ? -20_000 : y > 128_000 ? 150_000 : lattice(x, y)))),
    water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
  });
}

/** A host serving the yard on a slope and its land; `tampered` serves that path's document changed. */
function landHost(tampered: string | null = null) {
  const level = host(200, LAND_DRAWING);
  const documents = new Map([['land/chunks/-1/0', landChunk(-1, 0)], ['land/chunks/0/0', landChunk(0, 0)], ['land/backdrop', landBackdrop()]]);
  const fetched = vi.fn(async (input: string): Promise<Response> => {
    const at = /^\/world\/versions\/version\/(land\/[^?]+)\?world_id=world%3Agenerated%3Aland-fixture$/.exec(input.slice(access.baseUrl.length));
    if (at === null) return level.fetched(input);
    level.asked.push(input.slice(access.baseUrl.length));
    const body = documents.get(at[1]!);
    if (body === undefined) return refused(404, 'land_chunk_unavailable');
    const etag = `"${sha256(new TextEncoder().encode(body))}"`;
    return new Response(at[1] === tampered ? body.replace('6000', '6001') : body, { status: 200, headers: { ETag: etag } });
  });
  return { fetched, asked: level.asked };
}

describe('a site made on land', () => {
  it('reads every chunk and the backdrop its drawing names, by digest, and mounts the site on them in every look', async () => {
    const { fetched, asked } = landHost();
    vi.stubGlobal('fetch', fetched);
    const world = (await loadSiteWorld(access, landEntry, () => {}, async () => {}, '', null))!;
    const land = world.mount.land!;
    expect(land.chunks.map((chunk) => [chunk.chunkX, chunk.chunkY])).toEqual([[-1, 0], [0, 0]]);
    expect(land.groundMm(4000, 8000)).toBe(6320);
    expect((mounts.asked.at(-1) as { land?: unknown }).land).toBe(land);
    // And the land's own surfaces, so its sand, planting, rock and far woods are drawn.
    expect((mounts.asked.at(-1) as { landSurfaces?: unknown }).landSurfaces).toBe(LAND_SURFACES);
    expect(LAND_SURFACES.bands.map((band) => band.key)).toContain('rock');
    expect(asked.filter((path) => path.includes('/land/')).sort()).toEqual([
      '/world/versions/version/land/backdrop?world_id=world%3Agenerated%3Aland-fixture',
      '/world/versions/version/land/chunks/-1/0?world_id=world%3Agenerated%3Aland-fixture',
      '/world/versions/version/land/chunks/0/0?world_id=world%3Agenerated%3Aland-fixture',
    ]);
    // Redrawn in another look on the same land, read once.
    const before = asked.length;
    const again = await world.relook({ packId: null, source: 'address' } as unknown as WorldLookChoice);
    expect(again.mount.land).toBe(land);
    expect(asked.slice(before).some((path) => path.includes('/land/'))).toBe(false);
  });

  it.each(['land/chunks/0/0', 'land/backdrop'])('is not drawn when %s is not the document its drawing names', async (path) => {
    vi.stubGlobal('fetch', landHost(path).fetched);
    await expect(loadSiteWorld(access, landEntry, () => {}, async () => {}, '', null)).rejects.toThrow('is the document its digest names');
  });

  it('is not drawn when its land cannot be read', async () => {
    const { fetched } = landHost();
    vi.stubGlobal('fetch', vi.fn(async (input: string) => (input.includes('/land/backdrop') ? refused(404, 'land_unavailable') : fetched(input))));
    await expect(loadSiteWorld(access, landEntry, () => {}, async () => {}, '', null)).rejects.toThrow("land could not be read: HTTP 404");
  });

  it('puts what stands across the eye in a sight line above the land it stands on', async () => {
    vi.stubGlobal('fetch', landHost().fetched);
    const world = (await loadSiteWorld(access, landEntry, () => {}, async () => {}, '', null))!;
    const drawing = world.mount.drawing as Parameters<typeof siteSightRings>[0];
    // The fence stands 1.2 m on land 7 m up: across a 1.1 m eye above the land, under it above the datum.
    expect(siteSightRings(drawing, 1100, world.mount.land!.groundMm)).toHaveLength(1);
    expect(siteSightRings(drawing, 1100)).toHaveLength(0);
  });
});

describe('a site on level ground', () => {
  it('asks for no land and mounts with none', async () => {
    const { fetched, asked } = host();
    vi.stubGlobal('fetch', fetched);
    const world = (await loadSiteWorld(access, entry, () => {}, async () => {}, '', null))!;
    expect(world.mount.land).toBeUndefined();
    expect('land' in mounts.asked.at(-1)!).toBe(false);
    expect('landSurfaces' in mounts.asked.at(-1)!).toBe(false);
    expect(asked.some((path) => path.includes('/land/'))).toBe(false);
  });
});
