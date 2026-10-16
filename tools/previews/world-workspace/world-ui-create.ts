// Making a world's own parts on the front door's light plane (DESIGN's frames 20 to 22, rulings N1
// to N20): the page, the sentence field and its count, the Create orb, the cards to start from, the
// quiet command and the key row, the steps and the made note. They only draw; what a press does is
// the caller's, and which key does what is create-steps.mjs's createKey. Their look lives in
// world-ui-create.css, from world-ui.css's tokens and front-door.css's materials.
import { orb, stepList, type Step } from './world-ui.ts';
import { CREATE_WORDS, countWords } from './create-words.mjs';
import './front-door.css';
import './world-ui-create.css';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

let serial = 0;
const nextId = (stem: string): string => `${stem}-${++serial}`;

export type LightForm = 'create' | 'creating';

export interface LightPage {
  readonly root: HTMLElement;
  /** The title and what follows it: frame 20's column at 110, 196, frame 21's head at 110, 192. */
  readonly head: HTMLElement;
  /** Frame 20's cards (left 110, bottom 118); frame 21's steps (left 110, top 520). */
  readonly lower: HTMLElement;
  /** The quiet command's place (left 100, bottom 34). */
  readonly quiet: HTMLElement;
  /** The key row at the bottom right (N5). */
  readonly keys: HTMLElement;
  /** The stepped surface, which grows to hold every line under the field (N24). */
  readonly surface: HTMLElement;
  /** Swaps frame 20 for frame 21 in place (N18), the picture kept. */
  form(next: LightForm): void;
  /** The chosen world's still picture (N18); null leaves the white plane. */
  picture(address: string | null): void;
}

/**
 * The light page (frames 20 and 21): the chosen world's still picture under its veils, the
 * wordmark and the stepped surface, 930 by 470 on frame 20 and 1060 by 300 on frame 21. A modal
 * dialog named by `labelledBy` (the caller's title).
 */
export function lightPage({ form = 'create', picture = null, labelledBy }: { readonly form?: LightForm; readonly picture?: string | null; readonly labelledBy?: string } = {}): LightPage {
  const root = element('section', 'wu-light ux-noveuis');
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  if (labelledBy) root.setAttribute('aria-labelledby', labelledBy);
  root.dataset.form = form;
  const world = element('div', 'wu-light-world'), veil = element('div', 'wu-light-veil'), surface = element('div', 'wu-light-surface');
  for (const quietPart of [world, veil, surface]) quietPart.setAttribute('aria-hidden', 'true');
  const wordmark = element('p', 'wu-light-wordmark', CREATE_WORDS.wordmark);
  const head = element('div', 'wu-light-head'), lower = element('div', 'wu-light-lower');
  const quiet = element('div', 'wu-light-quiet'), keys = element('div', 'wu-light-keys');
  root.append(world, veil, surface, wordmark, head, lower, keys, quiet);
  const page: LightPage = {
    root, head, lower, quiet, keys, surface,
    form(next) { root.dataset.form = next; },
    picture(address) { world.style.backgroundImage = address ? `url(${JSON.stringify(address)})` : ''; },
  };
  page.picture(picture);
  return page;
}

/** A section label on the light plane ("Describe it", "Or start from", "Creating your world"). */
export function lightLabel(words: string, forId?: string): HTMLElement {
  const made = forId ? element('label', 'wu-light-label', words) : element('p', 'wu-light-label', words);
  if (forId && made instanceof HTMLLabelElement) made.htmlFor = forId;
  return made;
}

/**
 * A line on the light plane: the price line, the starts left, the leave line, the spend; `refused`
 * in the light refusal ink (N9). A polite status where it changes while the page is open.
 */
export function lightLine(words: string, { tone = 'plain', live = false }: { readonly tone?: 'plain' | 'refused'; readonly live?: boolean } = {}): HTMLParagraphElement {
  const line = element('p', 'wu-light-line', words);
  if (tone === 'refused') line.dataset.tone = 'refused';
  if (live) line.setAttribute('role', 'status');
  return line;
}

