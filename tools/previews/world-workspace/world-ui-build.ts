// Build mode's own parts (the building sheet, section 3; frame r13; ruling W10): the held group at the
// right, the tray of things to place along the bottom, and the names over people near what is held.
// They only draw; what a press does is build mode's (build-mode.ts), and every word is the caller's
// (build-words.mjs). Their look lives in world-ui-build.css, on world-ui.css's tokens and the redraws'
// craft (glyphRows, shade).
import { glyphRows, shade, type GlyphRow } from './world-ui.ts';
import './world-ui-build.css';

/** The held group's keys and words: 48 and 32 at 1920, never under 40 and 28 (the sheet's 1440 sizes). */
const HELD_SIZES = Object.freeze({ glyph: 'max(40px, calc(48 * var(--u)))', rowGap: 16, colGap: 20, word: 'max(28px, calc(32 * var(--u)))', nudge: -1 });

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

let serial = 0;

export interface HeldWords {
  /** The thing's name, or the question in its place ("Remove the bench?"). */
  readonly title: string;
  /** One sentence under it: a refusal (drawn in the refused ink), or the question's line. */
  readonly line?: { readonly words: string; readonly refused?: boolean } | null;
  readonly rows: readonly GlyphRow[];
}

export interface HeldGroup {
  readonly root: HTMLElement;
  /** Draws the group's words and rows, and shows it. */
  set(words: HeldWords): void;
  hide(): void;
}

/** The group at the right while something is chosen or held: its name, then a large key and one word for each thing that works now. */
export function heldGroup(): HeldGroup {
  const root = shade();
  root.classList.add('wu-held');
  root.setAttribute('role', 'region');
  const id = `wu-held-${++serial}`;
  root.setAttribute('aria-labelledby', id);
  root.hidden = true;
  return {
    root,
    set({ title, line = null, rows }) {
      const heading = element('h2', 'wu-held-title', title);
      heading.id = id;
      const parts: HTMLElement[] = [heading];
      if (line) parts.push(element('p', line.refused ? 'wu-held-line wu-refused' : 'wu-held-line', line.words));
      parts.push(glyphRows(rows, HELD_SIZES));
      root.replaceChildren(...parts);
      root.hidden = false;
    },
    hide() { root.hidden = true; },
  };
}

/** One tile of the tray: a kind to place, or the first tile that makes a creature. */
export interface TrayTile {
  readonly id: string;
  readonly name: string;
  /** Its picture once drawn (a URL), or null until then. */
  readonly picture: string | null;
  readonly make?: boolean;
  /** The first of the kinds that do not fit the world, which a wider gap sets apart (B4). */
  readonly apart?: boolean;
}

export type TrayTab = 'things' | 'creatures';

export interface TrayState {
  readonly tab: TrayTab;
  /** The open tab's tiles, or null while they are read: the tabs alone, the tray's height held. */
  readonly tiles: readonly TrayTile[] | null;
  /** The tile of the kind being held, ringed. */
  readonly held: string | null;
  /** The server cannot be reached: the tiles are drawn dimmed and do nothing. */
  readonly offline: boolean;
  /** What the open tab says when it holds nothing to place. */
  readonly empty: string;
}

export interface Tray {
  readonly root: HTMLElement;
  set(state: TrayState): void;
  /** A tile's picture, drawn after the tray. */
  picture(id: string, url: string): void;
  /** Gives a drawn tile the focus, shown and scrolled into view. */
  focus(id: string): void;
  hide(): void;
}

