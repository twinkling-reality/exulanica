// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildYourWorlds, onlyUntouchedStarter } from '../src/composition/world-entry.js';
import {
  FIRST_VIEW_WAIT, frameJpeg, holdsWorld, jpegWithoutMetadata, keepFirstViewPicture, mayPutPicture, readServedPictures, worldPicture, type PictureSource,
} from '../src/composition/world-pictures.js';
import type { SavedWorldEntry, SavedWorldEntryPicture } from '../src/world-entry-api.js';

const entry = (overrides: Partial<SavedWorldEntry> = {}): SavedWorldEntry => ({
  entryId: '11111111-1111-4111-8111-111111111111',
  worldId: 'world:generated:one',
  title: 'Saturday market',
  sourceKind: 'generated',
  sourceSnapshotId: '55555555-5555-4555-8555-555555555555',
  sourceSnapshotSha256: 'c'.repeat(64),
  authoredScene: null,
  authoredVersionId: '22222222-2222-4222-8222-222222222222',
  authoredStateSha256: 'a'.repeat(64),
  authoredEditSeq: 0,
  currentAuthoredStateSha256: 'a'.repeat(64),
  currentAuthoredEditSeq: 0,
  styleVersionId: '33333333-3333-4333-8333-333333333333',
  revision: 1,
  availability: 'available',
  unavailableReason: null,
  sourceAttachments: [],
  createdAt: '2026-10-04T17:26:19Z',
  updatedAt: '2026-10-04T17:30:00Z',
  generatedGround: {
    recipeKey: 'market_town', recipeLabel: 'A market town', regionId: 'r',
    arrivalMm: [0, 0, 0], arrivalFacingMm: [1, 0], tiles: [], specification: null, values: null,
  },
  ...overrides,
});

const quiet = entry({
  entryId: '44444444-4444-4444-8444-444444444444', title: 'Quiet corner',
  createdAt: '2026-09-30T08:00:00Z', updatedAt: '2026-09-30T09:00:00Z',
  generatedGround: {
    recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'r',
    arrivalMm: [0, 0, 0], arrivalFacingMm: [1, 0], tiles: [], specification: null, values: null,
  },
});

const starter = (edits = 0) => entry({
  entryId: '66666666-6666-4666-8666-666666666666', title: 'My world', sourceKind: 'authored',
  authoredScene: {} as never, generatedGround: null, currentAuthoredEditSeq: edits, authoredEditSeq: edits,
});

const press = (target: Element, key: string): KeyboardEvent => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
};

const build = (entries: readonly SavedWorldEntry[], extra: Partial<Parameters<typeof buildYourWorlds>[0]> = {}) => {
  const open = vi.fn(async () => undefined);
  const create = vi.fn();
  const handle = buildYourWorlds({ entries, open, adoptLatest: vi.fn(async () => undefined), create, ...extra });
  document.body.replaceChildren(handle.root);
  return { ...handle, open, create };
};

const title = (root: HTMLElement) => root.querySelector('.your-worlds-title')?.textContent;

