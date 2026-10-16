// The in-world design's shared parts (DESIGN's specification of 14 October 2026, section 5): small
// DOM builders over world-ui.css. They only draw; what a part does when pressed is the caller's.
// Every in-world screen builds from these; a part's look lives in world-ui.css alone.
import { ANCHOR_INSET, BESIDE, clampToView, noteDuration, placeBeside, uiScale } from './world-ui-layout.mjs';
import './world-ui.css';

type Keys = readonly string[] | 'mouse' | 'mouse-click';

export interface KeyWordOptions {
  /** The caps drawn: key names, or a mouse ('mouse-click' fills its left half). */
  readonly keys: Keys;
  /** One or two words from WORDS.md. */
  readonly word: string;
  /** The aria-keyshortcuts value; the key works whether or not the prompt shows. */
  readonly shortcut?: string;
  /** Present: the whole prompt is a button that runs it. Absent: a hint that only says the key. */
  readonly onPress?: () => void;
  readonly small?: boolean;
  readonly disabled?: boolean;
}

/** Symbols IBM Plex does not carry, drawn in the system's symbol face. */
const SYMBOLS = /[⌘⇧⌥←→↑↓]/u;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

/** One key cap; only the symbol characters of its name are set in the symbol face ("⌘Z" is one cap). */
function cap(name: string, small: boolean): HTMLElement {
  const key = element('span', small ? 'wu-key wu-small' : 'wu-key');
  for (const piece of name.split(/([⌘⇧⌥←→↑↓])/u).filter(Boolean)) key.append(SYMBOLS.test(piece) ? element('span', 'wu-sym', piece) : piece);
  return key;
}

/** Sets --ui-scale on `root` now and whenever the window changes size, until `signal` aborts. */
export function mountUiScale(root: HTMLElement, signal?: AbortSignal): void {
  const set = (): void => root.style.setProperty('--ui-scale', uiScale(innerWidth, innerHeight).toFixed(4));
  set();
  addEventListener('resize', set, signal ? { signal } : {});
}

/** The current --ui-scale of `root`, for placing parts in reference pixels. */
export function scaleOf(root: HTMLElement): number {
  const value = Number.parseFloat(root.style.getPropertyValue('--ui-scale'));
  return Number.isFinite(value) && value > 0 ? value : 1;
}

/** An outlined key and its word (5.1). */
export function keyWord(options: KeyWordOptions): HTMLButtonElement | HTMLSpanElement {
  const { keys, word, shortcut, onPress, small = false, disabled = false } = options;
  const prompt = onPress ? element('button', 'wu-prompt') : element('span', 'wu-prompt');
  const caps = keys === 'mouse' || keys === 'mouse-click'
    ? element('span', keys === 'mouse' ? 'wu-key wu-mouse' : 'wu-key wu-mouse wu-click')
    : keys.length === 1 ? cap(keys[0]!, small) : element('span', 'wu-keys');
  if (Array.isArray(keys) && keys.length > 1) for (const name of keys) caps.append(cap(name, small));
  caps.setAttribute('aria-hidden', 'true');
  prompt.append(caps, element('span', 'wu-word', word));
  if (shortcut) prompt.setAttribute('aria-keyshortcuts', shortcut);
  if (prompt instanceof HTMLButtonElement) {
    prompt.type = 'button';
    prompt.disabled = disabled;
    prompt.addEventListener('click', () => onPress?.());
  } else if (disabled) prompt.setAttribute('aria-disabled', 'true');
  return prompt;
}

/** Changes a prompt's word in place (Play to Pause, Your worlds to Back). */
export function setWord(prompt: HTMLElement, word: string): void {
  const words = prompt.querySelector('.wu-word');
  if (words && words.textContent !== word) words.textContent = word;
}

/** A row of prompts 30 px apart; `gapAfter` indexes get the 14 px gap between moving and doing keys. */
export function promptRow(prompts: readonly HTMLElement[], gapAfter: readonly number[] = []): HTMLDivElement {
  const row = element('div', 'wu-row');
  prompts.forEach((prompt, index) => {
    row.append(prompt);
    if (gapAfter.includes(index) && index < prompts.length - 1) row.append(element('span', 'wu-gap'));
  });
  return row;
}

