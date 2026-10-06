// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import {
  DEFAULT_WORLD_LOOK,
  STYLE_PACK_LIST_PROFILE,
  WORLD_LOOKS,
  chosenWorldLook,
  prepareWorldLook,
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
  it('is the pack the address names from the closed list, the tile look for today, else the default', () => {
    expect(chosenWorldLook('?look=cozy')).toBe('exulanica.cozy-town');
    expect(chosenWorldLook('?look=toon')).toBe('exulanica.toon-town');
    expect(chosenWorldLook('?look=finished')).toBe('exulanica.finished-town');
    expect(chosenWorldLook('?look=today')).toBeNull();
    expect(chosenWorldLook('')).toBe(DEFAULT_WORLD_LOOK);
    // A word that is not on the list, or a pack id written out, is not a way to name a pack.
    expect(chosenWorldLook('?look=exulanica.cozy-town')).toBe(DEFAULT_WORLD_LOOK);
    expect(chosenWorldLook('?look=constructor')).toBe(DEFAULT_WORLD_LOOK);
  });

  it('names only packs the committed library holds, the default among them', () => {
    expect(Object.values(WORLD_LOOKS).sort()).toEqual(readdirSync(PACKS).sort());
    expect(readdirSync(PACKS)).toContain(DEFAULT_WORLD_LOOK);
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
