// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { canonicalJson } from '@exulanica/atlas-core';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import {
  DEFAULT_WORLD_LOOK,
  STYLE_PACK_LIST_PROFILE,
  WORLD_LOOKS,
  addressedWorldLook,
  listedDefault,
  listedVersion,
  prepareWorldLook,
  worldLookChoice,
  type ListedStylePack,
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

/** An earlier version of a pack as the host serves it, built here from its published folder. */
function publishedVersion(packId: string, version: number): { digest: string; content: Map<string, Uint8Array<ArrayBuffer>> } {
  const folder = `${PACKS}/../published/${packId}/${version}`;
  const file = readFileSync(`${folder}/manifest.json`);
  const bytes = new Uint8Array(file.subarray(0, file.length - 1));
  const manifest = JSON.parse(new TextDecoder().decode(bytes)) as { files: { path: string }[] };
  const content = new Map<string, Uint8Array<ArrayBuffer>>([[sha256(bytes), bytes]]);
  for (const listed of manifest.files) {
    const piece = new Uint8Array(readFileSync(`${folder}/${listed.path}`));
    content.set(sha256(piece), piece);
  }
  return { digest: sha256(bytes), content };
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

  it('is the world\'s own look drawn on its base while it may be worn, else that base, else the default', () => {
    const base = { packId: 'exulanica.cozy-town', version: 3, manifestSha256: 'b'.repeat(64) };
    const own = { packId: 'generated.cozy-town', version: 2, manifestSha256: 'c'.repeat(64) };
    expect(worldLookChoice('', { ...own, own: { base, wearable: true } }))
      .toEqual({ packId: 'generated.cozy-town', manifestSha256: 'c'.repeat(64), source: 'world', ownBase: base });
    expect(worldLookChoice('', { ...own, own: { base, wearable: false } }))
      .toEqual({ packId: 'exulanica.cozy-town', manifestSha256: 'b'.repeat(64), source: 'world' });
    expect(worldLookChoice('', { ...own, own: { base: null, wearable: false } }))
      .toEqual({ packId: DEFAULT_WORLD_LOOK, manifestSha256: null, source: 'default' });
    // The address still wins, as for every world.
    expect(worldLookChoice('?look=toon', { ...own, own: { base, wearable: true } }))
      .toEqual({ packId: 'exulanica.toon-town', manifestSha256: null, source: 'address' });
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

  it('is the earlier version a world was given, read by its very manifest, the first written before previews', async () => {
    const served = committedLibrary();
    for (const version of [1, 2]) {
      const earlier = publishedVersion('exulanica.toon-town', version);
      const asked: { url: string; authorization: string | null }[] = [];
      vi.stubGlobal('fetch', host({ list: served.list, content: new Map([...served.content, ...earlier.content]) }, asked));
      const prepared = await prepareWorldLook(ACCESS, 'exulanica.toon-town', TEXTURES, [], earlier.digest);
      expect(prepared.packId).toBe('exulanica.toon-town');
      expect(prepared.pack.chain.map((manifest) => manifest.version)).toEqual([version]);
      expect(asked[0]!.url).toBe(`${ACCESS.baseUrl}/world/style-packs/${earlier.digest}`);
    }
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

/**
 * A look of the workspace's own made of one generated piece on the committed cozy town, as the
 * generation worker's builder writes one: the piece stands in for the town's trees. The piece is the
 * cozy town's own tree file, so its colours are the base's.
 */
function ownLook(served: Served): { digest: string; view: unknown; piece: Uint8Array<ArrayBuffer>; base: { packId: string; version: number; manifestSha256: string } } {
  const cozy = (served.list as { packs: { pack_id: string; version: number; manifest_sha256: string }[] }).packs
    .find((pack) => pack.pack_id === 'exulanica.cozy-town')!;
  const piece = new Uint8Array(readFileSync(`${PACKS}/exulanica.cozy-town/pieces/tree.glb`));
  const path = `generated/${sha256(piece)}.glb`;
  const manifest = {
    profile: 'exulanica.style-pack/v1',
    pack_id: 'generated.cozy-town',
    version: 1,
    title: 'Cozy town, with new pieces',
    description: 'Cozy town with generated pieces for 1 part in place of its own.',
    tags: [],
    origin: 'generated',
    provenance: { kind: 'generated', receipts: ['f'.repeat(64)] },
    licence: { id: 'CC0-1.0', attribution: null },
    authors: ['TRELLIS-image-large'],
    preview: null,
    base: { pack_id: cozy.pack_id, version: cozy.version, manifest_sha256: cozy.manifest_sha256 },
    light: null,
    shading: null,
    edge: null,
    palette: { encoding: 'exulanica.srgb8-linear16/v1', swatches: [] },
    surfaces: {},
    modules: { 'plant.default': { variants: [{ file: path, lod1: null, size_mm: [3000, 3000, 5500], stretch_mm: [null, null, null] }] } },
    files: [{ path, sha256: sha256(piece), bytes: piece.length, media_type: 'model/gltf-binary' }],
  };
  const digest = sha256(new TextEncoder().encode(canonicalJson(manifest)));
  return {
    digest,
    view: { manifest_sha256: digest, pack_id: 'generated.cozy-town', ready: true, manifest },
    piece,
    base: { packId: cozy.pack_id, version: cozy.version, manifestSha256: cozy.manifest_sha256 },
  };
}

/** A host serving the committed library and one version of the workspace's own pack. */
function hostWithOwn(served: Served, own: ReturnType<typeof ownLook>, asked: { url: string; authorization: string | null }[]) {
  const library = host(served, asked);
  return vi.fn(async (input: string, init?: RequestInit): Promise<Response> => {
    const path = input.slice(ACCESS.baseUrl.length);
    if (path === `/workspace-style-packs/${own.digest}`) {
      asked.push({ url: input, authorization: new Headers(init?.headers).get('Authorization') });
      return new Response(JSON.stringify(own.view), { status: 200 });
    }
    if (path === `/workspace-style-packs/${own.digest}/files/${sha256(own.piece)}`) {
      asked.push({ url: input, authorization: new Headers(init?.headers).get('Authorization') });
      return new Response(own.piece, { status: 200 });
    }
    if (path.startsWith('/workspace-style-packs/')) return new Response('{"code":"unknown_style_pack"}', { status: 404 });
    return library(input, init);
  });
}

describe('a world\'s own look, prepared', () => {
  it('reads its own manifest and pieces from the workspace and its base from the library, as one chain', async () => {
    const served = committedLibrary();
    const own = ownLook(served);
    const asked: { url: string; authorization: string | null }[] = [];
    vi.stubGlobal('fetch', hostWithOwn(served, own, asked));
    const prepared = await prepareWorldLook(ACCESS, 'generated.cozy-town', TEXTURES, [], own.digest, own.base);
    expect(prepared.pack.chain.map((manifest) => manifest.pack_id)).toEqual(['generated.cozy-town', 'exulanica.cozy-town']);
    // The trees are the own look's piece; everything else is the base's.
    expect(prepared.pack.modules['plant.default']!.stated).toBe(0);
    expect(prepared.pack.modules['vehicle.sedan']!.stated).toBe(1);
    expect(prepared.pack.light).not.toBeNull();
    expect(asked.map((request) => request.url)).toContain(`${ACCESS.baseUrl}/workspace-style-packs/${own.digest}/files/${sha256(own.piece)}`);
    expect(asked.map((request) => request.url)).toContain(`${ACCESS.baseUrl}/world/style-packs/${own.base.manifestSha256}`);
    expect(asked.some((request) => request.url === `${ACCESS.baseUrl}/world/style-packs/${sha256(own.piece)}`)).toBe(false);
    for (const request of asked) expect(request.authorization).toBe(`Bearer ${ACCESS.token}`);
  });

  it('is refused when the workspace does not serve it ready, or it is drawn on another base', async () => {
    const served = committedLibrary();
    const own = ownLook(served);
    vi.stubGlobal('fetch', hostWithOwn(served, { ...own, view: { ...(own.view as object), ready: false } }, []));
    await expect(prepareWorldLook(ACCESS, 'generated.cozy-town', TEXTURES, [], own.digest, own.base))
      .rejects.toThrow('not the ready version');
    vi.stubGlobal('fetch', hostWithOwn(served, own, []));
    const toon = (served.list as { packs: { pack_id: string; version: number; manifest_sha256: string }[] }).packs
      .find((pack) => pack.pack_id === 'exulanica.toon-town')!;
    await expect(prepareWorldLook(ACCESS, 'generated.cozy-town', TEXTURES, [], own.digest, {
      packId: toon.pack_id, version: toon.version, manifestSha256: toon.manifest_sha256,
    })).rejects.toThrow('is not drawn on');
  });

  it('is refused when the manifest the workspace states is not the one its digest names', async () => {
    const served = committedLibrary();
    const own = ownLook(served);
    const view = own.view as { manifest: { title: string } };
    const altered = { ...view, manifest: { ...view.manifest, title: 'Another look' } };
    vi.stubGlobal('fetch', hostWithOwn(served, { ...own, view: altered }, []));
    await expect(prepareWorldLook(ACCESS, 'generated.cozy-town', TEXTURES, [], own.digest, own.base))
      .rejects.toThrow('is not the one its digest names');
  });
});

describe('a listed version', () => {
  const pack = (packId: string, version: number, digest: string, earlier: readonly [number, string][]): ListedStylePack => ({
    pack_id: packId, version, manifest_sha256: digest, title: packId, description: '', authors: [],
    licence: { id: 'CC0-1.0', attribution: null },
    earlier_versions: earlier.map(([number, sha]) => ({ version: number, manifest_sha256: sha, preview_sha256: null, preview_media_type: null })),
  });
  const packs = [pack('exulanica.cozy-town', 3, 'c'.repeat(64), [[1, 'a'.repeat(64)], [2, 'b'.repeat(64)]]), pack('exulanica.toon-town', 3, 'f'.repeat(64), [])];

  it('names the pack and version a digest is, current or earlier, and nothing for a digest no pack lists', () => {
    expect(listedVersion(packs, 'c'.repeat(64))).toEqual({ pack: packs[0], version: 3, current: true });
    expect(listedVersion(packs, 'b'.repeat(64))).toEqual({ pack: packs[0], version: 2, current: false });
    expect(listedVersion(packs, 'f'.repeat(64))).toEqual({ pack: packs[1], version: 3, current: true });
    expect(listedVersion(packs, 'e'.repeat(64))).toBeUndefined();
  });
});
