// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import {
  DEFAULT_WORLD_LOOK,
  STYLE_PACK_LIST_PROFILE,
  WORLD_LOOKS,
  addressedWorldLook,
  listedDefault,
  prepareWorldLook,
  worldLookChoice,
} from '../src/world-look.js';

// Relative to web/, where the suite runs.
const PACKS = '../assets/style-packs/packs';
const TEXTURES = new Uint8Array(readFileSync('../assets/textures/manifest.json'));
const ACCESS: Credentials = { baseUrl: 'https://host.test/api', token: 'look-token' };

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

interface Served {
  readonly list: unknown;
  readonly content: Map<string, Uint8Array<ArrayBuffer>>;
}

/**
 * The committed library as a host serves it, built here from the files rather than by the server's
 * code: each manifest is its file without the last newline (the file is its canonical JSON and one
 * newline), each piece its file, all by the SHA-256 of those bytes.
 */
function committedLibrary(): Served {
  const content = new Map<string, Uint8Array<ArrayBuffer>>();
  const packs = readdirSync(PACKS).sort().map((folder) => {
    const file = readFileSync(`${PACKS}/${folder}/manifest.json`);
    const bytes = new Uint8Array(file.subarray(0, file.length - 1));
    const manifest = JSON.parse(new TextDecoder().decode(bytes)) as {
      pack_id: string; version: number; title: string; licence: unknown; files: { path: string }[];
    };
    content.set(sha256(bytes), bytes);
    for (const listed of manifest.files) {
      const piece = new Uint8Array(readFileSync(`${PACKS}/${folder}/${listed.path}`));
      content.set(sha256(piece), piece);
    }
    return { pack_id: manifest.pack_id, version: manifest.version, manifest_sha256: sha256(bytes), title: manifest.title, licence: manifest.licence };
  });
  return { list: { profile: STYLE_PACK_LIST_PROFILE, packs }, content };
}

