/**
 * Look: the sheet where a world's owner chooses which of the host's style packs their world is
 * drawn in, in Your worlds' language on the dark stage.
 *
 * The chosen pack is named large with its own words, its licence and who made it, and one primary
 * action that uses it; under it a strip holds every pack the host serves, the one the world is
 * drawn in now marked Now. Behind the page is the chosen pack's picture, and nothing where a pack
 * has none. Keys: the arrows choose, Enter uses, Escape goes back; none fires while a person types.
 *
 * It builds elements and holds no client: the caller hands it the packs as the host lists them and
 * routes Use through a handler, which answers with what happened in words or a refusal's words.
 * Choosing a look changes how the world is drawn and nothing else: its places, people and history
 * stay as they are, which the sheet says once.
 */

import { el, replace, setText } from './dom.js';
import './look-sheet.css';

/** One pack the sheet offers, as the host lists it. */
export interface LookOption {
  readonly packId: string;
  readonly title: string;
  readonly description: string;
  readonly authors: readonly string[];
  readonly licence: { readonly id: string; readonly attribution: string | null };
  /** A picture of a town drawn in the pack, or null where the host serves none. */
  readonly picture: string | null;
}

export interface LookSheet {
  readonly root: HTMLElement;
  /** The packs, with the one the world is drawn in now (null where none of them). */
  show(options: readonly LookOption[], current: string | null): void;
  focus(): void;
}

/** A licence in words: CC0 says what it means; any other is named by its identifier. */
export function licenceWords(licence: LookOption['licence']): string {
  const named = licence.id === 'CC0-1.0' ? 'CC0, free to use' : `Licence ${licence.id}`;
  return licence.attribution === null ? named : `${named}, ${licence.attribution}`;
}

/** Who made a pack, in words, or empty where the host names nobody. */
export function authorWords(authors: readonly string[]): string {
  if (authors.length === 0) return '';
  if (authors.length === 1) return `By ${authors[0]}`;
  return `By ${authors.slice(0, -1).join(', ')} and ${authors[authors.length - 1]}`;
}

/** Whether a key press belongs to a field a person is typing in, where no key may act. */
const typing = (target: EventTarget | null): boolean => target instanceof HTMLElement
  && (target.isContentEditable || target.closest('input, textarea, select') !== null);

