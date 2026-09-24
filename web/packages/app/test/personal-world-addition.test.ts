// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { tierPolicy } from '@exulanica/companion-runtime';
import { ApiError } from '@exulanica/graph-client';
import { buildPersonalWorldChoice } from '../src/composition/world-entry.js';
import {
  WorldEntryClient,
  type PersonalWorldState,
  type SavedWorldEntry,
} from '../src/world-entry-api.js';

const WORLD = 'world:personal:7b0e5d1c-0000-4000-8000-000000000001';
const ENTRY = '11111111-1111-4111-8111-111111111111';
const DIGEST = 'f'.repeat(64);
const PREVIEW = 'd'.repeat(64);
const SENTENCES = [
  '2 photographs you reviewed since will be added to your world\'s places.',
  '1 joins 1 place already in it.',
  '1 makes 1 new place.',
  'Its appearance and everything you made in it carry over: 1 object you placed.',
  'Your world as it is now stays saved as its previous version.',
];

/** `GET /worlds/personal-source` offering to add photographs, as the server sends it. */
const additionWire = (overrides: Record<string, unknown> = {}) => ({
  action: 'add_photographs',
  refusal: null,
  world_id: WORLD,
  saved_entry_id: ENTRY,
  photographs: { reviewed: 4, composed: 4, outside_scene_groups: 0 },
  regions: 2,
  topology_digest: DIGEST,
  current_topology_digest: 'e'.repeat(64),
  preview: {
    preview_sha256: PREVIEW,
    sentences: SENTENCES,
    counts: { photographs_added: 2, places_growing: 1, new_places: 1 },
  },
  ...overrides,
});

const entryWire = () => ({
  entry_id: ENTRY,
  world_id: WORLD,
  title: 'My photographs',
  source_kind: 'personal',
  source_snapshot_id: '66666666-6666-4666-8666-666666666666',
  source_snapshot_sha256: 'c'.repeat(64),
  authored_scene: null,
  authored_version_id: '77777777-7777-4777-8777-777777777777',
  authored_state_sha256: 'a'.repeat(64),
  authored_edit_seq: 1,
  current_authored_state_sha256: 'a'.repeat(64),
  current_authored_edit_seq: 1,
  style_version_id: '33333333-3333-4333-8333-333333333333',
  revision: 3,
  availability: 'available',
  unavailable_reason: null,
  source_attachments: [],
  created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-09-24T12:00:00Z',
  updated_at: '2026-09-24T12:30:00Z',
});

interface Sent { readonly method: string; readonly path: string; readonly body: unknown }

function server(read: Record<string, unknown>) {
  const sent: Sent[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const body = typeof init.body === 'string' ? JSON.parse(init.body) as unknown : null;
    sent.push({ method: init.method ?? 'GET', path: `${url.pathname}${url.search}`, body });
    if (url.pathname === '/worlds/personal-source' && init.method === 'POST') {
      return Response.json({
        action: 'add_photographs', world_id: WORLD, topology_digest: DIGEST,
        style_version_id: '33333333-3333-4333-8333-333333333333', saved_entry_id: ENTRY,
      });
    }
    if (url.pathname === '/worlds/personal-source') return Response.json(read);
    if (url.pathname === `/world-entries/${ENTRY}`) return Response.json(entryWire());
    throw new Error(`unexpected ${init.method ?? 'GET'} ${url.pathname}`);
  });
  return {
    sent,
    client: new WorldEntryClient({ baseUrl: 'https://exulanica.test', token: 'private', fetch }),
  };
}

describe('the client for adding reviewed photographs to a made world', () => {
  it('reads the preview, and refuses an addition without one or a preview without an addition',
    async () => {
      const state = await server(additionWire()).client.personalWorld();
      expect(state.action).toBe('add_photographs');
      expect(state.preview).toEqual({
        previewSha256: PREVIEW, sentences: SENTENCES, photographsAdded: 2,
      });
      for (const wrong of [
        additionWire({ preview: null }),
        additionWire({ action: 'save_entry' }),
        additionWire({ preview: { ...additionWire().preview, preview_sha256: 'nope' } }),
        additionWire({ preview: { ...additionWire().preview, sentences: [] } }),
      ]) {
        await expect(server(wrong).client.personalWorld()).rejects.toThrow(TypeError);
      }
    });

  it('confirms with the digest of the preview it showed, then reads the world it moved',
    async () => {
      const { client, sent } = server(additionWire());
      const state = await client.personalWorld();
      sent.length = 0;
      const moved = await client.makeFromPersonalSources(state, 'ignored');
      expect(moved.entryId).toBe(ENTRY);
      expect(sent.map(({ method, path }) => `${method} ${path}`)).toEqual([
        'POST /worlds/personal-source', `GET /world-entries/${ENTRY}`,
      ]);
      expect(sent[0]?.body).toEqual({ topology_digest: DIGEST, preview_sha256: PREVIEW });
    });
});