/** A fetch answering as the host does, recording each request's address and credential. */
function host(served: Served, asked: { url: string; authorization: string | null }[]) {
  return vi.fn(async (input: string, init?: RequestInit): Promise<Response> => {
    const authorization = new Headers(init?.headers).get('Authorization');
    asked.push({ url: input, authorization });
    const path = input.slice(ACCESS.baseUrl.length);
    if (path === '/world/style-packs') return new Response(JSON.stringify(served.list), { status: 200 });
    const digest = /^\/world\/style-packs\/([0-9a-f]{64})$/.exec(path)?.[1];
    const bytes = digest === undefined ? undefined : served.content.get(digest);
    if (bytes === undefined) return new Response('{"code":"unknown_reference"}', { status: 404 });
    return new Response(bytes, { status: 200 });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the look a generated world opens in', () => {
  const bound = { packId: 'exulanica.toon-town', version: 1, manifestSha256: 'a'.repeat(64) };

  it('is the pack the address names from the closed list, the tile look for today, or none', () => {
    expect(addressedWorldLook('?look=cozy')).toBe('exulanica.cozy-town');
    expect(addressedWorldLook('?look=toon')).toBe('exulanica.toon-town');
    expect(addressedWorldLook('?look=finished')).toBe('exulanica.finished-town');
    expect(addressedWorldLook('?look=today')).toBeNull();
    expect(addressedWorldLook('')).toBeUndefined();
    // A word that is not on the list, or a pack id written out, is not a way to name a pack.
    expect(addressedWorldLook('?look=exulanica.cozy-town')).toBeUndefined();
    expect(addressedWorldLook('?look=constructor')).toBeUndefined();
  });

  it('is the pack the address names, else the pack the world names by its exact manifest, else the default', () => {
    expect(worldLookChoice('?look=finished', bound)).toEqual({ packId: 'exulanica.finished-town', manifestSha256: null, source: 'address' });
    expect(worldLookChoice('?look=today', bound)).toEqual({ packId: null, manifestSha256: null, source: 'address' });
    expect(worldLookChoice('', bound)).toEqual({ packId: 'exulanica.toon-town', manifestSha256: 'a'.repeat(64), source: 'world' });
    expect(worldLookChoice('?look=constructor', null)).toEqual({ packId: DEFAULT_WORLD_LOOK, manifestSha256: null, source: 'default' });
  });

  it('names only packs the committed library holds, the default among them', () => {
    expect(Object.values(WORLD_LOOKS).sort()).toEqual(readdirSync(PACKS).sort());
    expect(readdirSync(PACKS)).toContain(DEFAULT_WORLD_LOOK);
  });
});

describe('the default look', () => {
  const listed = (packId: string, marked?: boolean) => ({
    pack_id: packId, version: 2, manifest_sha256: 'a'.repeat(64), title: packId, description: '', authors: [],
    licence: { id: 'CC0-1.0', attribution: null }, ...(marked === undefined ? {} : { default: marked }),
  });

  it('is the pack the host lists as its default, else the page\'s fallback from a host marking none', () => {
    expect(listedDefault([listed('exulanica.cozy-town', false), listed('exulanica.toon-town', true)])?.pack_id).toBe('exulanica.toon-town');
    expect(listedDefault([listed('exulanica.cozy-town'), listed('exulanica.toon-town')])?.pack_id).toBe(DEFAULT_WORLD_LOOK);
    expect(listedDefault([listed('exulanica.toon-town')])).toBeUndefined();
  });

  it('falls back to the pack the committed library names its default', () => {
    const library = JSON.parse(readFileSync('../assets/style-packs/library.v1.json', 'utf8')) as { default: string };
    expect(library.default).toBe(DEFAULT_WORLD_LOOK);
  });
});

describe('a pack the host serves, prepared for a world', () => {
  it('is read from the list, its manifest and its pieces, each by digest, with the session', async () => {
    const served = committedLibrary();
    const asked: { url: string; authorization: string | null }[] = [];
    vi.stubGlobal('fetch', host(served, asked));
    const prepared = await prepareWorldLook(ACCESS, 'exulanica.cozy-town', TEXTURES, []);
    expect(prepared.packId).toBe('exulanica.cozy-town');
    // Every variant's first file of every module, once each: what the dresser can place.
    const manifest = JSON.parse(readFileSync(`${PACKS}/exulanica.cozy-town/manifest.json`, 'utf8')) as {
      modules: Record<string, { variants: { file: string }[] }>;
    };
    const files = new Set(Object.values(manifest.modules).flatMap((module) => module.variants.map((v) => v.file)));
    expect(prepared.pieces.pieces.size).toBe(files.size);
    expect(asked[0]!.url).toBe(`${ACCESS.baseUrl}/world/style-packs`);
    expect(asked.length).toBe(2 + files.size);
    for (const request of asked) expect(request.authorization).toBe(`Bearer ${ACCESS.token}`);
  });

  it('is read by the very manifest a world names, without the list', async () => {
    const served = committedLibrary();
    const listed = (served.list as { packs: { pack_id: string; manifest_sha256: string }[] }).packs;
    const toon = listed.find((pack) => pack.pack_id === 'exulanica.toon-town')!;
    const asked: { url: string; authorization: string | null }[] = [];
    vi.stubGlobal('fetch', host({ ...served, list: { profile: STYLE_PACK_LIST_PROFILE, packs: [] } }, asked));
    const prepared = await prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [], toon.manifest_sha256);
    expect(prepared.packId).toBe('exulanica.toon-town');
    expect(asked[0]!.url).toBe(`${ACCESS.baseUrl}/world/style-packs/${toon.manifest_sha256}`);
    expect(asked.some((request) => request.url === `${ACCESS.baseUrl}/world/style-packs`)).toBe(false);
  });

  it('is refused when the manifest a world names is not the pack it names', async () => {
    const served = committedLibrary();
    const listed = (served.list as { packs: { pack_id: string; manifest_sha256: string }[] }).packs;
    const cozy = listed.find((pack) => pack.pack_id === 'exulanica.cozy-town')!;
    vi.stubGlobal('fetch', host(served, []));
    await expect(prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [], cozy.manifest_sha256))
      .rejects.toThrow('names exulanica.cozy-town');
  });

  it('is refused when the host does not list it, and nothing more is asked', async () => {
    const asked: { url: string; authorization: string | null }[] = [];
    const served = committedLibrary();
    vi.stubGlobal('fetch', host({ ...served, list: { profile: STYLE_PACK_LIST_PROFILE, packs: [] } }, asked));
    await expect(prepareWorldLook(ACCESS, 'exulanica.cozy-town', TEXTURES, [])).rejects.toThrow('serves no style pack');
    expect(asked.length).toBe(1);
  });

  it('is refused when the list is not the profile the page reads', async () => {
    const served = committedLibrary();
    vi.stubGlobal('fetch', host({ ...served, list: { profile: 'other/v1', packs: [] } }, []));
    await expect(prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [])).rejects.toThrow(STYLE_PACK_LIST_PROFILE);
  });

  it('is refused when a manifest or a piece arrives as other bytes than its digest names', async () => {
    const served = committedLibrary();
    const manifestDigest = (served.list as { packs: { pack_id: string; manifest_sha256: string }[] }).packs
      .find((pack) => pack.pack_id === 'exulanica.toon-town')!.manifest_sha256;
    const tampered = new Map(served.content);
    const manifest = tampered.get(manifestDigest)!.slice();
    const at = manifest.length - 2;
    manifest[at] = manifest[at]! ^ 1;
    tampered.set(manifestDigest, manifest);
    vi.stubGlobal('fetch', host({ ...served, content: tampered }, []));
    await expect(prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [])).rejects.toThrow('not the ones its digest names');

    const pieceFile = readFileSync(`${PACKS}/exulanica.toon-town/pieces/tree.glb`);
    const pieceDigest = sha256(new Uint8Array(pieceFile));
    const swapped = new Map(served.content);
    swapped.set(pieceDigest, new Uint8Array(readFileSync(`${PACKS}/exulanica.toon-town/pieces/fence.glb`)));
    vi.stubGlobal('fetch', host({ ...served, content: swapped }, []));
    await expect(prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [])).rejects.toThrow('not the ones its digest names');
  });
});
