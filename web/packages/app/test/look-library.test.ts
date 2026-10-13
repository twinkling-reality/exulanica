// @vitest-environment happy-dom
// The host's looks as the page reads them, and what a world is drawn in now, matched by digest.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import type { ListedStylePack } from '../src/world-look.js';

const listed = vi.hoisted(() => ({ packs: [] as ListedStylePack[], fetched: [] as string[], settings: null as unknown, settingsFail: false, ownPacks: [] as ListedStylePack[] }));
vi.mock('../src/world-look.js', async (original) => ({
  ...await original<typeof import('../src/world-look.js')>(),
  listedStylePacks: async () => listed.packs,
  listedWorkspaceStylePacks: async () => listed.ownPacks,
  listedSettings: async () => {
    if (listed.settingsFail) throw new Error('the list could not be read');
    return listed.settings;
  },
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
  listed.settings = null;
  listed.settingsFail = false;
  listed.ownPacks = [];
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

describe('the parts a setting is chosen from', () => {
  const SETTINGS = { version: 1, axes: [{ key: 'sky', title: 'Hour and sky' }], parts: [{ axis: 'sky', key: 'dusk', title: 'Dusk', description: 'Evening.' }] };

  it('are the host\'s, none from a host that lists none, and never the reason the looks cannot be read', async () => {
    expect((await readLookLibrary(ACCESS)).settings).toBeNull();
    listed.settings = SETTINGS;
    expect((await readLookLibrary(ACCESS)).settings).toEqual(SETTINGS);
    listed.settingsFail = true;
    const library = await readLookLibrary(ACCESS);
    expect(library.settings).toBeNull();
    expect(library.options).toHaveLength(2);
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

 it('offers an admitted standalone workspace look and preserves its authority for redraw and apply', async () => {
  listed.ownPacks = [{ ...TOON, pack_id: 'original.garden', manifest_sha256: sha('9'), source: 'workspace', ownBase: null }];
  const library = await readLookLibrary(ACCESS);
  const binding = library.binding(library.options.find(option => option.packId === 'original.garden')!.choiceId!);
  expect(binding).toEqual({ ...bound('original.garden', 1, sha('9')), own: { base: null, wearable: true } });
  expect(await library.now(binding)).toEqual({ packId: 'workspace:original.garden:1:'+sha('9'), how: {} });
  expect(library.defaultId).toBe(COZY.pack_id);
 });

 it('keeps library and workspace choices with the same pack id separate by source and exact manifest', async () => {
  listed.packs=[{...COZY,source:'library'},TOON];
  listed.ownPacks=[{...COZY,source:'workspace',manifest_sha256:sha('9'),earlier_versions:[{version:2,manifest_sha256:sha('8'),preview_sha256:null,preview_media_type:null}],ownBase:null,default:false}];
  const library=await readLookLibrary(ACCESS);
  const choices=library.options.filter(option=>option.packId===COZY.pack_id);
  expect(choices).toHaveLength(2);
  expect(library.binding(COZY.pack_id)).toBeNull();
  expect(library.binding(choices[1]!.choiceId!)).toMatchObject({manifestSha256:sha('9'),own:{base:null,wearable:true}});
  expect(await library.now({...bound(COZY.pack_id,2,sha('8')),own:{base:null,wearable:true}})).toMatchObject({packId:choices[1]!.choiceId,how:{earlier:{packId:choices[1]!.choiceId,version:2}}});
  expect(await library.now(bound(COZY.pack_id,3,sha('c')))).toEqual({packId:choices[0]!.choiceId,how:{}});
 });

 it('keeps a workspace choice in its own namespace even if identical bytes were promoted to the library', async () => {
  listed.packs=[{...COZY,source:'library'},TOON];
  listed.ownPacks=[{...COZY,source:'workspace',ownBase:null,default:false}];
  const library=await readLookLibrary(ACCESS);
  const choice=library.options.find(option=>option.choiceId?.startsWith('workspace:'))!;
  expect(await library.now({...bound(COZY.pack_id,COZY.version,COZY.manifest_sha256),own:{base:null,wearable:true}})).toEqual({packId:choice.choiceId,how:{}});
 });