export interface SentenceField {
  readonly root: HTMLElement;
  /** "Describe it", the field's label; sentenceRow sets it over the row of field and orb. */
  readonly label: HTMLElement;
  readonly field: HTMLTextAreaElement;
  readonly count: HTMLElement;
  /** Puts words in the field (kept from last time, N6) and redraws the count. */
  set(words: string): void;
}

/**
 * The sentence field and its count (N1, N2): it takes at most `limit` characters (the offer's
 * `description_characters`); the count reads "86 of 1000" from the first letter and is gone while
 * the field is empty, when today's placeholder shows. `onInput` hears every change.
 */
export function sentenceField({ limit, value = '', onInput }: { readonly limit: number; readonly value?: string; readonly onInput?: (words: string) => void }): SentenceField {
  const root = element('div', 'wu-light-field-box');
  const id = nextId('wu-sentence');
  const rim = element('div', 'wu-light-field-rim');
  const field = element('textarea', 'wu-light-field');
  field.id = id;
  field.maxLength = limit;
  field.rows = 3;
  field.placeholder = CREATE_WORDS.placeholder;
  field.spellcheck = true;
  const count = element('div', 'wu-light-count');
  count.id = nextId('wu-sentence-count');
  field.setAttribute('aria-describedby', count.id);
  rim.append(field);
  const label = lightLabel(CREATE_WORDS.describeIt, id);
  root.append(rim, count);
  const redraw = (): void => {
    const words = countWords(field.value.length, limit);
    // Empty, the count keeps its line (N23): it is hidden from sight and from a screen reader.
    count.textContent = words ?? '\u00a0';
    if (words === null) { count.dataset.empty = 'true'; count.setAttribute('aria-hidden', 'true'); }
    else { delete count.dataset.empty; count.removeAttribute('aria-hidden'); }
    if (field.value.length >= limit) count.dataset.full = 'true'; else delete count.dataset.full;
  };
  field.addEventListener('input', () => { redraw(); onInput?.(field.value); });
  const shown: SentenceField = { root, label, field, count, set(words) { field.value = words.slice(0, limit); redraw(); } };
  shown.set(value);
  return shown;
}

/**
 * The Create orb at 84 px (5.8, the front door's orb): one button named "Create". Dimmed and out of
 * the Tab order while it cannot start (N2: until the price line shows and a word is typed).
 */
export function createOrb({ onPress, ready = false }: { readonly onPress: () => void; readonly ready?: boolean }): HTMLButtonElement {
  const button = orb({ word: CREATE_WORDS.create, onPress, disabled: !ready });
  button.classList.add('wu-light-orb');
  return button;
}

/** Lets the orb be pressed, or dims it and takes it out of the Tab order. */
export function setOrbReady(button: HTMLButtonElement, ready: boolean): void {
  if (button.disabled === !ready) return;
  button.disabled = !ready;
}

/** "Describe it" 36 under the title and 12 over the row of field and orb, tops aligned, 26 apart (frame 20). */
export function sentenceRow(field: SentenceField, button: HTMLButtonElement): HTMLDivElement {
  const part = element('div', 'wu-light-sentence-part');
  const row = element('div', 'wu-light-row');
  row.append(field.root, button);
  part.append(field.label, row);
  return part;
}

export interface FilmCardWords {
  readonly key: string;
  readonly name: string;
  readonly sub: string;
  /** A served picture's address; null draws the quiet tile; Blank draws its own. */
  readonly picture: string | null;
  readonly blank?: boolean;
}

