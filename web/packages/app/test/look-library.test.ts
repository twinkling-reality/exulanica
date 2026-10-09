// @vitest-environment happy-dom
// The host's looks as the page reads them, and what a world is drawn in now, matched by digest.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import type { ListedStylePack } from '../src/world-look.js';

const listed = vi.hoisted(() => ({ packs: [] as ListedStylePack[], fetched: [] as string[] }));
vi.mock('../src/world-look.js', async (original) => ({
  ...await original<typeof import('../src/world-look.js')>(),
  listedStylePacks: async () => listed.packs,
  stylePackContent: async (_access: Credentials, sha: string) => {
    listed.fetched.push(sha);
    return new Uint8Array([1, 2, 3]);
  },
}));
const { UNSERVED_LOOK_WORDS, ownLookWords, readLookLibrary } = await import('../src/composition/look-library.js');

const ACCESS: Credentials = { baseUrl: 'https://host.test/api', token: 'look-token' };
const sha = (c: string): string => c.repeat(64);
const COZY: ListedStylePack = {
  pack_id: 'exulanica.cozy-town', version: 3, manifest_sha256: sha('c'), title: 'Cozy town', description: 'Warm.',
  authors: ['Exulanica'], licence: { id: 'CC0-1.0', attribution: null }, preview_sha256: sha('3'), preview_media_type: 'image/jpeg',
  default: true, changes: 'Shaded roads are grey again.',
  earlier_versions: [
    { version: 1, manifest_sha256: sha('a'), preview_sha256: null, preview_media_type: null },
    { version: 2, manifest_sha256: sha('b'), preview_sha256: sha('2'), preview_media_type: 'image/jpeg' },
  ],
};
const TOON: ListedStylePack = {
  pack_id: 'exulanica.toon-town', version: 1, manifest_sha256: sha('f'), title: 'Toon town', description: 'Bright.',
  authors: [], licence: { id: 'CC0-1.0', attribution: null },
};
const bound = (packId: string, version: number, digest: string) => ({ packId, version, manifestSha256: digest });

beforeEach(() => {
  listed.packs = [COZY, TOON];
  listed.fetched = [];
});

describe('the looks the host serves', () => {
  it('offers each pack at its current version with the host\'s note on what it changed', async () => {
    const library = await readLookLibrary(ACCESS);
    expect(library.options.map((option) => [option.packId, option.version, option.changes])).toEqual([
      ['exulanica.cozy-town', 3, 'Shaded roads are grey again.'], ['exulanica.toon-town', 1, null],
    ]);
    expect(library.binding('exulanica.cozy-town')).toEqual(bound('exulanica.cozy-town', 3, sha('c')));
  });
});

describe('what a world is drawn in now', () => {
  it('is the host\'s default for a world naming none, and the pack its digest names at the current version', async () => {
    const library = await readLookLibrary(ACCESS);
    expect(await library.now(null)).toEqual({ packId: 'exulanica.cozy-town', how: {} });
    expect(await library.now(bound('exulanica.toon-town', 1, sha('f')))).toEqual({ packId: 'exulanica.toon-town', how: {} });
  });

  it('is the earlier version a world keeps, with that version\'s own picture, or none where it has none', async () => {
    const library = await readLookLibrary(ACCESS);
    const second = await library.now(bound('exulanica.cozy-town', 2, sha('b')));
    expect(second.packId).toBe('exulanica.cozy-town');
    expect(second.how.earlier).toMatchObject({ packId: 'exulanica.cozy-town', version: 2 });
    expect(second.how.earlier!.picture).not.toBeNull();
    expect(listed.fetched).toContain(sha('2'));
    const first = await library.now(bound('exulanica.cozy-town', 1, sha('a')));
    expect(first.how.earlier).toEqual({ packId: 'exulanica.cozy-town', version: 1, picture: null });
  });

  it('is no pack, said in words, for a digest the host lists under none, whatever pack id it carries', async () => {
    const library = await readLookLibrary(ACCESS);
    expect(await library.now(bound('exulanica.cozy-town', 9, sha('e')))).toEqual({ packId: null, how: { notice: UNSERVED_LOOK_WORDS } });
  });

  it('is the world\'s own look said by the look it is drawn on, never as plain tiles while it may be worn', async () => {
    const library = await readLookLibrary(ACCESS);
    const base = { packId: COZY.pack_id, version: COZY.version, manifestSha256: COZY.manifest_sha256 };
    const own = (wearable: boolean, on: typeof base | null = base) => ({
      ...bound('generated.cozy-town', 1, sha('d')), own: { base: on, wearable },
    });
    const worn = await library.now(own(true));
    expect(worn).toEqual({ packId: null, how: { notice: ownLookWords(COZY.title, true) } });
    expect(worn.how.notice).toContain(COZY.title);
    expect(worn.how.notice).not.toContain('plain tiles');
    expect(await library.now(own(false))).toEqual({ packId: COZY.pack_id, how: { notice: ownLookWords(COZY.title, false) } });
    expect(await library.now(own(true, null))).toEqual({ packId: null, how: { notice: ownLookWords(null, true) } });
  });
});
