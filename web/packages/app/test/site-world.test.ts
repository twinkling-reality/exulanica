// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GeneratedTileHost } from '@exulanica/atlas-react/generated-tile';
import type { GeneratedSiteMount } from '@exulanica/atlas-react/generated-site';
import { DRAWING_ASKS, loadSiteWorld, switchableSite, type SiteWorld } from '../src/composition/site-world.js';
import { redrawWorldLook } from '../src/composition/world-look-redraw.js';
import { SURFACE_MATERIALS } from '../src/surface-materials.js';
import { STYLE_PACK_LIST_PROFILE, type WorldLookChoice } from '../src/world-look.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

// The site's mount is wrapped, so a test sees the light and dresser the page hands it; the texture
// library is the committed manifest, read from its file.
const mounts = vi.hoisted(() => ({ asked: [] as { look?: { id: string }; dress?: unknown; materials?: unknown }[] }));
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

/** A yard of tilled ground and one plastered wall, in the served shape. */
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

/** A host serving the drawing and, unless `listStatus` says otherwise, the committed packs. */
function host(listStatus = 200) {
  const library = committedLibrary();
  const asked: string[] = [];
  const fetched = vi.fn(async (input: string): Promise<Response> => {
    const path = input.slice(access.baseUrl.length);
    asked.push(path);
    if (path.startsWith('/world/versions/')) {
      return new Response(DRAWING, { status: 200, headers: { ETag: `"${sha256(new TextEncoder().encode(DRAWING))}"` } });
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
  });

  it('is the tile look in the engine\'s own colours when the pack cannot be read, saying why', async () => {
    vi.stubGlobal('fetch', host(503).fetched);
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '', null);
    expect(world?.look).toEqual({ pack: 'exulanica.cozy-town', source: 'default', drawn: false, reason: 'The style pack list unavailable: HTTP 503' });
    // With no pack the engine's own colours are still read from the catalog, leaf by leaf.
    expect(mounts.asked.at(-1)).toEqual({ servedBytes: new TextEncoder().encode(DRAWING).byteLength, materials: SURFACE_MATERIALS });
  });

  it('is the tile look, with no pack read, when the address asks for today\'s look', async () => {
    const { fetched, asked } = host();
    vi.stubGlobal('fetch', fetched);
    const world = await loadSiteWorld(access, entry, () => {}, async () => {}, '?look=today', null);
    expect(world?.look).toEqual({ pack: null, source: 'address', drawn: false, reason: null });
    expect(asked.filter((path) => path.startsWith('/world/style-packs'))).toEqual([]);
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
