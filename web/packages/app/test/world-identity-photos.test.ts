// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { buildWorldIdentity } from '../src/ui/world-identity.js';
import { WorldEntryClient, type SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * Adding photographs is offered by the capability the server serves for the world's kind
 * (`takes_photographs`, from `WORLD_KINDS` in `exulanica/world/worlds.py`), never by a guess from
 * the entry's source: a generated world refuses photographs by name, so the page never offers it.
 */

const wire = (takesPhotographs: unknown) => ({
  entry_id: '11111111-1111-4111-8111-111111111111',
  world_id: 'world:family-garden',
  title: 'Family garden',
  source_kind: 'personal',
  source_snapshot_id: '55555555-5555-4555-8555-555555555555',
  source_snapshot_sha256: 'c'.repeat(64),
  authored_scene: null,
  authored_version_id: '22222222-2222-4222-8222-222222222222',
  authored_state_sha256: 'a'.repeat(64),
  authored_edit_seq: 4,
  current_authored_state_sha256: 'a'.repeat(64),
  current_authored_edit_seq: 4,
  style_version_id: '33333333-3333-4333-8333-333333333333',
  revision: 1,
  availability: 'available',
  unavailable_reason: null,
  source_attachments: [],
  created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-09-19T12:00:00Z',
  updated_at: '2026-09-19T12:00:00Z',
  ...(takesPhotographs === undefined ? {} : { takes_photographs: takesPhotographs }),
});

const read = async (body: unknown): Promise<SavedWorldEntry> => {
  const client = new WorldEntryClient({
    baseUrl: 'https://exulanica.test', token: 'private', fetch: vi.fn(async () => Response.json([body])),
  });
  return (await client.entries())[0]!;
};

const identity = (entry: SavedWorldEntry) => buildWorldIdentity({
  entry,
  personalIntake: document.createElement('div'),
  rename: async () => entry,
  onOpenWorld: () => undefined,
  onAddObject: () => undefined,
  onOpenPhotos: () => undefined,
  onClosePhotos: () => undefined,
});

const addPhotos = (root: HTMLElement): HTMLButtonElement =>
  root.querySelector('.world-add-photos') as HTMLButtonElement;

describe('adding photos follows the served capability of the world', () => {
  it('reads the capability, and refuses an entry that does not state it', async () => {
    expect((await read(wire(true))).takesPhotographs).toBe(true);
    expect((await read(wire(false))).takesPhotographs).toBe(false);
    await expect(read(wire(undefined))).rejects.toThrow('photograph capability');
    await expect(read(wire('no'))).rejects.toThrow('photograph capability');
  });

  it('offers Add photos only in a world that takes photographs, and follows the entry it is given', async () => {
    const takes = await read(wire(true));
    const refuses = await read(wire(false));
    // A positive control: the button is there, and shown, where photographs are taken.
    const shown = identity(takes);
    expect(addPhotos(shown.root).hidden).toBe(false);

    const generated = identity(refuses);
    expect(addPhotos(generated.root).hidden).toBe(true);
    generated.setEntry(takes);
    expect(addPhotos(generated.root).hidden).toBe(false);
    generated.setEntry(refuses);
    expect(addPhotos(generated.root).hidden).toBe(true);
  });
});
