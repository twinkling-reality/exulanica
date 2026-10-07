// @vitest-environment happy-dom
// Look: the sheet where a world's owner chooses which of the host's packs it is drawn in.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BROWSE_PAUSE_MS, authorWords, buildLookRow, buildLookSheet, licenceWords, type LookOption } from '../src/ui/look-sheet.js';

const pack = (packId: string, title: string, picture: string | null = `/${packId}.jpg`): LookOption => ({
  packId, title, description: `${title}, in its own words.`, authors: ['Exulanica'],
  licence: { id: 'CC0-1.0', attribution: null }, picture,
});
const PACKS = [pack('cozy', 'Cozy town'), pack('finished', 'Finished town'), pack('toon', 'Toon town', null)];

let built: ReturnType<typeof buildLookSheet>;
const press = (target: Element, key: string): void => {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
};

const sheet = (onUse = vi.fn(async (option: LookOption) => {
  // As the page does once it is saved: the chosen look becomes Now.
  built.show(PACKS, option.packId);
  return `Now drawn in ${option.title}.`;
})) => {
  const onClose = vi.fn();
  built = buildLookSheet({ worldTitle: 'Saturday market', onUse, onClose });
  document.body.replaceChildren(built.root);
  built.show(PACKS, 'cozy');
  return { ...built, onUse, onClose };
};
const text = (root: HTMLElement, selector: string) => root.querySelector(selector)!.textContent;
const use = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('[data-action="look.use"]')!;

afterEach(() => document.body.replaceChildren());

