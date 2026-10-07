// @vitest-environment happy-dom
// Look: the sheet where a world's owner chooses which of the host's packs it is drawn in.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { authorWords, buildLookSheet, licenceWords, type LookOption } from '../src/ui/look-sheet.js';

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
