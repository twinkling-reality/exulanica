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
 *
 * A world drawn in an earlier version of a pack keeps it: the host still serves every version it
 * published, and a newer one is only ever a choice. The sheet then shows that version as Now, its
 * own card, beside the pack's current version, which says what changed and offers itself by number.
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
  /** The version the host offers, its current one; absent where the sheet need not name it. */
  readonly version?: number;
  /** The host's note on what this version changed, for a person; null or absent for none. */
  readonly changes?: string | null;
}

/** The earlier version of an offered pack a world is drawn in now. */
export interface EarlierLook {
  readonly packId: string;
  readonly version: number;
  /** That version's own picture, or null where it has none. */
  readonly picture: string | null;
}

/** How the world is drawn now, where the packs alone cannot say it. */
export interface LookNow {
  /** The world is drawn in an earlier version of one of the packs. */
  readonly earlier?: EarlierLook | null;
  /** One plain sentence said in the sheet's status line on opening, such as a look the host does not serve. */
  readonly notice?: string | null;
}

export interface LookSheet {
  readonly root: HTMLElement;
  /** Show the world itself behind the sheet (true) or the packs' pictures (false). */
  setLive(live: boolean): void;
  /**
   * The packs, with the one the world is drawn in now (null where none of them), and, where it is
   * an earlier version of one, which.
   */
  show(options: readonly LookOption[], current: string | null, now?: LookNow): void;
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

/** How long a person rests on a look before the world behind the sheet is drawn in it. */
export const BROWSE_PAUSE_MS = 180;

/** Whether a key press belongs to a field a person is typing in, where no key may act. */
const typing = (target: EventTarget | null): boolean => target instanceof HTMLElement
  && (target.isContentEditable || target.closest('input, textarea, select') !== null);

export function buildLookSheet(options: {
  /** The world's title, for the line that says where the sheet is. */
  readonly worldTitle: string;
  /**
   * Use a pack; resolves to what happened in words, said in the sheet's status line. `say` puts
   * words there while it works, such as that the world is being drawn in the new look.
   */
  readonly onUse: (option: LookOption, say: (words: string) => void) => Promise<string>;
  readonly onClose: () => void;
  /**
   * Draw the world behind the sheet in the look being looked at, while a person moves through
   * them: `now` true for the look the world is drawn in now, exactly as it is drawn (an earlier
   * version included), else the option's current version. Given, the sheet opens see-through on
   * the world rather than over a picture of it.
   */
  readonly onBrowse?: (option: LookOption, now: boolean) => void;
  /**
   * Words for a sheet that only chooses (a town not made yet): the primary action's words and the
   * caption of the look chosen so far, in place of "Use this look" and "Now".
   */
  readonly choosing?: { readonly use: string; readonly now: string };
}): LookSheet {
  const backdrop = el('figure', { class: 'look-sheet-backdrop', 'aria-hidden': 'true' });
  const overline = el('p', { class: 'look-sheet-overline' });
  const title = el('h1', { class: 'look-sheet-title' });
  const about = el('p', { class: 'look-sheet-about' });
  const use = el('button', { type: 'button', class: 'look-sheet-use', 'data-action': 'look.use' }, [
    el('span', { text: options.choosing?.use ?? 'Use this look' }), el('kbd', { text: '↵' }),
  ]) as HTMLButtonElement;
  const keep = el('button', { type: 'button', class: 'look-sheet-keep', 'data-action': 'look.keep' }, [
    el('span'), el('kbd', { text: 'Esc' }),
  ]) as HTMLButtonElement;
  const meta = el('p', { class: 'look-sheet-meta' });
  const status = el('p', { class: 'look-sheet-status', role: 'status', 'aria-live': 'polite' });
  const strip = el('div', { class: 'look-sheet-strip', role: 'listbox', 'aria-label': 'Looks' });
  const keys = el('p', { class: 'look-sheet-keys', 'aria-hidden': 'true' }, [
    el('span', {}, [el('kbd', { text: '← →' }), 'Choose']),
    el('span', {}, [el('kbd', { text: '↵' }), options.choosing === undefined ? 'Use' : 'Choose this look']),
    el('span', {}, [el('kbd', { text: 'Esc' }), options.choosing === undefined ? 'Back to the world' : 'Back']),
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

  /**
   * One card in the strip: a pack at its current version, or the earlier version the world is
   * drawn in now (`earlier`), which can be kept but not used again.
   */
  interface Card {
    readonly option: LookOption;
    readonly earlier: EarlierLook | null;
    /** The pack's place among the packs, counted from 1, shared by both versions of one. */
    readonly place: number;
  }
  let shown: readonly LookOption[] = [];
  let entries: readonly Card[] = [];
  let live = options.onBrowse !== undefined;
  root.dataset['live'] = String(live);
  let current: string | null = null;
  let earlier: EarlierLook | null = null;
  let chosen = 0;
  let busy = false;
  const cards: HTMLButtonElement[] = [];

  /** Whether a card is the look the world is drawn in now. */
  const isNowCard = (card: Card): boolean => card.option.packId === current && (earlier === null || card.earlier !== null);
  /** The version words a card's look is named by, where the world is in an earlier version of its pack. */
  const versioned = (card: Card): boolean => earlier !== null && card.option.packId === earlier.packId;
  const nowWords = (): string => {
    const now = entries.find(isNowCard);
    if (now === undefined) return 'Back to the world';
    return now.earlier !== null ? `Keep version ${now.earlier.version}` : `Keep ${now.option.title}`;
  };

  const render = (): void => {
    const card = entries[chosen];
    if (card === undefined) return;
    const option = card.option;
    setText(overline, `Look ${card.place} of ${shown.length}`);
    setText(title, option.title);
    const isNow = isNowCard(card);
    // A pack whose earlier version the world keeps says which version each card is, and what the
    // newer one changed, under its own words.
    const versionLine = !versioned(card) || earlier === null ? null : [
      ...(card.earlier === null ? [] : [`This world is drawn in version ${card.earlier.version}.`]),
      option.version === undefined ? 'A newer version is here.' : `Version ${option.version} is here.`,
      ...(option.changes == null ? [] : [option.changes]),
    ].join(' ');
    replace(about, versionLine === null ? [option.description] : [
      option.description, el('span', { class: 'look-sheet-version', text: versionLine }),
    ]);
    use.hidden = isNow;
    use.disabled = busy;
    use.querySelector('span')!.textContent = busy ? 'Working…'
      : versioned(card) && option.version !== undefined ? `Use version ${option.version}`
        : options.choosing?.use ?? 'Use this look';
    keep.querySelector('span')!.textContent = nowWords();
    replace(meta, [
      el('span', { text: licenceWords(option.licence) }),
      ...(option.authors.length === 0 ? [] : [el('span', { text: authorWords(option.authors) })]),
      el('span', { text: 'Your places, people and history stay as they are' }),
    ]);
    const picture = card.earlier !== null ? card.earlier.picture : option.picture;
    replace(backdrop, live || picture === null ? [] : [el('img', { src: picture, alt: '', decoding: 'async' })]);
    backdrop.hidden = live || picture === null;
    cards.forEach((card, index) => card.setAttribute('aria-selected', String(index === chosen)));
  };

  // The look a person moves to is drawn behind the sheet once they pause on it, so passing over
  // a look on the way to another draws nothing.
  let browseTimer: number | null = null;
  const browse = (): void => {
    if (browseTimer !== null) window.clearTimeout(browseTimer);
    const card = entries[chosen];
    if (!live || options.onBrowse === undefined || card === undefined) return;
    browseTimer = window.setTimeout(() => { browseTimer = null; options.onBrowse?.(card.option, isNowCard(card)); }, BROWSE_PAUSE_MS);
  };
  const choose = (index: number): void => {
    const next = Math.min(entries.length - 1, Math.max(0, index));
    const moved = next !== chosen;
    chosen = next;
    render();
    if (moved) browse();
  };

  const run = async (): Promise<void> => {
    const card = entries[chosen];
    if (card === undefined || busy || isNowCard(card)) return;
    busy = true;
    status.textContent = '';
    render();
    try {
      status.textContent = await options.onUse(card.option, (words) => { status.textContent = words; });
    } finally {
      busy = false;
      render();
      // Use is hidden once its look is Now; the keyboard stays in the sheet, on the chosen card.
      if (!root.contains(document.activeElement) || use.hidden) cards[chosen]?.focus({ preventScroll: true });
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
    show(next, now, how) {
      shown = next;
      current = now;
      earlier = how?.earlier != null && how.earlier.packId === now && next.some((option) => option.packId === now) ? how.earlier : null;
      // The earlier version the world keeps comes just before its pack's current version.
      entries = next.flatMap((option, index): Card[] => {
        const pack: Card = { option, earlier: null, place: index + 1 };
        return earlier !== null && option.packId === earlier.packId ? [{ option, earlier, place: index + 1 }, pack] : [pack];
      });
      cards.length = 0;
      replace(strip, entries.map((card, index) => {
        const picture = card.earlier !== null ? card.earlier.picture : card.option.picture;
        const caption = isNowCard(card)
          ? card.earlier !== null ? `Now · version ${card.earlier.version}` : options.choosing?.now ?? 'Now'
          : versioned(card) && card.option.version !== undefined ? `Version ${card.option.version}` : `Look ${card.place}`;
        const button = el('button', {
          type: 'button', role: 'option', class: 'look-sheet-card', 'data-pack-id': card.option.packId,
          ...(card.earlier === null ? {} : { 'data-version': String(card.earlier.version) }),
        }, [
          // A pack with no picture has no picture box: never a stand-in.
          ...(picture === null ? [] : [el('span', { class: 'look-sheet-picture', 'aria-hidden': 'true' }, [
            el('img', { src: picture, alt: '', loading: 'lazy', decoding: 'async' }),
          ])]),
          el('span', { class: 'look-sheet-caption', text: caption }),
          el('span', { class: 'look-sheet-card-title', text: card.option.title }),
        ]) as HTMLButtonElement;
        button.addEventListener('focus', () => choose(index));
        button.addEventListener('click', () => choose(index));
        cards.push(button);
        return button;
      }));
      // Opening on the look drawn now draws nothing new.
      const at = entries.findIndex(isNowCard);
      chosen = at < 0 ? 0 : at;
      if (how?.notice != null) status.textContent = how.notice;
      render();
    },
    focus() {
      (cards[chosen] ?? root).focus({ preventScroll: true });
    },
    setLive(next) {
      live = next && options.onBrowse !== undefined;
      root.dataset['live'] = String(live);
      render();
    },
  };
}

export interface LookRow {
  readonly root: HTMLElement;
  /** Show the look a new town will be made in, with a line on why it is this one. */
  show(option: LookOption, line: string): void;
}

/**
 * The look a town not made yet will be drawn in, beside its values in Create a world: its picture,
 * title and a line, and Change look, which opens the Look sheet to choose another.
 */
export function buildLookRow(onChange: () => void): LookRow {
  const picture = el('span', { class: 'look-row-picture', 'aria-hidden': 'true' });
  const title = el('span', { class: 'look-row-title' });
  const line = el('span', { class: 'look-row-line' });
  const change = el('button', { type: 'button', class: 'look-row-change', 'data-action': 'look.change', text: 'Change look' });
  change.addEventListener('click', onChange);
  const root = el('section', { class: 'look-row', 'aria-label': 'Look', hidden: true }, [
    el('p', { class: 'look-row-label', text: 'Look' }),
    el('div', { class: 'look-row-body' }, [picture, el('span', { class: 'look-row-words' }, [title, line]), change]),
  ]);
  return {
    root,
    show(option, words) {
      root.hidden = false;
      setText(title, option.title);
      setText(line, words);
      replace(picture, option.picture === null ? [] : [el('img', { src: option.picture, alt: '', decoding: 'async' })]);
      picture.hidden = option.picture === null;
    },
  };
}