/** A column of prompts 15 px apart. */
export function promptColumn(prompts: readonly HTMLElement[]): HTMLDivElement {
  const column = element('div', 'wu-col');
  column.append(...prompts);
  return column;
}

/** A page's keys at the bottom right (5.11), in the order given (Esc last). */
export function keyRow(prompts: readonly HTMLElement[]): HTMLDivElement {
  const row = promptRow(prompts);
  row.classList.add('wu-key-row');
  return row;
}

export interface ChipOptions { readonly quiet?: boolean; readonly live?: boolean; readonly page?: boolean }

/** A model's name or a state (5.5); never a button. */
export function chip(text: string, options: ChipOptions = {}): HTMLSpanElement {
  const made = element('span', 'wu-chip');
  made.classList.toggle('wu-quiet', options.quiet === true);
  made.classList.toggle('wu-page-chip', options.page === true);
  made.append(element('span', 'wu-chip-words', text));
  setChipLive(made, options.live === true);
  return made;
}

/** Leads a chip with the live dot while its model is deciding. */
export function setChipLive(made: HTMLElement, on: boolean): void {
  const dot = made.querySelector(':scope > .wu-live-dot');
  if (on && !dot) { const live = element('span', 'wu-live-dot'); live.setAttribute('aria-hidden', 'true'); made.prepend(live); }
  if (!on && dot) dot.remove();
}

const FORWARD = '<svg viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M4.5 2.5 8 6l-3.5 3.5" stroke="#fff" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/** The one decisive action on a screen (5.8): Open, Run, Create, Search or Make. */
export function orb({ word, onPress, disabled = false }: { readonly word: string; readonly onPress: () => void; readonly disabled?: boolean }): HTMLButtonElement {
  const button = element('button', 'wu-orb');
  button.type = 'button';
  button.disabled = disabled;
  const ring = element('span', 'wu-orb-ring');
  ring.innerHTML = FORWARD;
  button.append(element('span', 'wu-orb-word', word), ring);
  button.addEventListener('click', () => onPress());
  return button;
}

/** The 46 by 1 rule between a card's words and its prompts. */
export const rule = (): HTMLDivElement => element('div', 'wu-rule');

/** A section label on a page or card ("Personality", "Model"). */
export const label = (text: string): HTMLParagraphElement => element('p', 'wu-label', text);

/** A pill of thin glass (the redraws' craft): a line of parts, such as a title, a divider and a count. */
export function pill(...parts: readonly (Node | string)[]): HTMLDivElement {
  const made = element('div', 'wu-glass-thin wu-pill');
  made.append(...parts);
  return made;
}

/** A rail button's tip: its word and its key as a small cap ("History [H]"). */
export function tip(word: string, key: string): HTMLDivElement {
  const made = element('div', 'wu-glass-thin wu-tip');
  const cap = element('span', 'wu-key wu-small', key);
  cap.setAttribute('aria-hidden', 'true');
  made.append(element('span', '', word), cap);
  return made;
}

/** Floating words over the world on one soft shade with no edge; `small` for a name over someone. The caller fills and places it. */
export function shade({ small = false }: { readonly small?: boolean } = {}): HTMLDivElement {
  return element('div', small ? 'wu-shade wu-small' : 'wu-shade');
}

/** One row of key and word: the key's name (Enter is drawn as a return arrow, 'mouse' as a mouse, 'mouse-click' as one with its left button lit), its word, and what it does. */
export interface GlyphRow {
  readonly key: string;
  readonly word: string;
  /** The aria-keyshortcuts value; the key works whether or not the row shows. */
  readonly shortcut?: string;
  /** Present: the row is a button that runs it. Absent: the row only says the key. */
  readonly onPress?: () => void;
  readonly disabled?: boolean;
}

/**
 * A group's figures: a number is reference pixels (scaled by --ui-scale), a string any CSS length (a
 * sheet's own 1440 size as a max() floor). Each left out keeps world-ui.css's (32, 16, 16, 19, 0).
 */