describe('the Look sheet', () => {
  it('opens on the look the world is drawn in now, which it does not offer to use again', () => {
    const { root } = sheet();
    expect(text(root, '.look-sheet-title')).toBe('Cozy town');
    expect(text(root, '.look-sheet-overline')).toBe('Look 1 of 3');
    expect([...root.querySelectorAll('.look-sheet-caption')].map((node) => node.textContent)).toEqual(['Now', 'Look 2', 'Look 3']);
    expect(use(root).hidden).toBe(true);
    expect(text(root, '[data-action="look.keep"] span')).toBe('Keep Cozy town');
  });

  it('chooses with the arrows, uses with Enter, and says what came of it', async () => {
    const { root, onUse } = sheet();
    press(root, 'ArrowRight');
    expect(text(root, '.look-sheet-title')).toBe('Finished town');
    expect(use(root).hidden).toBe(false);
    expect(text(root, '[data-action="look.keep"] span')).toBe('Keep Cozy town');
    press(root, 'Enter');
    await vi.waitFor(() => expect(text(root, '.look-sheet-status')).toBe('Now drawn in Finished town.'));
    // Use went with the look becoming Now, and the keyboard stayed in the sheet.
    expect(root.contains(document.activeElement)).toBe(true);
    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse.mock.calls[0]![0].packId).toBe('finished');
  });

  it('goes back with Escape, and no key acts while a person types', () => {
    const { root, onClose, onUse } = sheet();
    const field = document.createElement('input');
    root.append(field);
    press(field, 'ArrowRight');
    press(field, 'Enter');
    press(field, 'Escape');
    expect(text(root, '.look-sheet-title')).toBe('Cozy town');
    expect(onUse).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    press(root, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows a pack\'s own picture behind the page, and nothing for a pack with none', () => {
    const { root } = sheet();
    const backdrop = root.querySelector<HTMLElement>('.look-sheet-backdrop')!;
    expect(backdrop.hidden).toBe(false);
    expect(backdrop.querySelector('img')!.getAttribute('src')).toBe('/cozy.jpg');
    press(root, 'ArrowRight');
    press(root, 'ArrowRight');
    expect(backdrop.hidden).toBe(true);
    expect(backdrop.querySelector('img')).toBeNull();
  });

  it('names a licence and who made a pack in words', () => {
    expect(licenceWords({ id: 'CC0-1.0', attribution: null })).toBe('CC0, free to use');
    expect(licenceWords({ id: 'CC-BY-4.0', attribution: 'Ada Lovelace' })).toBe('Licence CC-BY-4.0, Ada Lovelace');
    expect(authorWords([])).toBe('');
    expect(authorWords(['Exulanica'])).toBe('By Exulanica');
    expect(authorWords(['A', 'B', 'C'])).toBe('By A, B and C');
  });
});

describe('using a look that takes a while', () => {
  it('says what it is doing while it works, then what came of it, and offers nothing twice meanwhile', async () => {
    let finish: (words: string) => void = () => undefined;
    const onUse = vi.fn((option: LookOption, say: (words: string) => void) => {
      say(`Drawing the world in ${option.title}…`);
      return new Promise<string>((resolve) => { finish = resolve; });
    });
    const built = buildLookSheet({ worldTitle: 'Saturday market', onUse, onClose: vi.fn() });
    document.body.replaceChildren(built.root);
    built.show(PACKS, 'cozy');
    press(built.root, 'ArrowRight');
    press(built.root, 'Enter');
    await vi.waitFor(() => expect(text(built.root, '.look-sheet-status')).toBe('Drawing the world in Finished town…'));
    expect(use(built.root).disabled).toBe(true);
    press(built.root, 'Enter');
    expect(onUse).toHaveBeenCalledTimes(1);
    finish('The world is now drawn in Finished town.');
    await vi.waitFor(() => expect(text(built.root, '.look-sheet-status')).toBe('The world is now drawn in Finished town.'));
  });
});

describe('browsing looks on the world itself', () => {
  it('draws the world in a look once a person rests on it, never on opening or in passing', () => {
    vi.useFakeTimers();
    try {
      const onBrowse = vi.fn();
      const live = buildLookSheet({ worldTitle: 'Saturday market', onUse: vi.fn(async () => ''), onClose: vi.fn(), onBrowse });
      document.body.replaceChildren(live.root);
      live.show(PACKS, 'cozy');
      vi.advanceTimersByTime(BROWSE_PAUSE_MS * 2);
      expect(onBrowse).not.toHaveBeenCalled();
      expect(live.root.dataset['live']).toBe('true');
      // See-through on the world: no picture behind the page.
      expect(live.root.querySelector<HTMLElement>('.look-sheet-backdrop')!.hidden).toBe(true);
      press(live.root, 'ArrowRight');
      press(live.root, 'ArrowRight');
      vi.advanceTimersByTime(BROWSE_PAUSE_MS + 1);
      expect(onBrowse).toHaveBeenCalledTimes(1);
      expect(onBrowse.mock.calls[0]![0].packId).toBe('toon');
      // Without the world behind it, the sheet shows the packs' pictures and draws nothing.
      live.setLive(false);
      press(live.root, 'ArrowLeft');
      vi.advanceTimersByTime(BROWSE_PAUSE_MS + 1);
      expect(onBrowse).toHaveBeenCalledTimes(1);
      expect(live.root.querySelector<HTMLElement>('.look-sheet-backdrop')!.hidden).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('is never live without a way to draw the world', () => {
    const { root } = sheet();
    expect(root.dataset['live']).toBe('false');
  });
});

describe('the look of a town not made yet', () => {
  it('says the look in the row, and Change look opens the sheet to choose another', () => {
    const onChange = vi.fn();
    const row = buildLookRow(onChange);
    document.body.replaceChildren(row.root);
    expect(row.root.hidden).toBe(true);
    row.show(PACKS[0]!, 'The look this server draws new towns in.');
    expect(row.root.hidden).toBe(false);
    expect(row.root.querySelector('.look-row-title')!.textContent).toBe('Cozy town');
    expect(row.root.querySelector('img')!.getAttribute('src')).toBe('/cozy.jpg');
    row.show(PACKS[2]!, 'Your choice.');
    expect(row.root.querySelector<HTMLElement>('.look-row-picture')!.hidden).toBe(true);
    row.root.querySelector<HTMLButtonElement>('[data-action="look.change"]')!.click();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('chooses rather than uses, in its own words', () => {
    const choosing = buildLookSheet({
      worldTitle: 'A new town', onUse: vi.fn(async () => ''), onClose: vi.fn(),
      choosing: { use: 'Choose this look', now: 'Chosen' },
    });
    document.body.replaceChildren(choosing.root);
    choosing.show(PACKS, 'cozy');
    expect(choosing.root.querySelector('.look-sheet-caption')!.textContent).toBe('Chosen');
    expect(choosing.root.querySelector('[data-action="look.use"] span')!.textContent).toBe('Choose this look');
    expect(choosing.root.querySelector('.look-sheet-keys')!.textContent).toContain('Choose this look');
    expect(choosing.root.querySelector('.look-sheet-keys')!.textContent).not.toContain('Back to the world');
    // Choosing draws nothing: there is no world yet.
    expect(choosing.root.dataset['live']).toBe('false');
  });
});

describe('a world drawn in an earlier version of its look', () => {
  const VERSIONED = [
    { ...pack('cozy', 'Cozy town'), version: 3, changes: 'Shaded roads are grey again.' },
    { ...pack('finished', 'Finished town'), version: 1, changes: null },
  ];
  const EARLIER = { packId: 'cozy', version: 2, picture: '/cozy-2.jpg' };
  const captions = (root: HTMLElement) => [...root.querySelectorAll('.look-sheet-caption')].map((node) => node.textContent);

  it('shows that version as Now, its own card, before the current version, which says what changed', async () => {
    const onUse = vi.fn(async (_option: LookOption) => '');
    const versioned = buildLookSheet({ worldTitle: 'Saturday market', onUse, onClose: vi.fn() });
    document.body.replaceChildren(versioned.root);
    versioned.show(VERSIONED, 'cozy', { earlier: EARLIER });
    const { root } = versioned;
    expect(captions(root)).toEqual(['Now · version 2', 'Version 3', 'Look 2']);
    expect(text(root, '.look-sheet-overline')).toBe('Look 1 of 2');
    expect(text(root, '.look-sheet-version')).toBe('This world is drawn in version 2. Version 3 is here. Shaded roads are grey again.');
    expect(use(root).hidden).toBe(true);
    expect(text(root, '[data-action="look.keep"] span')).toBe('Keep version 2');
    // Its own picture, not the current version's.
    expect(root.querySelector('.look-sheet-backdrop img')!.getAttribute('src')).toBe('/cozy-2.jpg');

    press(root, 'ArrowRight');
    expect(text(root, '.look-sheet-overline')).toBe('Look 1 of 2');
    expect(text(root, '.look-sheet-version')).toBe('Version 3 is here. Shaded roads are grey again.');
    expect(use(root).hidden).toBe(false);
    expect(text(root, '[data-action="look.use"] span')).toBe('Use version 3');
    expect(text(root, '[data-action="look.keep"] span')).toBe('Keep version 2');
    expect(root.querySelector('.look-sheet-backdrop img')!.getAttribute('src')).toBe('/cozy.jpg');
    press(root, 'Enter');
    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse.mock.calls[0]![0]).toMatchObject({ packId: 'cozy', version: 3 });
    await vi.waitFor(() => expect(use(root).disabled).toBe(false));

    // Another pack names no version.
    press(root, 'ArrowRight');
    expect(root.querySelector('.look-sheet-version')).toBeNull();
    expect(text(root, '[data-action="look.use"] span')).toBe('Use this look');
  });

  it('draws the world exactly as it is now on its Now card, and the current version on the next', () => {
    vi.useFakeTimers();
    try {
      const onBrowse = vi.fn();
      const live = buildLookSheet({ worldTitle: 'Saturday market', onUse: vi.fn(async () => ''), onClose: vi.fn(), onBrowse });
      document.body.replaceChildren(live.root);
      live.show(VERSIONED, 'cozy', { earlier: EARLIER });
      press(live.root, 'ArrowRight');
      vi.advanceTimersByTime(BROWSE_PAUSE_MS + 1);
      press(live.root, 'ArrowLeft');
      vi.advanceTimersByTime(BROWSE_PAUSE_MS + 1);
      expect(onBrowse.mock.calls.map(([option, now]) => [option.packId, now])).toEqual([['cozy', false], ['cozy', true]]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('marks nothing as Now, and says so, for a look the host does not serve', () => {
    const { root, show } = sheet();
    show(VERSIONED, null, { notice: 'This world names a look this server does not offer.' });
    expect(captions(root)).toEqual(['Look 1', 'Look 2']);
    expect(text(root, '.look-sheet-status')).toBe('This world names a look this server does not offer.');
    expect(text(root, '[data-action="look.keep"] span')).toBe('Back to the world');
    expect(use(root).hidden).toBe(false);
  });
});