/** One card to start from (N3): a button named by its name, its sub-line describing it. */
export function filmCard(card: FilmCardWords, onStart: (key: string) => void): HTMLButtonElement {
  const button = element('button', 'wu-film-card');
  button.type = 'button';
  button.dataset.key = card.key;
  button.dataset.picture = card.blank ? 'blank' : card.picture ? 'served' : 'none';
  const picture = element('span', 'wu-film-picture');
  picture.setAttribute('aria-hidden', 'true');
  if (!card.blank && card.picture) picture.style.backgroundImage = `url(${JSON.stringify(card.picture)})`;
  // A card with no picture is the quiet card: its name on the surface's material (N23).
  else if (!card.blank) picture.textContent = card.name;
  const name = element('span', 'wu-film-name', card.name);
  name.id = nextId('wu-film-name');
  const sub = element('span', 'wu-film-sub', card.sub);
  sub.id = nextId('wu-film-sub');
  button.setAttribute('aria-labelledby', name.id);
  button.setAttribute('aria-describedby', sub.id);
  button.setAttribute('aria-keyshortcuts', 'Enter');
  button.append(picture, name, sub);
  button.addEventListener('click', () => onStart(card.key));
  return button;
}

export interface FilmStrip {
  readonly root: HTMLElement;
  readonly cards: readonly HTMLButtonElement[];
  /** Marks card `index` chosen (aria-current, 260 wide), the one Tab stop of the row; `focus` moves the focus to it. */
  choose(index: number, focus?: boolean): void;
  readonly chosen: number;
}

/**
 * "Or start from" and its row of cards, Blank last (N3): one Tab stop, the chosen card; arrows move
 * the choice (the caller's, by createKey). More cards than fit scroll sideways with faded edges.
 */
export function filmStrip(cards: readonly FilmCardWords[], onStart: (key: string) => void, { labelledBy }: { readonly labelledBy?: string } = {}): FilmStrip {
  const root = element('div', 'wu-film');
  // One group: the served cards in a strip that scrolls, then Blank outside it, always in view (N27).
  const row = element('div', 'wu-film-row');
  row.setAttribute('role', 'group');
  const scroller = element('div', 'wu-film-strip');
  const buttons = cards.map((card) => filmCard(card, onStart));
  scroller.append(...buttons.filter((_, at) => cards[at]?.blank !== true));
  row.append(scroller, ...buttons.filter((_, at) => cards[at]?.blank === true));
  // Labelled by a sentence the page already says ("... start from these:", N24), with no heading of its own.
  if (labelledBy) {
    row.setAttribute('aria-labelledby', labelledBy);
    root.append(row);
  } else {
    const heading = lightLabel(CREATE_WORDS.orStartFrom);
    heading.id = nextId('wu-film-label');
    row.setAttribute('aria-labelledby', heading.id);
    root.append(heading, row);
  }
  const edges = (): void => {
    scroller.dataset.moreBefore = String(scroller.scrollLeft > 1);
    scroller.dataset.moreAfter = String(scroller.scrollLeft + scroller.clientWidth < scroller.scrollWidth - 1);
  };
  scroller.addEventListener('scroll', edges, { passive: true });
  // Measured once the strip is laid out, and again whenever its size changes (N27): the fade shows
  // from the first paint, not only after a scroll.
  if (typeof ResizeObserver === 'function') new ResizeObserver(edges).observe(scroller);
  let chosen = 0;
  const strip: FilmStrip = {
    root,
    cards: buttons,
    get chosen() { return chosen; },
    choose(index, focus = false) {
      chosen = Math.max(0, Math.min(buttons.length - 1, index));
      buttons.forEach((button, at) => {
        button.tabIndex = at === chosen ? 0 : -1;
        if (at === chosen) button.setAttribute('aria-current', 'true'); else button.removeAttribute('aria-current');
      });
      const card = buttons[chosen];
      if (focus && card) { card.focus({ preventScroll: true }); card.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); }
      edges();
    },
  };
  strip.choose(0);
  return strip;
}

/** Where Esc's command is drawn: the light plane's quiet place (N5, as amended) or inside a row. */
export type QuietPlace = 'quiet' | 'row';

/**
 * The quiet command (5.11): one button named by its word ("Your worlds"), its key as
 * aria-keyshortcuts and its cap hidden. `place` says where it is drawn; DESIGN's amended N5 puts
 * Esc at left 100, bottom 34 on frame 20 and 21, so 'quiet' is the default.
 */