/** The tray along the bottom (frame r13): its two tabs, then a tile with a picture and a name for each thing to place. */
export function tray({ words, onTab, onPick }: {
  readonly words: { readonly label: string; readonly things: string; readonly creatures: string };
  readonly onTab: (tab: TrayTab) => void;
  readonly onPick: (tile: TrayTile) => void;
}): Tray {
  const root = element('section', 'wu-glass-thin wu-tray');
  root.setAttribute('aria-label', words.label);
  root.hidden = true;
  const tabs = element('div', 'wu-tray-tabs');
  tabs.setAttribute('role', 'tablist');
  const tabOf = new Map<TrayTab, HTMLButtonElement>();
  const panel = element('div', 'wu-tray-tiles');
  panel.setAttribute('role', 'tabpanel');
  panel.id = `wu-tray-${++serial}`;
  for (const [tab, name] of [['things', words.things], ['creatures', words.creatures]] as const) {
    const made = element('button', 'wu-tray-tab', name);
    made.type = 'button';
    made.setAttribute('role', 'tab');
    made.id = `${panel.id}-${tab}`;
    made.setAttribute('aria-controls', panel.id);
    made.addEventListener('click', () => onTab(tab));
    tabOf.set(tab, made);
    tabs.append(made);
  }
  // A wheel over the tiles scrolls them along; the arrows keep turning the view.
  panel.addEventListener('wheel', (event) => {
    if (panel.scrollWidth <= panel.clientWidth) return;
    event.preventDefault();
    panel.scrollBy({ left: event.deltaY + event.deltaX, behavior: 'smooth' });
  }, { passive: false });
  root.append(tabs, panel);
  const pictures = new Map<string, HTMLElement>(), buttons = new Map<string, HTMLButtonElement>();
  return {
    root,
    set({ tab, tiles, held, offline, empty }) {
      for (const [one, made] of tabOf) {
        made.setAttribute('aria-selected', String(one === tab));
        made.tabIndex = one === tab ? 0 : -1;
      }
      panel.setAttribute('aria-labelledby', `${panel.id}-${tab}`);
      root.dataset.offline = String(offline);
      pictures.clear();
      buttons.clear();
      if (tiles === null) { panel.replaceChildren(); panel.dataset.state = 'reading'; root.hidden = false; return; }
      const made = tiles.map((tile) => {
        const button = element('button', tile.make ? 'wu-tile wu-make' : 'wu-tile');
        button.type = 'button';
        button.disabled = offline;
        button.setAttribute('aria-pressed', String(tile.id === held));
        if (tile.apart) button.dataset.apart = 'true';
        const picture = element('span', 'wu-tile-picture');
        picture.setAttribute('aria-hidden', 'true');
        if (tile.make) picture.textContent = '+';
        else if (tile.picture) picture.style.backgroundImage = `url("${tile.picture}")`;
        pictures.set(tile.id, picture);
        buttons.set(tile.id, button);
        button.append(picture, element('span', 'wu-tile-name', tile.name));
        button.addEventListener('click', () => onPick(tile));
        return button;
      });
      const holdsSome = tiles.some((tile) => !tile.make);
      panel.dataset.state = holdsSome ? 'ready' : 'empty';
      panel.replaceChildren(...made, ...(holdsSome ? [] : [element('p', 'wu-tray-empty', empty)]));
      root.hidden = false;
    },
    picture(id, url) {
      const picture = pictures.get(id);
      if (picture) picture.style.backgroundImage = `url("${url}")`;
    },
    focus(id) {
      const button = buttons.get(id);
      if (!button) return;
      // Shown however the person got here, a click on Back as well as Esc (focusVisible is newer than TypeScript's DOM
      // types; a browser without it focuses the tile all the same).
      const shown: FocusOptions & { readonly focusVisible: boolean } = { preventScroll: true, focusVisible: true };
      button.focus(shown);
      button.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    },
    hide() { root.hidden = true; },
  };
}

/** A name over people near what is held: where its words stand (the top of the heads, CSS pixels). */
export interface NameNear { readonly words: string; readonly x: number; readonly y: number }

export interface NamesNear {
  readonly root: HTMLElement;
  /** Draws these names, each centred 16 reference pixels above its point; any others are hidden. */
  place(names: readonly NameNear[], scale: number): void;
  hide(): void;
}

/** The names over people near a held thing (frame r13's "Teo and Ines"): small labels on soft shades. */
export function namesNear(): NamesNear {
  const root = element('div', 'wu-names-near');
  root.setAttribute('aria-hidden', 'true');
  const labels: HTMLElement[] = [];
  return {
    root,
    place(names, scale) {
      while (labels.length < names.length) { const made = shade({ small: true }); made.classList.add('wu-name-near'); labels.push(made); root.append(made); }
      labels.forEach((label, index) => {
        const name = names[index];
        if (!name) { label.hidden = true; return; }
        if (label.textContent !== name.words) label.textContent = name.words;
        const transform = `translate3d(${name.x.toFixed(1)}px,${(name.y - 16 * scale).toFixed(1)}px,0) translate(-50%,-100%)`;
        if (label.style.transform !== transform) label.style.transform = transform;
        label.hidden = false;
      });
    },
    hide() { for (const label of labels) label.hidden = true; },
  };
}
