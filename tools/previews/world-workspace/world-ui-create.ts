// Making a world's own parts (ROOT's composer mock of 27 October, create-linear.html and making-linear.html, on
// Linear's "Conversations on Quality" pattern): the page over the front door with the current ready world's picture
// blurred behind it, the composer with its web search toggle, its price and the Create pill, the strip of ready
// worlds along the foot, and the making view's steps and web notes. They only draw; what a press does is the
// caller's (create-world.ts), and which key does what is create-steps.mjs's createKey. Their look lives in
// create-world.css. The light plane's parts (lightPage, lightLabel, lightLine, quietCommand, lightHint) are the
// Integrations page's, and madeNote the in-world made note's; their look lives in world-ui-create.css.
import type { Step } from './world-ui.ts';
import { CREATE_WORDS, NOTES_WORDS, aspectLabel } from './create-words.mjs';
import { scrollingColumn } from './world-page-frame.ts';
import './front-door.css';
import './world-ui-create.css';
import './create-world.css';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

let serial = 0;
const nextId = (stem: string): string => `${stem}-${++serial}`;

const SVG = 'http://www.w3.org/2000/svg';

/** A stroked line icon at the mock's 24 by 24, its paths' `d` as given; read by no one. */
function lineIcon(paths: readonly string[], circle = false): SVGSVGElement {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  if (circle) {
    const ring = document.createElementNS(SVG, 'circle');
    ring.setAttribute('cx', '12'); ring.setAttribute('cy', '12'); ring.setAttribute('r', '8.5');
    svg.append(ring);
  }
  for (const d of paths) {
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

/* ---------- Create a world: the page, the composer, the strip and the making view ---------- */

/** The page before Create, and while a world is made. */
export type CreateForm = 'create' | 'creating';

export interface CreatePage {
  readonly root: HTMLElement;
  /** The one column at the page's left edge: the title and what follows it. */
  readonly column: HTMLElement;
  /** Along the foot from the column's edge: the strip of ready worlds, on the page before Create. */
  readonly foot: HTMLElement;
  /** At the top right: Esc's command. */
  readonly corner: HTMLElement;
  /** Swaps the page before Create for the making view in place, the picture kept. */
  form(next: CreateForm): void;
  /** The current ready world's picture behind the page, crossfaded; null leaves the dark ground. */
  picture(address: string | null): void;
}

/**
 * The page (the mock's frame): the current ready world's picture filling the window, blurred and darkened, the shade
 * dark at the sides and the foot; the wordmark at the top left over the column's edge; the column; the strip along
 * the foot; Esc's command at the top right, last in the Tab order. A modal dialog named by `labelledBy` (the caller's
 * title).
 */
export function createPage({ labelledBy }: { readonly labelledBy: string }): CreatePage {
  const root = element('section', 'wu-create');
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-labelledby', labelledBy);
  root.dataset.form = 'create';
  // Two layers, so one picture crossfades into the next as the current card moves.
  const media = [element('div', 'wu-create-media'), element('div', 'wu-create-media')] as const;
  const shade = element('div', 'wu-create-shade');
  for (const quiet of [...media, shade]) quiet.setAttribute('aria-hidden', 'true');
  const mark = element('p', 'wu-create-mark', CREATE_WORDS.wordmark);
  const body = element('div', 'wu-create-body');
  const column = element('div', 'wu-create-column');
  const foot = element('div', 'wu-create-foot');
  body.append(column, foot);
  const corner = element('div', 'wu-create-corner');
  root.append(...media, shade, mark, body, corner);
  let shown = 0;
  let address: string | null = null;
  return {
    root, column, foot, corner,
    form(next) { root.dataset.form = next; },
    picture(next) {
      if (next === address) return;
      address = next;
      const hidden = media[1 - shown]!;
      hidden.style.backgroundImage = next ? `url(${JSON.stringify(next)})` : '';
      if (next) hidden.dataset.shown = 'true'; else delete hidden.dataset.shown;
      delete media[shown]!.dataset.shown;
      shown = 1 - shown;
    },
  };
}

/** The title at the column's top: "Create a world", or "Creating your world" while one is made. */
export function createTitle(words: string, id: string): HTMLHeadingElement {
  const title = element('h1', 'wu-create-title', words);
  title.id = id;
  title.tabIndex = -1;
  return title;
}

/** The web search toggle's state and details, where web notes are offered here. */
export interface ComposerWeb {
  readonly on: boolean;
  /** Its details, said on hover and keyboard focus. */
  readonly tip: string;
  readonly onChange: (on: boolean) => void;
}

export interface Composer {
  readonly root: HTMLElement;
  readonly field: HTMLTextAreaElement;
  readonly pill: HTMLButtonElement;
  /** The web search toggle while one is drawn. */
  readonly web: HTMLButtonElement | null;
  /** Puts words in the field (kept from last time, N6) and fits its height to them. */
  set(words: string): void;
  /** In the price's place: why Create cannot start, if it cannot, and the price, where there is one. */
  say(why: string | null, price: string | null): void;
  /** Says the reason again, for a press that meets the same one: emptied for a moment, then said, so it is heard. */
  again(): void;
  /** Dims the pill while Create cannot start; it stays a button that can be pressed, and says why. */
  ready(on: boolean): void;
  /** Draws the web search toggle with its details, or leaves it out where web notes are not offered (null). */
  offerWeb(web: ComposerWeb | null): void;
}

/** What a composer says of itself: the field's placeholder and name, and the pill's word. Create's by default. */
export interface ComposerWords {
  readonly placeholder: string;
  readonly label: string;
  readonly pill: string;
}

/**
 * The composer (the mock's one box): the words above, in the field's own type, with the placeholder in the muted
 * ink; in its foot the web search toggle, then why Create cannot start where it cannot, the price, and the white
 * Create pill with its key. Enter in the field and a press of the pill are the caller's. Making a creature in the
 * world is the same box with its own words (world-ui-creature.ts).
 */
export function composer({ value = '', onInput, onCreate, wording = { placeholder: CREATE_WORDS.placeholder, label: CREATE_WORDS.describeIt, pill: CREATE_WORDS.create } }: {
  readonly value?: string; readonly onInput?: (words: string) => void; readonly onCreate: () => void; readonly wording?: ComposerWords;
}): Composer {
  const root = element('div', 'wu-composer');
  const field = element('textarea', 'wu-composer-words');
  field.rows = 2;
  field.placeholder = wording.placeholder;
  field.spellcheck = true;
  field.setAttribute('aria-label', wording.label);
  const foot = element('div', 'wu-composer-foot');
  const web = element('span', 'wu-composer-web');
  // What the foot says changes while the page is open: the reason and the price, each a polite status.
  const said = element('span', 'wu-composer-why');
  const price = element('span', 'wu-composer-price');
  for (const status of [said, price]) status.setAttribute('role', 'status');
  const pill = element('button', 'wu-composer-pill', wording.pill);
  pill.type = 'button';
  pill.setAttribute('aria-keyshortcuts', 'Enter');
  const key = element('span', 'wu-composer-key', '↵');
  key.setAttribute('aria-hidden', 'true');
  pill.append(key);
  pill.addEventListener('click', () => onCreate());
  foot.append(web, said, price, pill);
  root.append(field, foot);
  // A reason too long for one line in the price's place takes a row of its own in the foot, over the toggle and Create.
  const measure = (): void => {
    delete foot.dataset['long'];
    if (said.hidden || !said.textContent) return;
    const line = Number.parseFloat(getComputedStyle(said).lineHeight) || 0;
    if (line > 0 && said.offsetHeight > line * 1.5) foot.dataset['long'] = 'true';
  };
  if (typeof ResizeObserver === 'function') new ResizeObserver(measure).observe(foot);
  // The field grows with its words, up to the composer's most (create-world.css), and scrolls past it.
  const fit = (): void => { field.style.height = 'auto'; if (field.scrollHeight > 0) field.style.height = `${field.scrollHeight}px`; };
  field.addEventListener('input', () => { fit(); onInput?.(field.value); });
  let chip: HTMLButtonElement | null = null;
  const shown: Composer = {
    root, field, pill,
    get web() { return chip; },
    set(words) { field.value = field.maxLength > 0 ? words.slice(0, field.maxLength) : words; fit(); },
    say(why, figure) {
      if (said.textContent !== (why ?? '')) said.textContent = why ?? '';
      said.hidden = why === null;
      if (price.textContent !== (figure ?? '')) price.textContent = figure ?? '';
      price.hidden = figure === null;
      measure();
    },
    again() {
      const why = said.textContent ?? '';
      if (!why) return;
      said.textContent = '';
      window.setTimeout(() => { if (said.textContent === '') said.textContent = why; }, 0);
    },
    ready(on) { if (on) pill.removeAttribute('aria-disabled'); else pill.setAttribute('aria-disabled', 'true'); },
    offerWeb(offered) {
      if (offered === null) { chip = null; web.replaceChildren(); return; }
      if (chip === null) {
        chip = element('button', 'wu-composer-chip');
        chip.type = 'button';
        chip.append(lineIcon(['M3.5 12h17M12 3.5c2.6 2.4 3.9 5.2 3.9 8.5s-1.3 6.1-3.9 8.5c-2.6-2.4-3.9-5.2-3.9-8.5s1.3-6.1 3.9-8.5z'], true), NOTES_WORDS.toggle);
        const tip = element('span', 'wu-composer-tip');
        tip.id = nextId('wu-composer-tip');
        tip.setAttribute('role', 'tooltip');
        chip.setAttribute('aria-describedby', tip.id);
        const own = chip;
        own.addEventListener('click', () => {
          const on = own.getAttribute('aria-pressed') !== 'true';
          own.setAttribute('aria-pressed', String(on));
          current?.onChange(on);
        });
        web.replaceChildren(chip, tip);
      }
      current = offered;
      chip.setAttribute('aria-pressed', String(offered.on));
      const tip = web.querySelector('.wu-composer-tip');
      if (tip && tip.textContent !== offered.tip) tip.textContent = offered.tip;
    },
  };
  let current: ComposerWeb | null = null;
  shown.say(null, null);
  shown.ready(false);
  shown.set(value);
  return shown;
}

/** A card in the strip: a ready world by its served name and picture, or Blank. */
export interface StripCard {
  readonly key: string;
  readonly name: string;
  /** A served picture's address; null draws the empty tile. */
  readonly picture: string | null;
  readonly blank?: boolean;
}

export interface WorldStrip {
  readonly root: HTMLElement;
  readonly cards: readonly HTMLButtonElement[];
  /** The current card's index. */
  readonly chosen: number;
  /** Makes card `index` current (aria-current, 200 wide, the one Tab stop of the row); `focus` moves the focus to it. */
  choose(index: number, focus?: boolean): void;
}

/**
 * The strip along the foot (Linear's episode row): the previous and next arrows above it, then the ready worlds, each
 * its 16:9 picture over "READY WORLD" and its name, and Blank last, "EMPTY" over "Blank". The current card is wider
 * and is the one Tab stop; arrows move it (the caller's, by createKey, and the arrow buttons). `onChoose` hears each
 * new current card (the page's picture follows it); `onStart` a press of a card.
 */
export function worldStrip(cards: readonly StripCard[], { onStart, onChoose, labelledBy }: {
  readonly onStart: (key: string) => void;
  readonly onChoose?: (card: StripCard) => void;
  readonly labelledBy?: string;
}): WorldStrip {
  const root = element('div', 'wu-strip');
  root.setAttribute('role', 'group');
  if (labelledBy) root.setAttribute('aria-labelledby', labelledBy); else root.setAttribute('aria-label', CREATE_WORDS.orStartFrom);
  const arrows = element('div', 'wu-strip-arrows');
  const arrow = (label: string, d: string, by: number): HTMLButtonElement => {
    const button = element('button', 'wu-strip-arrow');
    button.type = 'button';
    button.setAttribute('aria-label', label);
    button.append(lineIcon([d]));
    button.addEventListener('click', () => { if (button.getAttribute('aria-disabled') !== 'true') strip.choose(chosen + by); });
    return button;
  };
  const previous = arrow(CREATE_WORDS.previous, 'M15 6l-6 6 6 6', -1), next = arrow(CREATE_WORDS.next, 'M9 6l6 6-6 6', 1);
  arrows.append(previous, next);
  const row = element('div', 'wu-strip-cards');
  const buttons = cards.map((card) => {
    const button = element('button', 'wu-strip-card');
    button.type = 'button';
    button.dataset.key = card.key;
    button.dataset.picture = card.blank ? 'blank' : card.picture ? 'served' : 'none';
    const shot = element('span', 'wu-strip-shot');
    if (!card.blank && card.picture) {
      const picture = element('img');
      picture.alt = ''; picture.decoding = 'async'; picture.src = card.picture;
      shot.append(picture);
    }
    const kind = element('span', 'wu-strip-kind', card.blank ? CREATE_WORDS.empty : CREATE_WORDS.readyWorld);
    const name = element('span', 'wu-strip-name', card.name);
    name.id = nextId('wu-strip-name');
    kind.id = nextId('wu-strip-kind');
    button.setAttribute('aria-labelledby', name.id);
    button.setAttribute('aria-describedby', kind.id);
    button.setAttribute('aria-keyshortcuts', 'Enter');
    button.append(shot, kind, name);
    button.addEventListener('click', () => onStart(card.key));
    return button;
  });
  row.append(...buttons);
  root.append(arrows, row);
  let chosen = 0;
  const strip: WorldStrip = {
    root,
    cards: buttons,
    get chosen() { return chosen; },
    choose(index, focus = false) {
      const was = chosen;
      chosen = Math.max(0, Math.min(buttons.length - 1, index));
      buttons.forEach((button, at) => {
        button.tabIndex = at === chosen ? 0 : -1;
        if (at === chosen) button.setAttribute('aria-current', 'true'); else button.removeAttribute('aria-current');
      });
      // At an end its arrow says so and stays where it is, so the focus never falls off it.
      for (const [button, end] of [[previous, chosen === 0], [next, chosen >= buttons.length - 1]] as const) {
        if (end) button.setAttribute('aria-disabled', 'true'); else button.removeAttribute('aria-disabled');
      }
      const card = buttons[chosen];
      if (focus && card) card.focus({ preventScroll: true });
      card?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
      if (cards[chosen] && (chosen !== was || !told)) { told = true; onChoose?.(cards[chosen]!); }
    },
  };
  let told = false;
  strip.choose(0);
  return strip;
}

/** One step's row, kept across redraws, and what it shows now. */
interface StepRow { readonly item: HTMLLIElement; readonly words: HTMLElement; readonly time: HTMLTimeElement; drawn: Step | null }

export interface MakingSteps {
  readonly root: HTMLElement;
  /** Redraws the steps; the live line says the running step's words once, as it changes. */
  set(steps: readonly Step[]): void;
}

/**
 * The making view's steps (the mock's hairline rows): each step's words and its time in the mono type, the running
 * one in the full ink with a dot before it and aria-current="step"; a polite live line says each new running step.
 * Each step keeps its row across redraws (by its key, else its words), so a time's digits change in place.
 */
export function makingSteps(): MakingSteps {
  const root = element('div', 'wu-making-steps');
  const spoken = element('div', 'wu-hidden-words');
  spoken.setAttribute('aria-live', 'polite');
  const list = element('ol', 'wu-making-list');
  root.append(spoken, list);
  const rows = new Map<string, StepRow>();
  return {
    root,
    set(next) {
      const ids = next.map((step) => step.key ?? step.words);
      for (const [id, row] of rows) if (!ids.includes(id)) { row.item.remove(); rows.delete(id); }
      next.forEach((step, place) => {
        const id = ids[place]!;
        let row = rows.get(id);
        if (row === undefined) {
          const item = element('li', 'wu-making-step');
          const words = element('span', 'wu-making-words');
          const time = element('time', 'wu-making-time');
          item.append(words, time);
          row = { item, words, time, drawn: null };
          rows.set(id, row);
        }
        const was = row.drawn;
        row.drawn = step;
        if (was?.state !== step.state || was.words !== step.words) {
          row.item.dataset.state = step.state;
          if (step.state === 'now') {
            row.item.setAttribute('aria-current', 'step');
            const dot = element('i', 'wu-making-now');
            dot.setAttribute('aria-hidden', 'true');
            row.words.replaceChildren(dot, step.words);
          } else {
            row.item.removeAttribute('aria-current');
            row.words.textContent = step.words;
          }
        }
        if (was?.time !== step.time) row.time.textContent = step.time ?? '';
        if (list.children[place] !== row.item) list.insertBefore(row.item, list.children[place] ?? null);
      });
      const running = next.find((step) => step.state === 'now')?.words ?? '';
      if (spoken.textContent !== running) spoken.textContent = running;
    },
  };
}

export interface WebNotes {
  readonly root: HTMLElement;
  /** The notes the request kept, each under its aspect's label, under `label` ("FROM THE WEB, 3 SEARCHES"). */
  notes(label: string, notes: readonly { readonly aspect: string; readonly text: string }[]): void;
  /** Where no notes come, the line that says why in their place, under `label`. */
  instead(label: string, line: string): void;
}

/** The making view's second column (the mock's): the web notes, hidden until they or the line in their place come. */
export function webNotes(): WebNotes {
  const root = element('section', 'wu-making-web');
  const label = element('p', 'wu-making-kind');
  label.id = nextId('wu-making-kind');
  root.setAttribute('aria-labelledby', label.id);
  root.hidden = true;
  return {
    root,
    notes(words, notes) {
      label.textContent = words;
      root.replaceChildren(label, ...notes.map((note) => {
        const line = element('p', 'wu-making-note');
        line.append(element('b', '', aspectLabel(note.aspect)), note.text);
        return line;
      }));
      root.hidden = false;
    },
    instead(words, line) {
      label.textContent = words;
      root.replaceChildren(label, element('p', 'wu-making-note', line));
      root.hidden = false;
    },
  };
}

/* ---------- The light plane: the Integrations page's parts, and the in-world made note ---------- */

/** The light page's one form: the Integrations page over the front door (integrations.ts). */
export type LightForm = 'integrations';

export interface LightPage {
  readonly root: HTMLElement;
  /** The title and what follows it. */
  readonly head: HTMLElement;
  /** What stands under the head in the page's column. */
  readonly lower: HTMLElement;
  /** The quiet command's place. */
  readonly quiet: HTMLElement;
  /** The key row at the bottom right (N5). */
  readonly keys: HTMLElement;
  /** The stepped surface behind the head. */
  readonly surface: HTMLElement;
  /** Swaps the page's form in place, the picture kept. */
  form(next: LightForm): void;
  /** The chosen world's still picture; null leaves the plane. */
  picture(address: string | null): void;
}

/**
 * The light page: the chosen world's still picture under its veils, the wordmark and the stepped surface, on the
 * light pages' frame. A modal dialog named by `labelledBy` (the caller's title).
 */
export function lightPage({ form = 'integrations', picture = null, labelledBy }: { readonly form?: LightForm; readonly picture?: string | null; readonly labelledBy?: string } = {}): LightPage {
  const root = element('section', 'wu-light wu-frame ux-noveuis');
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  if (labelledBy) root.setAttribute('aria-labelledby', labelledBy);
  root.dataset.form = form;
  const world = element('div', 'wu-light-world'), veil = element('div', 'wu-light-veil'), surface = element('div', 'wu-light-surface');
  for (const quietPart of [world, veil, surface]) quietPart.setAttribute('aria-hidden', 'true');
  const wordmark = element('p', 'wu-light-wordmark', CREATE_WORDS.wordmark);
  const head = element('div', 'wu-light-head'), lower = element('div', 'wu-light-lower');
  const quiet = element('div', 'wu-light-quiet'), keys = element('div', 'wu-light-keys wu-frame-keys');
  // The light pages' frame (world-page-frame.css): the parts flow in one column, the stepped surface behind the head
  // with them, which fills the window down to the key row and scrolls with its fades and track where it is longer.
  const body = element('div', 'wu-light-body');
  body.append(surface, head, lower);
  const column = scrollingColumn(body);
  column.column.classList.add('wu-light-column');
  const measure = new ResizeObserver(() => column.update());
  for (const part of [body, head, lower]) measure.observe(part);
  root.append(world, veil, wordmark, column.column, keys, quiet);
  const page: LightPage = {
    root, head, lower, quiet, keys, surface,
    form(next) { root.dataset.form = next; },
    picture(address) { world.style.backgroundImage = address ? `url(${JSON.stringify(address)})` : ''; },
  };
  page.picture(picture);
  return page;
}

/** A section label on the light plane. */
export function lightLabel(words: string, forId?: string): HTMLElement {
  const made = forId ? element('label', 'wu-light-label', words) : element('p', 'wu-light-label', words);
  if (forId && made instanceof HTMLLabelElement) made.htmlFor = forId;
  return made;
}

/**
 * A line on the light plane; `refused` in the light refusal ink (N9). A polite status where it changes while the page
 * is open.
 */
export function lightLine(words: string, { tone = 'plain', live = false }: { readonly tone?: 'plain' | 'refused'; readonly live?: boolean } = {}): HTMLParagraphElement {
  const line = element('p', 'wu-light-line', words);
  if (tone === 'refused') line.dataset.tone = 'refused';
  if (live) line.setAttribute('role', 'status');
  return line;
}

/** Where Esc's command is drawn: the light plane's quiet place, inside a row, or Create's top right corner. */
export type QuietPlace = 'quiet' | 'row' | 'corner';

/**
 * The quiet command (5.11): one button named by its word ("Your worlds"), its key as aria-keyshortcuts and its cap
 * hidden. `place` says where it is drawn.
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

/** A key the row says: a cap and a word, not a button. */
export function lightHint(key: string, word: string, shortcut: string): HTMLSpanElement {
  const hint = element('span', 'wu-qcmd wu-light-hint');
  const cap = element('span', 'wu-qcmd-key', key);
  cap.setAttribute('aria-hidden', 'true');
  hint.append(cap, element('span', 'wu-qcmd-word', word));
  hint.setAttribute('aria-keyshortcuts', shortcut);
  return hint;
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