export interface GlyphRowSizes {
  readonly glyph?: number | string;
  readonly rowGap?: number | string;
  readonly colGap?: number | string;
  readonly word?: number | string;
  /** Plain pixels: the measured lift of a word's letters onto its key's middle. */
  readonly nudge?: number;
  /** Talking's choices: each row on its own feathered bar, no group shade. */
  readonly bars?: boolean;
}

const RETURN = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 5v7a3 3 0 0 1-3 3H6 M10 11l-4 4 4 4"/></svg>';

const MOUSE = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v4"/></svg>';

/** The mouse with its left button lit (frame r13's Place): a click or a drag. */
const MOUSE_CLICK = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.6" aria-hidden="true"><rect x="6" y="2.5" width="12" height="19" rx="6"/><path d="M12 2.5v7 M6 9.5h12"/><path d="M6.8 9 V8.5 a5.2 5.2 0 0 1 5.2 -5.2 V9 z" fill="#fff" stroke="none"/></svg>';

/** Rows of key and word (the redraws' craft): keys one size, in one column, each word centred on its key. */
export function glyphRows(rows: readonly GlyphRow[], sizes: GlyphRowSizes = {}): HTMLDivElement {
  const group = element('div', sizes.bars === true ? 'wu-rows wu-bars' : 'wu-rows');
  const length = (value: number | string): string => typeof value === 'number' ? `calc(${value} * var(--u))` : value;
  for (const [name, property] of [['glyph', '--glyph'], ['rowGap', '--row-gap'], ['colGap', '--col-gap'], ['word', '--word']] as const) {
    const value = sizes[name];
    if (value !== undefined) group.style.setProperty(property, length(value));
  }
  if (sizes.nudge !== undefined && Number.isFinite(sizes.nudge)) group.style.setProperty('--nudge', `${sizes.nudge}px`);
  for (const { key, word, shortcut, onPress, disabled = false } of rows) {
    const row = onPress ? element('button', 'wu-row') : element('div', 'wu-row');
    const glyph = element('span', 'wu-glyph');
    if (key === 'Enter') glyph.innerHTML = RETURN;
    else if (key === 'mouse') glyph.innerHTML = MOUSE;
    else if (key === 'mouse-click') glyph.innerHTML = MOUSE_CLICK;
    else glyph.textContent = key;
    glyph.setAttribute('aria-hidden', 'true');
    row.append(glyph, element('span', 'wu-word', word));
    if (shortcut) row.setAttribute('aria-keyshortcuts', shortcut);
    if (row instanceof HTMLButtonElement) {
      row.type = 'button';
      row.disabled = disabled;
      row.addEventListener('click', () => onPress?.());
    } else if (disabled) row.setAttribute('aria-disabled', 'true');
    group.append(row);
  }
  return group;
}

/**
 * Moves an anchored part to `x`, `y` (its top left, CSS pixels) by transform alone, kept `inset`
 * reference pixels inside the viewport. Returns where it went.
 */
export function anchor(part: HTMLElement, x: number, y: number, { inset = ANCHOR_INSET, scale = 1 } = {}): { x: number; y: number } {
  const size = { width: part.offsetWidth, height: part.offsetHeight };
  const at = clampToView({ x, y }, size, { width: innerWidth, height: innerHeight }, inset * scale);
  const transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
  if (part.style.transform !== transform) part.style.transform = transform;
  return at;
}

/** Where the note sits: clear of the hints in the world, above the catalog in build mode, low on a page. */
export type NotePlace = 'world' | 'build' | 'page';

export interface Notes {
  /** Shows one line, replacing any note on screen; it leaves after its time unless `ms` is 0. */
  show(words: string, options?: { readonly prompt?: HTMLElement; readonly ms?: number }): void;
  clear(): void;
  place(where: NotePlace): void;
  readonly root: HTMLElement;
}