afterEach(() => {
  document.body.replaceChildren();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('Your worlds', () => {
  it('names the most recently changed world without filler metadata', () => {
    const { root } = build([quiet, entry()]);
    expect(title(root)).toBe('Your worlds');
    expect([...root.querySelectorAll('.your-worlds-card .world-entry-choice-title')].map((n) => n.textContent))
      .toEqual(['Saturday market', 'Quiet corner']);
    expect(root.querySelector('.your-worlds-meta')).toBeNull();
    expect(root.querySelector('.your-worlds-caption')).toBeNull();
  });

  it('chooses with the arrow keys and opens the chosen world with Enter', () => {
    const { root, open } = build([quiet, entry()]);
    (root.querySelector('.your-worlds-card') as HTMLElement).focus();
    press(document.activeElement!, 'ArrowRight');
    expect(root.querySelector('.your-worlds-open')?.getAttribute('aria-label')).toBe('Open Quiet corner');
    press(root, 'Enter');
    expect(open).toHaveBeenCalledWith(quiet);
  });

  it('selects on click and opens on double click', () => {
    const { root, open } = build([quiet, entry()]);
    (root.querySelectorAll('button.world-entry-choice')[1] as HTMLButtonElement).click();
    expect(open).not.toHaveBeenCalled();
    expect(root.querySelector('.your-worlds-open')?.getAttribute('aria-label')).toBe('Open Quiet corner');
    root.querySelectorAll('button.world-entry-choice')[1]!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    expect(open).toHaveBeenCalledWith(quiet);
  });

  it('creates with N, but never while a person types', () => {
    const field = document.createElement('input');
    const personal = document.createElement('section');
    personal.append(field);
    const { root, create } = build([entry()], { personalWorld: { root: personal, refresh: async () => undefined } });
    field.focus();
    const typed = press(field, 'n');
    expect(create).not.toHaveBeenCalled();
    expect(typed.defaultPrevented).toBe(false);
    press(root, 'n');
    expect(create).toHaveBeenCalledOnce();
  });

  it('says why creating is refused and opens nothing', () => {
    const { root, create, setCreate } = build([entry()]);
    setCreate({ state: 'unavailable', words: { happened: 'This workspace already holds as many towns as it may.' } });
    const card = root.querySelector('.your-worlds-create') as HTMLButtonElement;
    expect(card.getAttribute('aria-disabled')).toBe('true');
    card.click();
    expect(create).not.toHaveBeenCalled();
    expect(root.querySelector('.your-worlds-status')?.textContent)
      .toBe('This workspace already holds as many towns as it may.');
  });

  it('offers no Create a world where the server serves no saved worlds to add to', () => {
    const handle = buildYourWorlds({ entries: [entry()], open: vi.fn(), adoptLatest: vi.fn() });
    expect((handle.root.querySelector('.your-worlds-create') as HTMLElement).hidden).toBe(true);
  });

  it('asks a person whose only world is the untouched starter to create one', () => {
    expect(onlyUntouchedStarter([starter()])).toBe(true);
    expect(onlyUntouchedStarter([starter(3)])).toBe(false);
    expect(onlyUntouchedStarter([starter(), entry()])).toBe(false);
    const { root } = build([starter()]);
    expect(title(root)).toBe('Your worlds');
    expect(root.querySelector('.your-worlds-create')).not.toBeNull();
  });

  it('says why a world cannot open when its card is pressed, and opens nothing', () => {
    const gone = entry({ availability: 'unavailable', unavailableReason: 'source_deleted' });
    const { root, open } = build([gone]);
    (root.querySelector('button.world-entry-choice') as HTMLButtonElement).click();
    expect(open).not.toHaveBeenCalled();
    expect(root.querySelector('.your-worlds-status')?.textContent).toContain('source material was deleted');
  });
});

describe('the pictures on Your worlds', () => {
  it('shows a world its own kept frame, else none: never another world\'s, not even one of its recipe', () => {
    expect(worldPicture(entry())).toBeNull();
    expect(worldPicture(quiet)).toBeNull();
    expect(worldPicture(starter())).toBeNull();
    expect(worldPicture(entry({ generatedGround: { ...entry().generatedGround!, recipeKey: 'harbour' } }))).toBeNull();
    window.localStorage.setItem(`exulanica.world-picture.v1.${entry().entryId}`, 'data:image/jpeg;base64,AAAA');
    expect(worldPicture(entry())).toBe('data:image/jpeg;base64,AAAA');
    // Anything else under the key is not a picture and is not shown.
    window.localStorage.setItem(`exulanica.world-picture.v1.${quiet.entryId}`, 'javascript:alert(1)');
    expect(worldPicture(quiet)).toBeNull();
  });
});

describe('the pictures the server keeps', () => {
  const hex = async (bytes: Blob): Promise<string> => [...new Uint8Array(
    await crypto.subtle.digest('SHA-256', await bytes.arrayBuffer()),
  )].map((n) => n.toString(16).padStart(2, '0')).join('');
  const jpeg = (...values: number[]) => new Blob([new Uint8Array(values)], { type: 'image/jpeg' });
  /** Each case its own world: the page holds what it read for as long as it lives. */
  let serial = 0;
  const world = (overrides: Partial<SavedWorldEntry> = {}): SavedWorldEntry => {
    serial += 1;
    return entry({ entryId: `aaaaaaaa-aaaa-4aaa-8aaa-${String(serial).padStart(12, '0')}`, ...overrides });
  };
  const kept = (sha256: string, overrides: Partial<SavedWorldEntryPicture> = {}): SavedWorldEntryPicture => ({
    sha256, mediaType: 'image/jpeg', byteSize: 3, width: 1280, height: 720,
    authoredVersionId: entry().authoredVersionId, authoredStateSha256: entry().authoredStateSha256,
    styleVersionId: entry().styleVersionId, current: true, takenAt: '2026-10-14T20:00:00Z', ...overrides,
  });
  const own = (one: SavedWorldEntry) => window.localStorage.getItem(`exulanica.world-picture.v1.${one.entryId}`);

  it('shows the server\'s picture while it shows the world as it is, read once by its digest', async () => {
    const bytes = jpeg(1, 2, 3);
    const digest = await hex(bytes);
    const server = { picture: vi.fn(async () => bytes) };
    const current = world({ picture: kept(digest) });
    window.localStorage.setItem(`exulanica.world-picture.v1.${current.entryId}`, 'data:image/jpeg;base64,AAAA');
    expect(worldPicture(current)).toBe('data:image/jpeg;base64,AAAA');
    expect(await readServedPictures(server, [current])).toBe(1);
    expect(server.picture).toHaveBeenCalledWith(current.entryId, digest);
    expect(worldPicture(current)).toMatch(/^blob:/);
    expect(await readServedPictures(server, [current])).toBe(0);
    expect(server.picture).toHaveBeenCalledTimes(1);
    // The world changed since: its own picture, then none, until a page puts a new one.
    const changed = { ...current, picture: kept(digest, { current: false }) };
    expect(worldPicture(changed)).toBe('data:image/jpeg;base64,AAAA');
    window.localStorage.clear();
    expect(worldPicture(changed)).toBeNull();
    const unread = world({ picture: kept(digest, { current: false }) });
    expect(await readServedPictures(server, [unread])).toBe(0);
    expect(server.picture).toHaveBeenCalledTimes(1);
  });

  it('never shows bytes that are not the digest the entry states, nor a picture it could not read', async () => {
    const stated = await hex(jpeg(1, 2, 3));
    const other = world({ picture: kept(stated) });
    expect(await readServedPictures({ picture: vi.fn(async () => jpeg(4, 5, 6)) }, [other])).toBe(0);
    expect(worldPicture(other)).toBeNull();
    const failed = world({ picture: kept(stated) });
    expect(await readServedPictures({ picture: vi.fn(async () => { throw new Error('offline'); }) }, [failed])).toBe(0);
    expect(worldPicture(failed)).toBeNull();
  });

  it('draws the cards again with the pictures that arrived', async () => {
    const bytes = jpeg(7, 8, 9);
    const pictured = world({ picture: kept(await hex(bytes)) });
    const bare = world({ generatedGround: { ...entry().generatedGround!, recipeKey: 'harbour' }, picture: kept(await hex(bytes)) });
    const { root, refreshPictures } = build([pictured, bare], { picture: worldPicture });
    const image = (one: SavedWorldEntry) => root.querySelector(`[data-entry-id="${one.entryId}"] .your-worlds-picture img`);
    expect(image(pictured)).toBeNull();
    expect(image(bare)).toBeNull();
    await readServedPictures({ picture: vi.fn(async () => bytes) }, [pictured, bare]);
    refreshPictures();
    expect(image(pictured)?.getAttribute('src')).toMatch(/^blob:/);
    expect(image(bare)?.getAttribute('src')).toMatch(/^blob:/);
  });

  /** A renderer whose next frame is drawn when asked for, onto a canvas `level` paints. */
  const renderer = (level: (index: number) => number = (index) => index % 251): PictureSource => {
    const frames = new Set<() => void>();
    const data = new Uint8ClampedArray(1280 * 720 * 4).map((_, index) => level(index));
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: () => undefined, getImageData: () => ({ data }),
    } as never);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/jpeg;base64,BBBB');
    const canvas = document.createElement('canvas');
    canvas.width = 1600;
    canvas.height = 900;
    return {
      app: {
        on: (_name, handler) => frames.add(handler),
        off: (_name, handler) => frames.delete(handler),
        get renderNextFrame() { return false; },
        set renderNextFrame(_asked: boolean) { queueMicrotask(() => frames.forEach((frame) => frame())); },
        graphicsDevice: { canvas },
      },
    };
  };
  const server = () => ({
    putPicture: vi.fn(async (one: SavedWorldEntry, bytes: Blob) => kept(await hex(bytes), {
      authoredVersionId: one.authoredVersionId, authoredStateSha256: one.authoredStateSha256, styleVersionId: one.styleVersionId,
    })),
  });

  it('keeps a first view here and puts it where the server has none current, once for what it shows', async () => {
    const put = server();
    const first = world();
    const record = await keepFirstViewPicture(renderer(), first, put);
    expect(own(first)).toBe('data:image/jpeg;base64,BBBB');
    expect(put.putPicture).toHaveBeenCalledTimes(1);
    expect(put.putPicture.mock.calls[0]![0]).toBe(first);
    expect(put.putPicture.mock.calls[0]![1].type).toBe('image/jpeg');
    // Shown from what was put, with no read of it.
    expect(worldPicture({ ...first, picture: record })).toMatch(/^blob:/);
    await keepFirstViewPicture(renderer(), first, put);
    expect(put.putPicture).toHaveBeenCalledTimes(1);
    await keepFirstViewPicture(renderer(), { ...first, styleVersionId: '77777777-7777-4777-8777-777777777777' }, put);
    expect(put.putPicture).toHaveBeenCalledTimes(2);
    const pictured = world({ picture: kept('e'.repeat(64)) });
    await keepFirstViewPicture(renderer(), pictured, put);
    expect(own(pictured)).toBe('data:image/jpeg;base64,BBBB');
    expect(put.putPicture).toHaveBeenCalledTimes(2);
    const stale = world({ picture: kept('e'.repeat(64), { current: false }) });
    await keepFirstViewPicture(renderer(), stale, put);
    expect(put.putPicture).toHaveBeenCalledTimes(3);
  });

  it('encodes a frame at once, without waiting on the idle time toBlob waits for, its metadata taken out', async () => {
    const segment = (marker: number, body: number[]): number[] => [0xff, marker, ((body.length + 2) >> 8) & 0xff, (body.length + 2) & 0xff, ...body];
    const app0 = segment(0xe0, [0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0]);
    const scan = [...segment(0xda, [1, 1, 0, 0, 63, 0]), 0x12, 0x34, 0xff, 0xd9];
    const bare = [0xff, 0xd8, ...app0, ...scan];
    const written = [0xff, 0xd8, ...app0, ...segment(0xe1, [0x45, 0x78, 0x69, 0x66, 0, 0]), ...scan];
    const address = (bytes: number[]) => `data:image/jpeg;base64,${btoa(String.fromCharCode(...bytes))}`;
    const encode = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(address(written));
    const waits = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob');
    const frame = document.createElement('canvas');
    const picture = await frameJpeg(frame, 0.72);
    expect(encode).toHaveBeenCalledWith('image/jpeg', 0.72);
    expect(waits).not.toHaveBeenCalled();
    expect(picture?.type).toBe('image/jpeg');
    expect([...new Uint8Array(await picture!.arrayBuffer())]).toEqual(bare);
    // Nothing to encode (an empty canvas), or a browser that writes no JPEG: no picture.
    encode.mockReturnValue('data:,');
    expect(await frameJpeg(frame)).toBeNull();
    encode.mockReturnValue('data:image/png;base64,iVBORw0KGgo=');
    expect(await frameJpeg(frame)).toBeNull();
  });

  it('sends a JPEG without the metadata a browser writes, which the server refuses, and its scan unchanged', () => {
    const segment = (marker: number, body: number[]): number[] => [0xff, marker, ((body.length + 2) >> 8) & 0xff, (body.length + 2) & 0xff, ...body];
    const app0 = segment(0xe0, [0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0]);
    const quantised = segment(0xdb, [0, ...Array.from({ length: 64 }, (_, index) => index)]);
    const frame = segment(0xc0, [8, 0, 180, 1, 64, 1, 1, 0x11, 0]);
    const scan = [...segment(0xda, [1, 1, 0, 0, 63, 0]), 0x12, 0xff, 0x00, 0x34, 0xff, 0xd9];
    const bare = [0xff, 0xd8, ...app0, ...quantised, ...frame, ...scan];
    // A colour profile (APP2), Exif (APP1) and a comment, as an encoder may add them.
    const written = [0xff, 0xd8, ...app0, ...segment(0xe2, [0x49, 0x43, 0x43, 0x5f, 1, 2, 3]), ...segment(0xe1, [0x45, 0x78, 0x69, 0x66, 0, 0]),
      ...quantised, ...segment(0xfe, [0x68, 0x69]), ...frame, ...scan];
    expect([...jpegWithoutMetadata(Uint8Array.from(written))]).toEqual(bare);
    expect([...jpegWithoutMetadata(Uint8Array.from(bare))]).toEqual(bare);
    // Not a JPEG, or one cut short, comes back as it is for the server to refuse.
    const notJpeg = Uint8Array.from([0x89, 0x50, 0x4e, 0x47]);
    expect(jpegWithoutMetadata(notJpeg)).toBe(notJpeg);
    const cut = Uint8Array.from(written.slice(0, 30));
    expect(jpegWithoutMetadata(cut)).toBe(cut);
  });

  // A frame of a world drawn before its land and light: near white and colourless, crossed by darker
  // lines (one pixel in ten), so it is not one flat colour: only the washed-out check refuses it.
  const washedLevel = (index: number): number => ((index >> 2) % 10 === 0 ? 150 : 236 + ((index >> 2) % 7) + (index % 4 === 2 ? 3 : 0));
  // A drawn world: sky, ground and shade, in colour.
  const drawnLevel = (index: number): number => (index % 4 === 2 ? 180 : index % 4 === 1 ? 140 : 90) + ((index >> 2) % 60);

  it('reads a frame as the drawn world only when it is neither one flat colour nor washed out', () => {
    const frame = (level: (index: number) => number) => Uint8ClampedArray.from({ length: 1280 * 720 * 4 }, (_, index) => level(index));
    expect(holdsWorld(frame(drawnLevel))).toBe(true);
    expect(holdsWorld(frame(() => 30))).toBe(false);
    expect(holdsWorld(frame(washedLevel))).toBe(false);
    // The same frame with its washed share under half is a world: a bright sky over a darker town.
    expect(holdsWorld(frame((index) => ((index >> 2) % 10 < 6 ? 120 + ((index >> 2) % 30) : washedLevel(index))))).toBe(true);
    // Bright but coloured (a sunlit sky over sand) is a world.
    expect(holdsWorld(frame((index) => (index % 4 === 2 ? 215 : index % 4 === 1 ? 190 : 120) + ((index >> 2) % 40)))).toBe(true);
  });

  it('keeps nothing, here or on the server, until a frame holds the drawn world, then keeps that one', async () => {
    const put = server();
    const first = world();
    const source = renderer(washedLevel);
    const painted = (source.app.graphicsDevice.canvas.getContext('2d') as unknown as { getImageData: () => { data: Uint8ClampedArray } }).getImageData().data;
    let waits = 0;
    const sleep = vi.fn(async () => {
      waits += 1;
      // While the world is waited for nothing is kept; on the third wait the land is drawn.
      expect(own(first)).toBeNull();
      expect(put.putPicture).not.toHaveBeenCalled();
      if (waits === 3) painted.forEach((_, index) => { painted[index] = drawnLevel(index); });
    });
    const record = await keepFirstViewPicture(source, first, put, { sleep });
    expect(waits).toBe(3);
    expect(sleep).toHaveBeenCalledWith(FIRST_VIEW_WAIT.retryMs);
    expect(record).not.toBeNull();
    expect(own(first)).toBe('data:image/jpeg;base64,BBBB');
    expect(put.putPicture).toHaveBeenCalledTimes(1);
  });

  it('keeps nothing when no frame holds the drawn world within the bound, nor once another world is open', async () => {
    const put = server();
    const never = world();
    const sleep = vi.fn(async () => undefined);
    expect(await keepFirstViewPicture(renderer(washedLevel), never, put, { sleep })).toBeNull();
    // Asked at the start and after each retry, up to the bound.
    expect(sleep).toHaveBeenCalledTimes(FIRST_VIEW_WAIT.boundMs / FIRST_VIEW_WAIT.retryMs);
    expect(own(never)).toBeNull();
    expect(put.putPicture).not.toHaveBeenCalled();
    let open = true;
    const left = world({ entryId: '99999999-9999-4999-8999-999999999999' });
    const leaving = vi.fn(async () => { open = false; });
    expect(await keepFirstViewPicture(renderer(washedLevel), left, put, { sleep: leaving, current: () => open })).toBeNull();
    expect(leaving).toHaveBeenCalledTimes(1);
    expect(own(left)).toBeNull();
  });

  it('asks for no frame while the world says its drawing is not ready', async () => {
    const put = server();
    const dressed = world();
    let ready = false;
    const source = renderer(drawnLevel);
    const asked = vi.spyOn(source.app, 'on');
    const sleep = vi.fn(async () => { ready = sleep.mock.calls.length >= 2; });
    await keepFirstViewPicture(source, dressed, put, { sleep, ready: () => ready });
    expect(sleep).toHaveBeenCalledTimes(2);
    expect(asked).toHaveBeenCalledTimes(1);
    expect(own(dressed)).toBe('data:image/jpeg;base64,BBBB');
  });

  it('never sends a frame of a world that holds or held a photograph', async () => {
    const attachment = {} as SavedWorldEntry['sourceAttachments'][number];
    const removed = {} as NonNullable<SavedWorldEntry['previousSourceAttachments']>[number];
    const photographed = [
      world({ sourceKind: 'personal', generatedGround: null }),
      world({ sourceKind: 'authored', authoredScene: {} as never, generatedGround: null, sourceAttachments: [attachment] }),
      world({ sourceKind: 'authored', authoredScene: {} as never, generatedGround: null, previousSourceAttachments: [removed] }),
    ];
    const put = server();
    for (const one of photographed) {
      expect(mayPutPicture(one)).toBe(false);
      expect(await keepFirstViewPicture(renderer(), one, put)).toBeNull();
      expect(own(one)).toBe('data:image/jpeg;base64,BBBB');
    }
    expect(put.putPicture).not.toHaveBeenCalled();
    expect(mayPutPicture(world())).toBe(true);
    expect(mayPutPicture(starter())).toBe(true);
  });

  it('leaves the browser\'s own picture when the put is refused, and keeps and puts no flat frame', async () => {
    const refused = world();
    const put = { putPicture: vi.fn(async () => { throw new Error('read only'); }) };
    expect(await keepFirstViewPicture(renderer(), refused, put)).toBeNull();
    expect(own(refused)).toBe('data:image/jpeg;base64,BBBB');
    expect(worldPicture(refused)).toBe('data:image/jpeg;base64,BBBB');
    const flat = world();
    const quietPut = server();
    expect(await keepFirstViewPicture(renderer(() => 40), flat, quietPut, { sleep: async () => undefined })).toBeNull();
    expect(own(flat)).toBeNull();
    expect(quietPut.putPicture).not.toHaveBeenCalled();
  });
});