export function buildLookSheet(options: {
  /** The world's title, for the line that says where the sheet is. */
  readonly worldTitle: string;
  /** Use a pack; resolves to what happened in words, said in the sheet's status line. */
  readonly onUse: (option: LookOption) => Promise<string>;
  readonly onClose: () => void;
}): LookSheet {
  const backdrop = el('figure', { class: 'look-sheet-backdrop', 'aria-hidden': 'true' });
  const overline = el('p', { class: 'look-sheet-overline' });
  const title = el('h1', { class: 'look-sheet-title' });
  const about = el('p', { class: 'look-sheet-about' });
  const use = el('button', { type: 'button', class: 'look-sheet-use', 'data-action': 'look.use' }, [
    el('span', { text: 'Use this look' }), el('kbd', { text: '↵' }),
  ]) as HTMLButtonElement;
  const keep = el('button', { type: 'button', class: 'look-sheet-keep', 'data-action': 'look.keep' }, [
    el('span'), el('kbd', { text: 'Esc' }),
  ]) as HTMLButtonElement;
  const meta = el('p', { class: 'look-sheet-meta' });
  const status = el('p', { class: 'look-sheet-status', role: 'status', 'aria-live': 'polite' });
  const strip = el('div', { class: 'look-sheet-strip', role: 'listbox', 'aria-label': 'Looks' });
  const keys = el('p', { class: 'look-sheet-keys', 'aria-hidden': 'true' }, [
    el('span', {}, [el('kbd', { text: '← →' }), 'Choose']),
    el('span', {}, [el('kbd', { text: '↵' }), 'Use']),
    el('span', {}, [el('kbd', { text: 'Esc' }), 'Back to the world']),
  ]);
  const root = el('section', {
    class: 'look-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Look', 'data-ui-stage': 'dark', tabindex: '-1',
  }, [
    backdrop,
    el('header', { class: 'look-sheet-head' }, [
      el('p', { class: 'look-sheet-mark' }, [el('span', { class: 'look-sheet-dot', 'aria-hidden': 'true' }), `${options.worldTitle} · Look`]),
      keys,
    ]),
    el('section', { class: 'look-sheet-lede' }, [
      overline, title, about,
      el('div', { class: 'look-sheet-actions' }, [use, keep]),
      meta, status,
    ]),
    strip,
  ]);

  let shown: readonly LookOption[] = [];
  let current: string | null = null;
  let chosen = 0;
  let busy = false;
  const cards: HTMLButtonElement[] = [];

  const render = (): void => {
    const option = shown[chosen];
    if (option === undefined) return;
    const now = shown.find((held) => held.packId === current) ?? null;
    setText(overline, `Look ${chosen + 1} of ${shown.length}`);
    setText(title, option.title);
    setText(about, option.description);
    const isNow = option.packId === current;
    use.hidden = isNow;
    use.disabled = busy;
    use.querySelector('span')!.textContent = busy ? 'Working…' : 'Use this look';
    keep.querySelector('span')!.textContent = isNow ? `Keep ${option.title}` : now === null ? 'Back to the world' : `Keep ${now.title}`;
    replace(meta, [
      el('span', { text: licenceWords(option.licence) }),
      ...(option.authors.length === 0 ? [] : [el('span', { text: authorWords(option.authors) })]),
      el('span', { text: 'Your streets, people and history stay as they are' }),
    ]);
    replace(backdrop, option.picture === null ? [] : [el('img', { src: option.picture, alt: '', decoding: 'async' })]);
    backdrop.hidden = option.picture === null;
    cards.forEach((card, index) => card.setAttribute('aria-selected', String(index === chosen)));
  };

  const choose = (index: number): void => {
    chosen = Math.min(shown.length - 1, Math.max(0, index));
    render();
  };

  const run = async (): Promise<void> => {
    const option = shown[chosen];
    if (option === undefined || busy || option.packId === current) return;
    busy = true;
    status.textContent = '';
    render();
    try {
      status.textContent = await options.onUse(option);
    } finally {
      busy = false;
      render();
    }
  };

  use.addEventListener('click', () => void run());
  keep.addEventListener('click', () => options.onClose());
  root.addEventListener('keydown', (event) => {
    // The world under the sheet takes no key while the sheet is open.
    event.stopPropagation();
    if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      options.onClose();
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      choose(chosen + (event.key === 'ArrowRight' ? 1 : -1));
      cards[chosen]?.focus({ preventScroll: true });
    } else if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement && event.target !== cards[chosen])) {
      event.preventDefault();
      void run();
    }
  });

  return {
    root,
    show(next, now) {
      shown = next;
      current = now;
      cards.length = 0;
      replace(strip, next.map((option, index) => {
        const card = el('button', {
          type: 'button', role: 'option', class: 'look-sheet-card', 'data-pack-id': option.packId,
        }, [
          // A pack with no picture has no picture box: never a stand-in.
          ...(option.picture === null ? [] : [el('span', { class: 'look-sheet-picture', 'aria-hidden': 'true' }, [
            el('img', { src: option.picture, alt: '', loading: 'lazy', decoding: 'async' }),
          ])]),
          el('span', { class: 'look-sheet-caption', text: option.packId === now ? 'Now' : `Look ${index + 1}` }),
          el('span', { class: 'look-sheet-card-title', text: option.title }),
        ]) as HTMLButtonElement;
        card.addEventListener('focus', () => choose(index));
        card.addEventListener('click', () => choose(index));
        cards.push(card);
        return card;
      }));
      const at = next.findIndex((option) => option.packId === now);
      choose(at < 0 ? 0 : at);
    },
    focus() {
      (cards[chosen] ?? root).focus({ preventScroll: true });
    },
  };
}
