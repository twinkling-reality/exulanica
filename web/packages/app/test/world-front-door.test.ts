// @vitest-environment happy-dom
// What a world's card offers on the world workspace's front door (tools/previews/world-workspace/front-door-card.ts,
// which front-door.ts runs over the app's Your worlds): Open and Details only. The app's View values, its button and
// its V, opens the saved values whose "Create another from these inputs" is the shell's own Create, a way back into
// the shell, so the front door leaves it out. After the saved worlds the front door offers the installation's showcase
// worlds the workspace does not hold yet (showcase-world.ts), whose Open makes the copy as the world's link does.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildYourWorlds } from '../src/composition/world-entry.js';
import type { Credentials } from '../src/config.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

const card = async (): Promise<{ offerOpenAndDetailsOnly(root: HTMLElement): void }> =>
  import('../../../../tools/previews/world-workspace/' + 'front-door-card.ts') as Promise<{ offerOpenAndDetailsOnly(root: HTMLElement): void }>;

/** A town made from a starter card, with the values it was made from. */
const town = {
  entryId: '11111111-1111-4111-8111-111111111111',
  worldId: 'world:generated:one',
  title: 'A small town',
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
    recipeKey: 'small_town', recipeLabel: 'A small town', regionId: 'r', arrivalMm: [0, 0, 0], arrivalFacingMm: [1, 0],
    tiles: [], specification: 'world-specification.v2', values: { city_extent_x_mm: 384000 },
  },
} as SavedWorldEntry;

/** Your worlds as the app builds it with View values offered, in the page. */
function yourWorlds(): HTMLElement {
  const handle = buildYourWorlds({ entries: [town], open: vi.fn(async () => undefined), adoptLatest: vi.fn(async () => undefined), create: vi.fn(), viewValues: vi.fn() });
  document.body.append(handle.root);
  return handle.root;
}
const press = (target: Element, key: string): void => { target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })); };
const valuesShown = (): boolean => document.querySelector<HTMLDialogElement>('.generation-details')?.open === true;
const valuesButton = (root: HTMLElement): HTMLElement | null => root.querySelector('[data-action="worlds.values"]');

afterEach(() => { document.body.replaceChildren(); });

describe('a world\'s card on the workspace\'s front door', () => {
  it('offers View values in the app\'s own Your worlds, button and V: a positive control', () => {
    const root = yourWorlds();
    expect(valuesButton(root)).not.toBeNull();
    press(root.querySelector('.your-worlds-card')!, 'v');
    expect(valuesShown()).toBe(true);
  });

  it('offers Open and Details only: no View values button, its note gone, and V shows nothing', async () => {
    const root = yourWorlds();
    (await card()).offerOpenAndDetailsOnly(root);
    expect(valuesButton(root)).toBeNull();
    expect(root.querySelector('#your-worlds-values-why')).toBeNull();
    press(root.querySelector('.your-worlds-card')!, 'v');
    press(root.querySelector('.your-worlds-card')!, 'V');
    expect(valuesShown()).toBe(false);
    expect(root.querySelector('.your-worlds-open')).not.toBeNull();
  });

  it('lets a person type v in a field on the page', async () => {
    const root = yourWorlds();
    (await card()).offerOpenAndDetailsOnly(root);
    const field = document.createElement('input');
    root.append(field);
    const heard = vi.fn();
    field.addEventListener('keydown', heard);
    press(field, 'v');
    expect(heard).toHaveBeenCalledTimes(1);
  });
});

/** What the front door reads of the installation's showcase worlds (tools/previews/world-workspace/showcase-world.ts). */
interface Showcase {
  showcaseOffers(access: Credentials, held: readonly { readonly worldId: string }[]): Promise<{ key: string; title: string; picture: string | null }[]>;
  makeShowcaseCopy(access: Credentials, key: string): Promise<SavedWorldEntry>;
}
const showcase = async (): Promise<Showcase> =>
  import('../../../../tools/previews/world-workspace/' + 'showcase-world.ts') as Promise<Showcase>;

