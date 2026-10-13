// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildYourWorlds, onlyUntouchedStarter } from '../src/composition/world-entry.js';
import { worldPicture } from '../src/composition/world-pictures.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

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
  it('shows a world its own kept frame first, else its recipe, else none', () => {
    expect(worldPicture(entry())).toBe('/your-worlds/market_town.jpg');
    expect(worldPicture(quiet)).toBe('/your-worlds/small_town.jpg');
    expect(worldPicture(starter())).toBeNull();
    expect(worldPicture(entry({ generatedGround: { ...entry().generatedGround!, recipeKey: 'harbour' } }))).toBeNull();
    window.localStorage.setItem(`exulanica.world-picture.v1.${entry().entryId}`, 'data:image/jpeg;base64,AAAA');
    expect(worldPicture(entry())).toBe('data:image/jpeg;base64,AAAA');
    // Anything else under the key is not a picture and is not shown.
    window.localStorage.setItem(`exulanica.world-picture.v1.${quiet.entryId}`, 'javascript:alert(1)');
    expect(worldPicture(quiet)).toBe('/your-worlds/small_town.jpg');
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