export function quietCommand({ key = 'Esc', word = CREATE_WORDS.yourWorlds, shortcut = 'Escape', onPress, place = 'quiet' }: {
  readonly key?: string; readonly word?: string; readonly shortcut?: string; readonly onPress: () => void; readonly place?: QuietPlace;
}): HTMLButtonElement {
  const button = element('button', 'wu-qcmd');
  button.type = 'button';
  button.dataset.place = place;
  const cap = element('span', 'wu-qcmd-key', key);
  cap.setAttribute('aria-hidden', 'true');
  button.append(cap, element('span', 'wu-qcmd-word', word));
  button.setAttribute('aria-keyshortcuts', shortcut);
  button.addEventListener('click', () => onPress());
  return button;
}

/** Which keys the row draws now (K6: a key is drawn only where it works). */
export interface CreateKeys { readonly create: boolean; readonly start: boolean }

/** A key the row says: a cap and a word, not a button (the orb and the cards are the buttons). */
function lightHint(key: string, word: string, shortcut: string): HTMLSpanElement {
  const hint = element('span', 'wu-qcmd wu-light-hint');
  const cap = element('span', 'wu-qcmd-key', key);
  cap.setAttribute('aria-hidden', 'true');
  hint.append(cap, element('span', 'wu-qcmd-word', word));
  hint.setAttribute('aria-keyshortcuts', shortcut);
  return hint;
}

/**
 * Frame 20's key row at the bottom right (N5, as amended): [Enter] Create, and [Enter] Start while a
 * card has focus. It never holds Esc: Esc is drawn once, as the quiet command.
 */
export function createKeyRow(row: HTMLElement, keys: CreateKeys): void {
  const hints: HTMLElement[] = [];
  if (keys.create) hints.push(lightHint('Enter', CREATE_WORDS.create, 'Enter'));
  if (keys.start) hints.push(lightHint('Enter', CREATE_WORDS.start, 'Enter'));
  row.replaceChildren(...hints);
}

export interface LightSteps {
  readonly root: HTMLElement;
  /** Redraws the steps; the live line says the running step's words once, as it changes. */
  set(steps: readonly Step[]): void;
}

/**
 * The steps on the light plane (5.17's step part in light colours, N17): the running step has
 * aria-current="step" and its dot pulses; a polite live line says each new running step (N20).
 */
export function lightSteps(steps: readonly Step[] = []): LightSteps {
  const root = element('div', 'wu-light-steps');
  const spoken = element('div', 'wu-hidden-words');
  spoken.setAttribute('aria-live', 'polite');
  let list = stepList([]);
  root.append(spoken, list);
  const shown: LightSteps = {
    root,
    set(next) {
      const fresh = stepList(next);
      list.replaceWith(fresh);
      list = fresh;
      const running = next.find((step) => step.state === 'now')?.words ?? '';
      if (spoken.textContent !== running) spoken.textContent = running;
    },
  };
  shown.set(steps);
  return shown;
}

export interface MadeNoteColumn { readonly label: string; readonly value: string }

export interface MadeNote {
  readonly root: HTMLElement;
  /** Fades it out over 300 ms and removes it (the first key or click, N14). */
  dismiss(): void;
}

/**
 * The made note (frame 22, N13): glass, centred at bottom 96, its columns in order, each a label
 * over a value that wraps within its column; an empty one is left out. Announced once (N20).
 */
export function madeNote(columns: readonly MadeNoteColumn[]): MadeNote {
  const root = element('div', 'wu-made-note wu-glass');
  root.setAttribute('role', 'status');
  // The status region goes on the page empty and is filled after (N24), so it is announced once.
  const fill = (): void => {
    for (const column of columns) {
      if (!column.value.trim()) continue;
      const part = element('div', 'wu-made-column');
      part.append(element('p', 'wu-made-label', column.label), element('p', 'wu-made-value', column.value));
      root.append(part);
    }
  };
  window.setTimeout(fill, 0);
  let leaving = 0;
  return {
    root,
    dismiss() {
      if (leaving || !root.isConnected) return;
      root.dataset.leaving = 'true';
      const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
      leaving = window.setTimeout(() => root.remove(), reduced ? 120 : 300);
    },
  };
}