/** The one note at a time at the bottom centre (5.13). */
export function notes(host: HTMLElement, { place = 'world' }: { readonly place?: NotePlace } = {}): Notes {
  const root = element('div', 'wu-note wu-glass');
  root.setAttribute('role', 'status');
  root.dataset.place = place;
  root.hidden = true;
  host.append(root);
  let timer = 0, leaving = 0;
  const clear = (): void => {
    clearTimeout(timer); clearTimeout(leaving);
    root.hidden = true; root.replaceChildren(); delete root.dataset.leaving;
  };
  return {
    root,
    clear,
    place(where) { root.dataset.place = where; },
    show(words, { prompt, ms } = {}) {
      clear();
      root.append(element('span', 'wu-note-words', words));
      if (prompt) root.append(prompt);
      root.hidden = false;
      const stay = ms ?? noteDuration(Boolean(prompt));
      if (stay > 0) timer = window.setTimeout(() => {
        root.dataset.leaving = 'true';
        leaving = window.setTimeout(clear, 300);
      }, stay);
    },
  };
}

export interface Ring {
  readonly root: SVGSVGElement;
  /** Centres the ring on a ground point's screen position with these radii (CSS pixels). */
  place(x: number, y: number, rx: number, ry: number): void;
  hide(): void;
}

const SVG = 'http://www.w3.org/2000/svg';
let ringSerial = 0;

/** The ring at a chosen subject's feet (5.4). */
export function ring(): Ring {
  const id = `wu-ring-${++ringSerial}`;
  const root = document.createElementNS(SVG, 'svg');
  root.setAttribute('class', 'wu-ring wu-anchored');
  root.setAttribute('aria-hidden', 'true');
  root.innerHTML = `<defs><radialGradient id="${id}-fill"><stop offset="0" stop-color="#bfe9f0" stop-opacity=".24"/><stop offset="1" stop-color="#bfe9f0" stop-opacity="0"/></radialGradient>`
    + `<filter id="${id}-glow" x="-20%" y="-60%" width="140%" height="220%"><feGaussianBlur stdDeviation="3"/></filter></defs>`
    + `<ellipse class="wu-ring-fill" fill="url(#${id}-fill)"/><ellipse class="wu-ring-glow" fill="none" stroke="#bfe9f0" stroke-opacity=".5" stroke-width="6" filter="url(#${id}-glow)"/>`
    + '<ellipse class="wu-ring-line" fill="none" stroke="#fff" stroke-width="2.2"/>';
  root.style.display = 'none';
  const ellipses = [...root.querySelectorAll('ellipse')];
  return {
    root,
    place(x, y, rx, ry) {
      const pad = 12, width = 2 * (rx + pad), height = 2 * (ry + pad);
      root.setAttribute('width', width.toFixed(1)); root.setAttribute('height', height.toFixed(1));
      for (const one of ellipses) {
        one.setAttribute('cx', (rx + pad).toFixed(1)); one.setAttribute('cy', (ry + pad).toFixed(1));
        one.setAttribute('rx', rx.toFixed(1)); one.setAttribute('ry', ry.toFixed(1));
      }
      root.style.transform = `translate3d(${(x - width / 2).toFixed(1)}px,${(y - height / 2).toFixed(1)}px,0)`;
      root.style.display = '';
    },
    hide() { root.style.display = 'none'; },
  };
}

/** How a footprint's outline reads: the chosen thing, a copy where it would go, a refused copy, the spot it came from (dashed). */
export type OutlineForm = 'chosen' | 'copy' | 'refused' | 'origin';

export interface Outline {
  readonly root: SVGSVGElement;
  /** Draws a rounded outline through a footprint's corners as projected on screen (CSS pixels, in order). */
  place(corners: readonly { readonly x: number; readonly y: number }[]): void;
  /** Changes the form (a copy turns refused when the server refuses its spot). */
  form(form: OutlineForm): void;
  hide(): void;
}

/** A thing's footprint (5.4, 5.15): 2.2 px white with the ring's glow when chosen; 1.8 px for a copy, tinted when refused; dashed for the spot it came from. */
export function outline({ form = 'chosen' }: { readonly form?: OutlineForm } = {}): Outline {
  const id = `wu-outline-${++ringSerial}`;
  const root = document.createElementNS(SVG, 'svg');
  root.setAttribute('class', 'wu-outline');
  root.setAttribute('aria-hidden', 'true');
  root.dataset.form = form;
  root.innerHTML = `<defs><filter id="${id}-glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3"/></filter></defs>`
    + `<path class="wu-outline-glow" filter="url(#${id}-glow)"/><path class="wu-outline-line"/>`;
  root.style.display = 'none';
  const paths = [...root.querySelectorAll('path')];
  return {
    root,
    place(corners) {
      if (corners.length < 3) { root.style.display = 'none'; return; }
      const d = roundedPath(corners, 8);
      for (const path of paths) path.setAttribute('d', d);
      root.style.display = '';
    },
    form(next) { root.dataset.form = next; },
    hide() { root.style.display = 'none'; },
  };
}