const offered = (): PersonalWorldState => ({
  action: 'add_photographs',
  refusal: null,
  worldId: WORLD,
  savedEntryId: ENTRY,
  photographs: { reviewed: 4, composed: 4, outsideSceneGroups: 0 },
  regions: 2,
  topologyDigest: DIGEST,
  currentTopologyDigest: 'e'.repeat(64),
  preview: { previewSha256: PREVIEW, sentences: SENTENCES, photographsAdded: 2 },
});

const moved = { entryId: ENTRY } as SavedWorldEntry;
const DELAY = tierPolicy(2).confirmEnabledAfterMs;
const within = (root: HTMLElement) => ({
  add: root.querySelector<HTMLButtonElement>('.personal-world-make')!,
  confirmation: root.querySelector<HTMLElement>('.personal-world-confirm')!,
  confirm: root.querySelector<HTMLButtonElement>('.personal-world-confirm-add')!,
  cancel: root.querySelector<HTMLButtonElement>('.personal-world-cancel')!,
  sentences: () => [...root.querySelectorAll('.personal-world-preview li')]
    .map((line) => line.textContent),
  counts: () => root.querySelector('.personal-world-counts')?.textContent,
  countsLine: root.querySelector<HTMLElement>('.personal-world-counts')!,
  failure: root.querySelector<HTMLElement>('.personal-world-failure')!,
});

afterEach(() => { vi.useRealTimers(); });

describe('the choice to add reviewed photographs to a made world', () => {
  it('offers the addition in the server words, and pressing it writes nothing but the preview',
    async () => {
      vi.useFakeTimers();
      const make = vi.fn(async () => moved);
      const control = buildPersonalWorldChoice({
        read: vi.fn(async () => offered()), make, open: vi.fn(),
      });
      await control.refresh();
      const at = within(control.root);
      expect(at.add.textContent).toBe('Add my new photographs as places');
      expect(at.counts()).toBe(SENTENCES[0]);
      expect(at.countsLine.hidden).toBe(false);
      expect(at.confirmation.hidden).toBe(true);
      at.add.click();
      expect(make).not.toHaveBeenCalled();
      expect(at.confirmation.hidden).toBe(false);
      expect(at.add.hidden).toBe(true);
      expect(at.sentences()).toEqual(SENTENCES);
      // The offer's line is the list's first sentence, so it is not said twice.
      expect(at.countsLine.hidden).toBe(true);
      // Confirm wakes only after the tier 2 delay, so a double press cannot carry through.
      expect(at.confirm.disabled).toBe(true);
      at.confirm.click();
      expect(make).not.toHaveBeenCalled();
      vi.advanceTimersByTime(DELAY - 1);
      expect(at.confirm.disabled).toBe(true);
      vi.advanceTimersByTime(1);
      expect(at.confirm.disabled).toBe(false);
    });

  it('cancels back to the offer and sends nothing', async () => {
    vi.useFakeTimers();
    const make = vi.fn(async () => moved);
    const control = buildPersonalWorldChoice({
      read: vi.fn(async () => offered()), make, open: vi.fn(),
    });
    await control.refresh();
    const at = within(control.root);
    at.add.click();
    vi.advanceTimersByTime(DELAY);
    at.cancel.click();
    expect(make).not.toHaveBeenCalled();
    expect(at.confirmation.hidden).toBe(true);
    expect(at.add.hidden).toBe(false);
    expect(at.countsLine.hidden).toBe(false);
    expect(at.sentences()).toEqual([]);
  });

  it('confirms exactly the previewed state and opens the world it moved', async () => {
    vi.useFakeTimers();
    const make = vi.fn(async () => moved);
    const open = vi.fn(async () => undefined);
    const control = buildPersonalWorldChoice({ read: vi.fn(async () => offered()), make, open });
    await control.refresh();
    const at = within(control.root);
    at.add.click();
    vi.advanceTimersByTime(DELAY);
    at.confirm.click();
    await vi.runAllTimersAsync();
    expect(make).toHaveBeenCalledWith(offered(), 'My photographs');
    expect(open).toHaveBeenCalledWith(moved);
  });

  it('shows a preview that changed in the server words and reads the offer again', async () => {
    vi.useFakeTimers();
    const words = 'Your world or your photographs changed after you looked, so nothing was added. '
      + 'Look again, then confirm.';
    const read = vi.fn(async () => offered());
    const open = vi.fn();
    const control = buildPersonalWorldChoice({
      read,
      make: vi.fn(async () => {
        throw new ApiError(409, 'personal_world_preview_changed', words);
      }),
      open,
    });
    await control.refresh();
    const at = within(control.root);
    at.add.click();
    vi.advanceTimersByTime(DELAY);
    at.confirm.click();
    await vi.runAllTimersAsync();
    expect(at.failure.hidden).toBe(false);
    expect(at.failure.textContent).toBe(words);
    expect(open).not.toHaveBeenCalled();
    expect(read).toHaveBeenCalledTimes(2);
    expect(at.add.hidden).toBe(false);
    expect(at.add.disabled).toBe(false);
  });
});
