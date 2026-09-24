// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  buildPersonalWorldChoice,
  buildWorldEntrySurface,
} from '../src/composition/world-entry.js';
import {
  WorldEntryClient,
  type PersonalWorldState,
  type SavedWorldEntry,
} from '../src/world-entry-api.js';

const PERSONAL_WORLD = 'world:personal:7b0e5d1c-0000-4000-8000-000000000001';
const DIGEST = 'f'.repeat(64);

/** `GET /worlds/personal-source` as the server sends it. */
const stateWire = (overrides: Record<string, unknown> = {}) => ({
  action: 'create_world',
  refusal: null,
  world_id: null,
  saved_entry_id: null,
  photographs: { reviewed: 3, composed: 2, outside_scene_groups: 1 },
  regions: 1,
  topology_digest: DIGEST,
  current_topology_digest: null,
  preview: null,
  ...overrides,
});

const refusedWire = (code: string, detail: string) => stateWire({
  action: null, refusal: { code, detail }, topology_digest: null,
});

const entryWire = (overrides: Record<string, unknown> = {}) => ({
  entry_id: '11111111-1111-4111-8111-111111111111',
  world_id: PERSONAL_WORLD,
  title: 'My photographs',
  source_kind: 'personal',
  source_snapshot_id: '55555555-5555-4555-8555-555555555555',
  source_snapshot_sha256: 'c'.repeat(64),
  authored_scene: null,
  authored_version_id: '22222222-2222-4222-8222-222222222222',
  authored_state_sha256: 'a'.repeat(64),
  authored_edit_seq: 0,
  current_authored_state_sha256: 'a'.repeat(64),
  current_authored_edit_seq: 0,
  style_version_id: '33333333-3333-4333-8333-333333333333',
  revision: 1,
  availability: 'available',
  unavailable_reason: null,
  source_attachments: [],
  created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-09-24T12:00:00Z',
  updated_at: '2026-09-24T12:00:00Z',
  ...overrides,
});

interface Sent { readonly method: string; readonly path: string; readonly body: unknown }

/** A server that answers the composition path and records every request, in order. */
function server(composed: Record<string, unknown>) {
  const sent: Sent[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const path = `${url.pathname}${url.search}`;
    const body = typeof init.body === 'string' ? JSON.parse(init.body) as unknown : null;
    sent.push({ method: init.method ?? 'GET', path, body });
    if (url.pathname === '/worlds/personal-source' && init.method === 'POST') {
      return Response.json(composed);
    }
    if (url.pathname === '/worlds/personal-source') return Response.json(stateWire());
    if (url.pathname === '/world/styles/current') {
      return Response.json({
        current_topology_digest: DIGEST,
        current: { version_id: '33333333-3333-4333-8333-333333333333' },
      });
    }
    if (url.pathname === '/world/versions/bootstrap') {
      return Response.json({ version_id: '22222222-2222-4222-8222-222222222222' });
    }
    if (url.pathname === '/world-entries') return Response.json(entryWire(), { status: 201 });
    if (url.pathname.startsWith('/world-entries/')) return Response.json(entryWire());
    throw new Error(`unexpected ${init.method ?? 'GET'} ${path}`);
  });
  return {
    sent,
    client: new WorldEntryClient({ baseUrl: 'https://exulanica.test', token: 'private', fetch }),
  };
}

const composedWire = (overrides: Record<string, unknown> = {}) => ({
  action: 'create_world',
  world_id: PERSONAL_WORLD,
  topology_digest: DIGEST,
  style_version_id: '33333333-3333-4333-8333-333333333333',
  saved_entry_id: null,
  ...overrides,
});

describe('the client for making a world from reviewed photographs', () => {
  it('reads the server state, and refuses a state that is both, neither, or unknown', async () => {
    const { client } = server(composedWire());
    const state = await client.personalWorld();
    expect(state).toMatchObject({
      action: 'create_world', refusal: null, topologyDigest: DIGEST,
      photographs: { reviewed: 3, composed: 2, outsideSceneGroups: 1 }, regions: 1,
    });
    for (const wrong of [
      stateWire({ refusal: { code: 'x', detail: 'y' } }),
      stateWire({ action: null }),
      stateWire({ action: 'make_it_anyway' }),
    ]) {
      const fetch = vi.fn(async () => Response.json(wrong));
      await expect(new WorldEntryClient({
        baseUrl: 'https://exulanica.test', token: 'private', fetch,
      }).personalWorld()).rejects.toThrow(TypeError);
    }
  });

  it('composes exactly what was read, then saves the world the server named', async () => {
    const { client, sent } = server(composedWire());
    const state = await client.personalWorld();
    sent.length = 0;
    const entry = await client.makeFromPersonalSources(state, 'Harbour walks');
    expect(entry.worldId).toBe(PERSONAL_WORLD);
    expect(sent.map(({ method, path }) => `${method} ${path}`)).toEqual([
      'POST /worlds/personal-source',
      `GET /world/styles/current?world_id=${encodeURIComponent(PERSONAL_WORLD)}`,
      `POST /world/versions/bootstrap?world_id=${encodeURIComponent(PERSONAL_WORLD)}`,
      'POST /world-entries',
    ]);
    // The digest the read showed, and nothing the browser chose: no photographs, no region.
    expect(sent[0]?.body).toEqual({ topology_digest: DIGEST });
    expect(sent[3]?.body).toMatchObject({
      world_id: PERSONAL_WORLD, title: 'Harbour walks', source_kind: 'personal',
    });
  });

  it('reopens the saved world that already names it rather than saving a second', async () => {
    const saved = '99999999-9999-4999-8999-999999999999';
    const { client, sent } = server(composedWire({
      action: 'update_world', saved_entry_id: saved,
    }));
    const state = await client.personalWorld();
    sent.length = 0;
    await client.makeFromPersonalSources(state, 'ignored');
    expect(sent.map(({ method, path }) => `${method} ${path}`)).toEqual([
      'POST /worlds/personal-source', `GET /world-entries/${saved}`,
    ]);
  });

  it('sends nothing for a state the server refused', async () => {
    const { client, sent } = server(composedWire());
    const fetch = vi.fn(async () => Response.json(refusedWire(
      'no_reviewed_personal_sources', 'Review your photographs first.',
    )));
    const refused = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).personalWorld();
    await expect(client.makeFromPersonalSources(refused, 'x'))
      .rejects.toThrow('Review your photographs first.');
    expect(sent).toEqual([]);
  });
});