export interface DottedPath {
  readonly root: SVGSVGElement;
  /** Draws a gentle dotted curve from `from` to `to` (CSS pixels). */
  place(from: { readonly x: number; readonly y: number }, to: { readonly x: number; readonly y: number }): void;
  hide(): void;
}

/** The dotted path from a thing's spot to its copy (5.15): 1.4 px, 75 % white, dashes 3 6, a gentle curve. */
export function path(): DottedPath {
  const root = document.createElementNS(SVG, 'svg');
  root.setAttribute('class', 'wu-path');
  root.setAttribute('aria-hidden', 'true');
  root.innerHTML = '<path class="wu-path-line"/>';
  root.style.display = 'none';
  const line = root.querySelector('path')!;
  return {
    root,
    place(from, to) {
      // The bend is a seventh of the length, to the left of the way from the spot to the copy.
      const dx = to.x - from.x, dy = to.y - from.y, bend = 1 / 7;
      const control = { x: (from.x + to.x) / 2 + dy * bend, y: (from.y + to.y) / 2 - dx * bend };
      line.setAttribute('d', `M${from.x.toFixed(1)} ${from.y.toFixed(1)}Q${control.x.toFixed(1)} ${control.y.toFixed(1)} ${to.x.toFixed(1)} ${to.y.toFixed(1)}`);
      root.style.display = '';
    },
    hide() { root.style.display = 'none'; },
  };
}

export interface NameTagWords {
  readonly name: string;
  /** What the character is doing; null or absent while a pop speaks for it, and for a thing. */
  readonly doing?: string | null;
  /** The served model name for the chip, or null with no model (and for a thing). */
  readonly model?: string | null;
  /** The chip's live dot while a run is on and this model is deciding. */
  readonly live?: boolean;
}

export interface NameTag {
  readonly root: HTMLElement;
  set(words: NameTagWords): void;
  /** Puts the caret 10 reference px above the head point (x, y), centred. */
  place(x: number, y: number): void;
  hide(): void;
}

const CARET = '<svg class="wu-tag-caret" viewBox="0 0 12 7" aria-hidden="true"><path d="M1 1l5 5 5-5" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/** The sentence a screen reader hears for a name tag: "Teo, waiting by the bench, Nemotron 3 Nano 30B". */
export function tagSentence({ name, doing, model }: NameTagWords): string {
  const said = doing ? doing.charAt(0).toLowerCase() + doing.slice(1) : null;
  return [name, said, model].filter(Boolean).join(', ');
}

/** The name over the character or thing at the reticle (5.3): name, doing line, model chip, caret. */
export function nameTag({ scale = () => 1, inset = ANCHOR_INSET }: { readonly scale?: () => number; readonly inset?: number } = {}): NameTag {
  const root = element('div', 'wu-anchored wu-tag');
  const name = element('div', 'wu-tag-name'), doing = element('div', 'wu-tag-doing');
  // What is drawn is hidden from readers; one live line says it all once, on each change.
  name.setAttribute('aria-hidden', 'true'); doing.setAttribute('aria-hidden', 'true');
  const spoken = element('div', 'wu-hidden-words');
  spoken.setAttribute('aria-live', 'polite');
  root.append(spoken, name, doing);
  root.insertAdjacentHTML('beforeend', CARET);
  let modelChip: HTMLSpanElement | null = null, size: { width: number; height: number } | null = null, sizedAt = 0;
  root.hidden = true;
  return {
    root,
    set(words) {
      if (name.textContent !== words.name) { name.textContent = words.name; size = null; }
      const line = words.doing || '';
      if (doing.textContent !== line) { doing.textContent = line; size = null; }
      doing.hidden = !line;
      if (!words.model) { if (modelChip) { modelChip.remove(); modelChip = null; size = null; } }
      else {
        if (!modelChip) { modelChip = chip(words.model); modelChip.setAttribute('aria-hidden', 'true'); root.insertBefore(modelChip, root.lastElementChild); size = null; }
        const held = modelChip.querySelector('.wu-chip-words');
        if (held && held.textContent !== words.model) { held.textContent = words.model; size = null; }
        setChipLive(modelChip, words.live === true);
      }
      const sentence = tagSentence(words);
      if (spoken.textContent !== sentence) spoken.textContent = sentence;
    },
    place(x, y) {
      root.hidden = false;
      const s = scale();
      // Measured once per change of words or scale, so a frame only writes a transform.
      if (size === null || sizedAt !== s) { size = { width: root.offsetWidth, height: root.offsetHeight }; sizedAt = s; }
      const at = clampToView({ x: x - size.width / 2, y: y - size.height - 10 * s }, size, { width: innerWidth, height: innerHeight }, inset * s);
      const transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
      if (root.style.transform !== transform) root.style.transform = transform;
    },
    hide() { root.hidden = true; },
  };
}

