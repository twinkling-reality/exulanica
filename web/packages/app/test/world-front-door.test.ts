// @vitest-environment happy-dom
// What a world's card offers on the world workspace's front door (tools/previews/world-workspace/front-door-card.ts,
// which front-door.ts runs over the app's Your worlds): Open and Details only. The app's View values, its button and
// its V, opens the saved values whose "Create another from these inputs" is the shell's own Create, a way back into
// the shell, so the front door leaves it out.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildYourWorlds } from '../src/composition/world-entry.js';
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