const entry = (): SavedWorldEntry => ({
  entryId: '11111111-1111-4111-8111-111111111111',
  worldId: PERSONAL_WORLD,
  title: 'My photographs',
  sourceKind: 'personal',
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
  createdAt: '2026-09-24T12:00:00Z',
  updatedAt: '2026-09-24T12:00:00Z',
});

const offered = (overrides: Partial<PersonalWorldState> = {}): PersonalWorldState => ({
  action: 'create_world',
  refusal: null,
  worldId: null,
  savedEntryId: null,
  photographs: { reviewed: 3, composed: 2, outsideSceneGroups: 1 },
  regions: 1,
  topologyDigest: DIGEST,
  currentTopologyDigest: null,
  preview: null,
  ...overrides,
});

const refused = (detail: string): PersonalWorldState => offered({
  action: null, refusal: { code: 'no_reviewed_personal_sources', detail }, topologyDigest: null,
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const button = (root: HTMLElement) =>
  root.querySelector<HTMLButtonElement>('.personal-world-make')!;

describe('the choice to make a world from reviewed photographs', () => {
  it('shows the server refusal in its own words and offers nothing', async () => {
    const words = 'None of your photographs has a current review from you. Review them first.';
    const control = buildPersonalWorldChoice({
      read: vi.fn(async () => refused(words)), make: vi.fn(), open: vi.fn(),
    });
    await control.refresh();
    expect(control.root.dataset['state']).toBe('refused');
    expect(control.root.querySelector('.personal-world-status')?.textContent).toBe(words);
    expect(button(control.root).hidden).toBe(true);
    expect(button(control.root).disabled).toBe(true);
    expect(control.root.querySelector<HTMLElement>('.personal-world-title-row')?.hidden)
      .toBe(true);
  });

  it('offers the action the server names, with its counts, and opens what it makes', async () => {
    const made = entry();
    const make = vi.fn(async () => made);
    const open = vi.fn(async () => undefined);
    const control = buildPersonalWorldChoice({ read: vi.fn(async () => offered()), make, open });
    await control.refresh();
    expect(button(control.root).hidden).toBe(false);
    expect(button(control.root).textContent).toBe('Make a world from my photographs');
    expect(control.root.querySelector('.personal-world-counts')?.textContent).toBe(
      '2 reviewed photographs in 1 place. 1 reviewed photograph is not in any place, so it is '
        + 'left out.',
    );
    const title = control.root.querySelector<HTMLInputElement>('.personal-world-title')!;
    title.value = 'Harbour walks';
    button(control.root).click();
    await settle();
    expect(make).toHaveBeenCalledWith(offered(), 'Harbour walks');
    expect(open).toHaveBeenCalledWith(made);
  });

  it('offers a world composed but never made as making one, and asks for its name', async () => {
    const control = buildPersonalWorldChoice({
      read: vi.fn(async () => offered({ action: 'update_world', worldId: PERSONAL_WORLD })),
      make: vi.fn(), open: vi.fn(),
    });
    await control.refresh();
    expect(button(control.root).textContent).toBe('Make a world from my photographs');
    expect(control.root.querySelector<HTMLElement>('.personal-world-title-row')?.hidden)
      .toBe(false);
  });

  it('shows a refused write in the server words, not its code, and reads again', async () => {
    const words = 'Your reviewed photographs changed after this was checked, so nothing was made.';
    const read = vi.fn(async () => offered())
      .mockResolvedValueOnce(offered())
      .mockResolvedValueOnce(offered({ topologyDigest: 'e'.repeat(64) }));
    const open = vi.fn();
    const control = buildPersonalWorldChoice({
      read,
      make: vi.fn(async () => { throw new ApiError(409, 'personal_sources_changed', words); }),
      open,
    });
    await control.refresh();
    button(control.root).click();
    await settle();
    await settle();
    const failure = control.root.querySelector<HTMLElement>('.personal-world-failure')!;
    expect(failure.hidden).toBe(false);
    expect(failure.textContent).toBe(words);
    expect(open).not.toHaveBeenCalled();
    expect(read).toHaveBeenCalledTimes(2);
    expect(button(control.root).disabled).toBe(false);
  });

  it('sits under the saved worlds in the list of worlds', async () => {
    const control = buildPersonalWorldChoice({
      read: vi.fn(async () => offered()), make: vi.fn(), open: vi.fn(),
    });
    const surface = buildWorldEntrySurface({
      entries: [entry(), { ...entry(), entryId: 'other', title: 'My world' }],
      open: vi.fn(), adoptLatest: vi.fn(), personalWorld: control,
    });
    const list = surface.querySelector('.world-entry-list')!;
    expect(surface.lastElementChild).toBe(control.root);
    expect(list.compareDocumentPosition(control.root) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });
});