/** A closed path through `corners`, each corner cut by a quadratic curve of `radius` pixels at most. */
function roundedPath(corners: readonly { readonly x: number; readonly y: number }[], radius: number): string {
  const n = corners.length, toward = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const length = Math.hypot(to.x - from.x, to.y - from.y) || 1, cut = Math.min(radius, length / 2);
    return { x: from.x + (to.x - from.x) * cut / length, y: from.y + (to.y - from.y) * cut / length };
  };
  const at = (point: { x: number; y: number }) => `${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  let d = '';
  corners.forEach((corner, index) => {
    const before = toward(corner, corners[(index + n - 1) % n]!), after = toward(corner, corners[(index + 1) % n]!);
    d += `${index === 0 ? 'M' : 'L'}${at(before)}Q${at(corner)} ${at(after)}`;
  });
  return d + 'Z';
}

/** A subject's screen box, CSS pixels; head and waist heights centre the card. */
export interface SubjectBounds { readonly left: number; readonly top: number; readonly right: number; readonly bottom: number; readonly headY?: number; readonly waistY?: number }

export interface SideCard {
  readonly root: HTMLElement;
  /** Where the caller puts the card's words and prompts. */
  readonly body: HTMLElement;
  /**
   * Places the card and its connector beside the subject; returns the side it took. `connect`
   * (default `bounds`) is where the connector starts, when the card sits beside more than its subject.
   */
  place(bounds: SubjectBounds, options?: { readonly connect?: SubjectBounds }): 'right' | 'left';
  hide(): void;
}

/**
 * The glass card beside a subject (5.6): `question` makes it the 452 px card with an orb, `build`
 * the narrower build mode card (330 to 390 px, padding 24 26, 30 px title).
 */
export function sideCard({ question = false, build = false, scale = () => 1 }: { readonly question?: boolean; readonly build?: boolean; readonly scale?: () => number } = {}): SideCard {
  const root = element('div', 'wu-anchored wu-beside');
  const card = element('section', `wu-card wu-glass${question ? ' wu-question' : ''}${build ? ' wu-build' : ''}`);
  const connector = document.createElementNS(SVG, 'svg');
  connector.setAttribute('class', 'wu-connector');
  connector.setAttribute('aria-hidden', 'true');
  connector.innerHTML = '<path fill="none" stroke="rgba(255,255,255,.7)" stroke-width="1.2"/><circle r="2.5" fill="#fff"/>';
  const [line, dot] = [connector.querySelector('path')!, connector.querySelector('circle')!];
  root.append(connector, card);
  root.hidden = true;
  return {
    root,
    body: card,
    place(bounds, { connect = bounds } = {}) {
      root.hidden = false;
      const s = scale();
      const size = { width: card.offsetWidth, height: card.offsetHeight };
      const at = placeBeside(bounds, size, { width: innerWidth, height: innerHeight }, { gap: BESIDE.gap * s, inset: BESIDE.inset * s, meet: BESIDE.meet * s, connect, top: BESIDE.top * s, bottom: BESIDE.bottom * s });
      card.style.transform = `translate3d(${at.x.toFixed(1)}px,${at.y.toFixed(1)}px,0)`;
      const { from, elbow, to } = at.connector;
      line.setAttribute('d', `M${from.x.toFixed(1)} ${from.y.toFixed(1)}L${elbow.x.toFixed(1)} ${elbow.y.toFixed(1)}L${to.x.toFixed(1)} ${to.y.toFixed(1)}`);
      dot.setAttribute('cx', from.x.toFixed(1)); dot.setAttribute('cy', from.y.toFixed(1));
      return at.side;
    },
    hide() { root.hidden = true; },
  };
}

/** The words of a card, top to bottom (5.6): optional label, title, one or two lines. */
export function cardWords({ label: over, title, lines = [] }: { readonly label?: string; readonly title: string; readonly lines?: readonly string[] }): DocumentFragment {
  const words = document.createDocumentFragment();
  if (over) words.append(element('p', 'wu-card-label', over));
  words.append(element('h2', 'wu-card-title', title));
  for (const line of lines.slice(0, 2)) words.append(element('p', 'wu-card-line', line));
  return words;
}

export type PageForm = 'character' | 'creature' | 'full';

export interface Page {
  readonly root: HTMLElement;
  readonly content: HTMLElement;
  /** The page's key row; the caller fills it, Esc last. */
  readonly keys: HTMLElement;
  open(host: HTMLElement): void;
  close(): void;
}

/** A page over the dimmed world (5.7). */
export function page({ form }: { readonly form: PageForm }): Page {
  const root = element('section', `wu-page wu-${form}`);
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  const content = element('div', 'wu-page-content');
  const keys = element('div', 'wu-row wu-key-row');
  content.append(keys);
  root.append(element('div', 'wu-page-blur'), element('div', 'wu-page-shade'), content);
  return {
    root, content, keys,
    open(host) { host.append(root); },
    close() { root.remove(); },
  };
}

export type StepState = 'done' | 'now' | 'next';
export interface Step { readonly words: string; readonly state: StepState; readonly sub?: string; readonly time?: string }

/** Steps with their state, words and time (5.17); the caller redraws it as steps change. */
export function stepList(steps: readonly Step[]): HTMLOListElement {
  const list = element('ol', 'wu-steps');
  for (const step of steps) {
    const item = element('li', 'wu-step');
    item.dataset.state = step.state;
    if (step.state === 'now') item.setAttribute('aria-current', 'step');
    const dot = element('span', 'wu-step-dot'); dot.setAttribute('aria-hidden', 'true');
    const words = element('div');
    words.append(element('div', 'wu-step-words', step.words));
    if (step.sub) words.append(element('div', 'wu-step-sub', step.sub));
    item.append(dot, words, element('span', 'wu-step-time', step.time ?? ''));
    list.append(item);
  }
  return list;
}

export interface AreaBanner { readonly root: HTMLElement; play(): Promise<void>; remove(): void }

/** The world's name on arrival (5.18): in 600 ms, holds 2.4 s, out 800 ms; once. */
export function areaBanner({ name, over, sub }: { readonly name: string; readonly over?: string; readonly sub?: string }): AreaBanner {
  const root = element('div', over ? 'wu-banner wu-made' : 'wu-banner');
  root.setAttribute('role', 'status');
  if (over) root.append(element('p', 'wu-banner-over', over));
  root.append(element('h1', 'wu-banner-name', name), element('div', 'wu-banner-line'));
  if (sub) root.append(element('p', 'wu-banner-sub', sub));
  let animation: Animation | null = null;
  return {
    root,
    async play() {
      const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
      const keyframes = reduced
        ? [{ opacity: 0 }, { opacity: 1, offset: 0.04 }, { opacity: 1, offset: 0.96 }, { opacity: 0 }]
        : [{ opacity: 0, translate: '0 6px' }, { opacity: 1, translate: '0 0', offset: 0.1875 }, { opacity: 1, translate: '0 0', offset: 0.75 }, { opacity: 0, translate: '0 0' }];
      animation = root.animate(keyframes, { duration: reduced ? 3000 : 3800, easing: 'ease-out', fill: 'forwards' });
      try { await animation.finished; } catch { /* Cancelled when the world closes. */ }
    },
    remove() { animation?.cancel(); root.remove(); },
  };
}