describe('the showcase worlds on the workspace\'s front door', () => {
  const access: Credentials = { baseUrl: 'http://127.0.0.1:20611/api', token: '' };
  const picture = new Uint8Array([255, 216, 255, 217]);
  const hex = async (bytes: Uint8Array<ArrayBuffer>): Promise<string> => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map((n) => n.toString(16).padStart(2, '0')).join('');
  /** A served world as GET /worlds/showcase lists it. */
  const served = (key: string, title: string, worldId: string, sha256: string) => ({
    key, title, sentence: title.toLowerCase(), world_id: worldId, picture: { sha256, media_type: 'image/jpeg', width: 1280, height: 720 },
  });
  /** A copy's saved entry as POST /worlds/showcase/{key} answers it: a place made from its kind. */
  const copy = {
    entry_id: '77777777-7777-4777-8777-777777777777', world_id: 'world:generated:fish', title: 'Fishing village',
    source_kind: 'generated', source_snapshot_id: '55555555-5555-4555-8555-555555555555', source_snapshot_sha256: 'c'.repeat(64),
    authored_scene: null, authored_version_id: '22222222-2222-4222-8222-222222222222', authored_state_sha256: 'a'.repeat(64),
    authored_edit_seq: 0, current_authored_state_sha256: 'a'.repeat(64), current_authored_edit_seq: 0,
    style_version_id: '33333333-3333-4333-8333-333333333333', revision: 1, availability: 'available', unavailable_reason: null,
    source_attachments: [], created_at: '2026-10-28T12:00:00Z', updated_at: '2026-10-28T12:00:00Z', takes_photographs: false,
    generated_site: { kind: 'fishing_village', kind_version: 1, kind_label: 'Fishing village', region_id: 'region:generated', arrival_mm: [0, 0, 0], arrival_facing_mm: [0, 1] },
  };
  /** Each request a stand-in for fetch was asked, as its method and address. */
  const asked = (stub: { readonly mock: { readonly calls: readonly (readonly unknown[])[] } }) =>
    stub.mock.calls.map((call) => `${(call[1] as RequestInit | undefined)?.method ?? 'GET'} ${String(call[0])}`);
  const json = (body: unknown, { status = 200, headers = {} }: { readonly status?: number; readonly headers?: Record<string, string> } = {}) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('offers each served world the workspace holds no copy of, its picture shown only as the digest the catalog names', async () => {
    const digest = await hex(picture);
    const catalog = { worlds: [
      served('fishing-village', 'Fishing village', 'world:generated:fish', digest),
      served('mountain-town', 'A snowy mountain town with a bakery', town.worldId, digest),
      served('night-market', 'Night market', 'world:generated:night', 'f'.repeat(64)),
    ] };
    const reads = vi.fn(async (url: string) => (url.endsWith('/worlds/showcase')
      ? json(catalog) : new Response(new Blob([picture], { type: 'image/jpeg' }))));
    vi.stubGlobal('fetch', reads);
    const offers = await (await showcase()).showcaseOffers(access, [town]);
    // The town the workspace holds is a copy of the mountain town: it is the workspace's own card, not an offer.
    expect(offers.map((one) => [one.key, one.title])).toEqual([['fishing-village', 'Fishing village'], ['night-market', 'Night market']]);
    expect(offers[0]!.picture).toMatch(/^blob:/u);
    expect(offers[1]!.picture).toBeNull();
    expect(asked(reads)).toEqual([
      'GET http://127.0.0.1:20611/api/worlds/showcase',
      `GET http://127.0.0.1:20611/api/worlds/showcase/fishing-village/picture?sha256=${digest}`,
      `GET http://127.0.0.1:20611/api/worlds/showcase/night-market/picture?sha256=${'f'.repeat(64)}`,
    ]);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })));
    expect(await (await showcase()).showcaseOffers(access, [town])).toEqual([]);
  });

  it('makes the copy as the world\'s link does, asking again while it is being made, and says why where it was not', async () => {
    vi.useFakeTimers();
    const answers = [
      json({ code: 'kind_work_waiting', detail: 'still being made' }, { status: 503, headers: { 'Retry-After': '1' } }),
      json({ entry: copy, made: true, incomplete: [] }, { status: 201 }),
    ];
    const asks = vi.fn(async () => answers.shift()!);
    vi.stubGlobal('fetch', asks);
    const making = (await showcase()).makeShowcaseCopy(access, 'fishing-village');
    await vi.advanceTimersByTimeAsync(1000);
    const entry = await making;
    expect(entry.entryId).toBe(copy.entry_id);
    expect(entry.worldId).toBe('world:generated:fish');
    expect(asked(asks)).toEqual([
      'POST http://127.0.0.1:20611/api/worlds/showcase/fishing-village', 'POST http://127.0.0.1:20611/api/worlds/showcase/fishing-village',
    ]);
    vi.stubGlobal('fetch', vi.fn(async () => json({ code: 'world_limit_reached', detail: 'This workspace holds as many worlds as it may.' }, { status: 409 })));
    await expect((await showcase()).makeShowcaseCopy(access, 'fishing-village')).rejects.toThrow('This workspace holds as many worlds as it may.');
  });
});