describe('View values on Your worlds', () => {
  const made = (values: Readonly<Record<string, number | string>> | null) => entry({
    generatedGround: {
      recipeKey: 'market_town', recipeLabel: 'A market town', regionId: 'r',
      arrivalMm: [0, 0, 0], arrivalFacingMm: [1, 0], tiles: [],
      specification: values === null ? null : 'world-specification.v2', values,
    },
  });
  const button = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('[data-action="worlds.values"]')!;

  it('inspects the saved receipt before explicitly creating another world from it', () => {
    const viewValues = vi.fn();
    const world = made({ city_extent_x_mm: 384000, cross_street_hierarchy: 'local_street' });
    const { root } = build([world], { viewValues });
    expect(button(root).hidden).toBe(false);
    expect(button(root).getAttribute('aria-disabled')).toBe('false');
    button(root).click();
    expect(viewValues).not.toHaveBeenCalled();
    const dialog = document.querySelector<HTMLDialogElement>('.generation-details')!;
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain('world-specification.v2');
    expect(dialog.querySelector('[data-saved-key="city_extent_x_mm"] dd')?.textContent).toBe('384000');
    [...dialog.querySelectorAll('button')].find(control => control.textContent === 'Create another from these inputs')!.click();
    expect(viewValues).toHaveBeenLastCalledWith(world);
    press(root.querySelector('.your-worlds-card')!, 'v');
    expect(document.querySelector<HTMLDialogElement>('.generation-details')?.open).toBe(true);
    expect(viewValues).toHaveBeenCalledTimes(1);
    // Never while a person types.
    const field = document.createElement('input');
    root.append(field);
    press(field, 'v');
    expect(viewValues).toHaveBeenCalledTimes(1);
  });

  it('says a world made before values were kept has none to show, and opens nothing', () => {
    const viewValues = vi.fn();
    const { root } = build([made(null)], { viewValues });
    expect(button(root).getAttribute('aria-disabled')).toBe('true');
    expect(root.querySelector<HTMLElement>('#your-worlds-values-why')!.hidden).toBe(false);
    button(root).click();
    expect(viewValues).not.toHaveBeenCalled();
    expect(root.querySelector('.your-worlds-status')!.textContent)
      .toBe('This world was made before its values were kept, so there are none to show.');
  });

  it('offers no View values for a world not made from a recipe, or where nothing can be made', () => {
    expect(button(build([starter(1)], { viewValues: vi.fn() }).root).hidden).toBe(true);
    expect(button(build([made({ city_extent_x_mm: 1 })]).root).hidden).toBe(true);
  });
});
