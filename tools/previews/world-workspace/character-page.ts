// A character's own page, Teo's day (DESIGN's r06, approved 16 October, with r11's personality fields in place; the
// R-DAY-DECISION build sheet sections 1 and 3): History's light page, who the character is at the left (portrait, kind
// and world, name, what they are doing, the personality as written, who decides, the price and the last run) and What
// Teo did at the right as a path of moment cards, newest first. N turns the left column into the two fields in place.
// Choosing a model, Compare's question and Ask keep their flows in the right column until their own redraws land. It
// draws from what it is given and says what it was asked through `act`; contextual-world.ts reads, writes and runs.
// The parts are world-ui-record.ts's, the places day-rows.mjs's, the page's own type world-ui-record-day.css's, the
// words the words modules'.
import { label, orb as runOrb, page, type Page } from './world-ui.ts';
import { element, ground, keyButton, keyRow, orb as portraitOrb, pictureBox, px, sentence, type Parts } from './world-ui-record.ts';
import { CHARACTER_WORDS, modelLine, routineRow, priceWords, whatDid, nothingYet, readingRecord, called } from './character-words.mjs';
import { PERSONALITY_LIMITS, PERSONALITY_WORDS, counter, length, notRead, readsEach, savedNote, writtenWords } from './personality-words.mjs';
import { COMPARE_WORDS } from './compare-words.mjs';
import { PATH_WORDS, byParts, plural } from './history-words.mjs';
import { DAY_LAYOUTS, dayLayout, dayView, stepChoice } from './day-rows.mjs';
import './world-ui-record-day.css';

type Who = ReturnType<typeof called>;
type Layout = typeof DAY_LAYOUTS.wide;
type View = ReturnType<typeof dayView>;
type Act = (action: string, value?: unknown) => void;

export interface DidRow {
  readonly time: string;
  readonly what: string;
  readonly sub: string;
  /** Whether a recorded decision stands behind the row, which [Enter] See the decision opens. */
  readonly decision: boolean;
  /** A line said to the character, or to everyone near (T6): never chosen. */
  readonly heard?: boolean;
  /** The moment's title in JOURNEY's moment words (R1), "Teo spoke to Marco"; absent, the row's own words (`what`). */
  readonly title?: string | null;
  /** The line said, as drawn: in curly quotes, a line said to the character with its speaker first (T6's heard). */
  readonly said?: string | null;
  /** Whether the row is a moment of the moments read: only such a row draws a picture tile (R5e). */
  readonly moment?: boolean;
  /** The moment's picture, as an image address (R2); absent or null on a moment, the quiet tile until it comes. */
  readonly picture?: string | null;
  /** The served name of the model that decided, or null where none did; absent, the who line is `sub` as worded. */
  readonly model?: string | null;
  /** How many choices that model was offered (the decision's count); null where it is not known. */
  readonly choices?: number | null;
  /** Who decided where no model did (T7): a person playing, or an outside program. */
  readonly decider?: 'person' | 'external' | null;
}

export interface ModelChoice {
  /** null for Routine. */
  readonly model: { readonly provider: string; readonly modelId: string; readonly name: string; readonly price: unknown; readonly local?: boolean } | null;
  readonly current: boolean;
}

export interface CharacterPageState {
  readonly who: Who;
  /** The kind and the world: "Resident · Terraces on the bay". */
  readonly sub: string;
  /** Whether this person may choose the character's model here (the role's write is permitted). */
  readonly assignable: boolean;
  /** The assigned model, or null for the routine; undefined while the models are read. */
  readonly model: { readonly name: string; readonly price: unknown; readonly local?: boolean } | null | undefined;
  /** Whether a run can be asked of a model here: false where no model is connected. */
  readonly connected: boolean;
  /** Why the character's model does not run here, in the Run section's words (J2, J22), or null where it can. */
  readonly runLine: string | null;
  readonly run: {
    readonly open: boolean;
    /** "10 minutes · at most $0.05", or the running line. */
    readonly big: string;
    readonly small: string;
    readonly busy: boolean;
    /** A refusal in plain words, or null. */
    readonly refusal: string | null;
  };
  /** The rows of What Teo did, newest first; null while they are read. */
  readonly did: readonly DidRow[] | null;
  /** The chosen row, which the arrows move; null with none. */
  readonly didFocus: number | null;
  /** Whether [Q] Ask is offered. */
  readonly canAsk: boolean;
  /** Ask's questions in the right column in place of the rows, and an answer once one is read; or null. */
  readonly ask: {
    readonly questions: readonly string[];
    readonly focus: number;
    readonly busy: boolean;
    /** The question answered, its answer's lines (a note line marked), or a failure. */
    readonly asked: string | null;
    readonly answer: readonly { readonly text: string; readonly note: boolean }[] | null;
    readonly failure: string | null;
  } | null;
  /** "Last run 06:00 to 07:15 · 12 decisions · spent $0.0042", or null. */
  readonly lastRun: string | null;
  /**
   * The personality its owner wrote for a being they placed ({ character, shown }), or null for
   * anything else, whose page has no personality and no [N] (spec 8.6).
   */
  readonly personality: { readonly character: { readonly name: string | null; readonly about: string | null } | null; readonly shown: boolean } | null;
  /** The personality being written, or null: its fields hold their own words while a person types. */
  readonly editing: { readonly session: string; readonly refusal: string | null; readonly busy: boolean } | null;
  /** The model list while choosing, or null. */
  readonly choosing: { readonly choices: readonly ModelChoice[] | null; readonly focus: number; readonly refusal: string | null; readonly busy: boolean } | null;
  /** Whether [C] Compare is offered (frame 12a). */
  readonly canCompare: boolean;
  /**
   * The question before a comparison (frame 12a, rulings C1 and C2), in the right column in place of
   * the rows, or null. Its Big line, explanation and figures are the server's offer, worded.
   */
  readonly compare: {
    /** With nothing to ask of any model (C4), the one line drawn alone: no rows, orb or arrows. */
    readonly nothing: string | null;
    readonly big: string;
    readonly explain: string;
    /** The models to ask beside the recorded one: neither Routine nor the character's own. */
    readonly choices: readonly ModelChoice[] | null;
    readonly focus: number;
    /** "At most $0.01", or while the asks run "Asking 5 of 24 · $0.0008 of $0.01"; null while the offer is read. */
    readonly figure: string | null;
    readonly asking: boolean;
    /** Why the chosen model may not be asked, or that the offer could not be read, in words. */
    readonly note: string | null;
    readonly canStart: boolean;
  } | null;
  /** The character's round portrait, as an image address (MOTION's, R2); absent or null, the first letter on the quiet orb. */
  readonly portrait?: string | null;
  /** What the character is doing now, in the society's activity words ("Waiting by the bench", J30); absent, left out. */
  readonly doing?: string | null;
  /**
   * Who decides, in J30's small-print words: "Nemotron 3 Nano 30B decides for Teo", "Teo follows a routine", "A person
   * is playing Teo", "Teo comes from an outside program". Absent, the model's name, or the Run section's line.
   */
  readonly decides?: string | null;
  /** Who decides where a model does not (T7); with one, the model's line carries no Current tag. */
  readonly decider?: 'person' | 'external' | null;
  /**
   * While a run is on: J30's "Teo's model is deciding · 9:13 left" in place of the last run, or null where this
   * character's model is not deciding. Absent, the run's own line (`run.big`) while one is on.
   */
  readonly running?: string | null;
  /** A still of the view the character was chosen in, faded behind the page; absent, the live world shows through. */
  readonly still?: string | null;
}

export interface CharacterPage {
  draw(state: CharacterPageState): void;
  /** Hides the page while a decision's page shows over the world in its place. */
  hide(hidden: boolean): void;
  close(): void;
}

/** How long "Saved. Teo's model reads it from the next minute." stays in the who column (frame 11). */
export const SAVED_NOTE_MS = 4000;

/**
 * Opens the page in `host`; `act` hears model, run, stop, choose (with an index), use, back, row
 * and inspect (with a row's index), ask and question (with a question's index), personality, draft
 * (with { name, about }), save, compare, compareChoose (with an index) and compareStart.
 */
export function openCharacterPage(host: HTMLElement, act: Act): CharacterPage {
  const sheet: Page = page({ form: 'character' });
  sheet.root.classList.add('wu-record', 'wu-record-day');
  sheet.root.setAttribute('aria-label', 'Character');
  // History's key row stands in for page()'s own.
  sheet.keys.hidden = true;
  const [world, wash] = ground(null);
  const layer = element('div', 'wu-day-layer');
  sheet.content.prepend(world, wash, layer);
  sheet.open(host);

  let last: CharacterPageState | null = null;
  let shown = '';
  /** Where What Teo did's view started, kept between draws so a choice in view moves nothing. */
  let first: number | null = null;
  /** The personality's fields while it is written: kept in place, so typing never loses its place. */
  let editor: Editor | null = null;
  /** The personality as it stood when a save was sent, until the page sees it saved or refused. */
  let savingFrom: string | null = null;
  let saved = false;
  let savedTimer: ReturnType<typeof setTimeout> | null = null;
  const resized = () => render();
  addEventListener('resize', resized);

  function render() {
    const state = last;
    if (!state) return;
    const width = host.clientWidth || innerWidth, height = host.clientHeight || innerHeight;
    const key = `${JSON.stringify(state)}|${width}x${height}|${saved}`;
    if (key === shown) return;
    shown = key;
    const editing = state.editing && state.personality ? state.editing : null;
    if (editing && editor?.session === editing.session) {
      editor.update(editing);
      return;
    }
    editor = null;
    const layout = dayLayout(width);
    sheet.root.classList.toggle('wu-hr-narrow', layout === DAY_LAYOUTS.narrow);
    sheet.root.setAttribute('aria-label', state.who.title);
    sheet.root.toggleAttribute('data-editing', Boolean(editing));
    if (state.still) {
      world.style.backgroundImage = `url("${state.still}")`;
      sheet.root.removeAttribute('data-live');
    } else {
      world.style.backgroundImage = '';
      sheet.root.setAttribute('data-live', '');
    }
    const focused = document.activeElement instanceof HTMLElement && sheet.root.contains(document.activeElement) ? document.activeElement.dataset['focusKey'] ?? null : null;

    const parts: HTMLElement[] = [];
    let keys: HTMLElement[];
    let title: HTMLElement | null = null;
    if (editing) {
      editor = drawEditor(state, editing, layout, act);
      parts.push(editor.column);
      keys = editor.keys;
    } else {
      const who = drawWho(state, layout, saved);
      title = who.title;
      parts.push(who.column);
      keys = [];
    }
    const side = !editing && (state.compare || state.choosing || state.ask);
    if (side) {
      parts.push(drawSide(state, layout, width, act));
      keys = sideKeys(state, act);
    } else {
      const view = state.did?.length ? dayView({ count: state.did.length, chosen: state.didFocus, first, layout, width, height }) : null;
      first = view ? view.first : null;
      parts.push(drawDay(state, layout, view, width, height, Boolean(editing), act));
      if (!editing) keys = dayKeys(state, act);
    }
    keys.forEach((one) => { one.dataset['focusKey'] ??= 'key-' + (one.getAttribute('aria-keyshortcuts') ?? one.textContent); });
    const row = keyRow([]);
    row.append(...keys);
    parts.push(row);
    layer.replaceChildren(...parts);
    if (editor) return;
    const again = focused ? [...sheet.root.querySelectorAll<HTMLElement>('[data-focus-key]')].find((node) => node.dataset['focusKey'] === focused) : null;
    if (again) again.focus({ preventScroll: true });
    else if (!sheet.root.contains(document.activeElement)) title?.focus({ preventScroll: true });
  }

  function showSaved() {
    saved = true;
    if (savedTimer) clearTimeout(savedTimer);
    savedTimer = setTimeout(() => { saved = false; savedTimer = null; render(); }, SAVED_NOTE_MS);
  }

  return {
    draw(state) {
      // A save shows as the fields closing over a personality that changed while it was sent (frame 11's note).
      const character = JSON.stringify(state.personality?.character ?? null);
      if (state.editing) savingFrom = state.editing.busy ? savingFrom ?? character : null;
      else if (savingFrom !== null && character !== savingFrom) {
        savingFrom = null;
        if (state.personality?.shown) showSaved();
      }
      last = state;
      render();
    },
    hide(hidden) { sheet.root.hidden = hidden; },
    close() {
      removeEventListener('resize', resized);
      if (savedTimer) clearTimeout(savedTimer);
      sheet.close();
    },
  };
}

/** A key the page answers, with its shortcut said for a reader, and drawn dimmed where it cannot act now. */
function key(caps: readonly string[], word: string, shortcut: string, onPress: () => void, disabled = false): HTMLButtonElement {
  const button = keyButton(caps, word, onPress);
  button.setAttribute('aria-keyshortcuts', shortcut);
  button.disabled = disabled;
  return button;
}

/** A key the page answers with no button to press (the arrows while choosing). */
function hint(caps: readonly string[], word: string, shortcut: string): HTMLSpanElement {
  const made = element('span', 'wu-hr-key wu-day-hint');
  made.setAttribute('aria-keyshortcuts', shortcut);
  for (const cap of caps) made.append(element('kbd', 'wu-hr-cap', cap));
  made.append(element('span', 'wu-hr-key-word', word));
  return made;
}

/** The round portrait, 3px ground ring and soft shadow; the first letter on the quiet orb until one exists. */
function portrait(state: CharacterPageState, layout: Layout): HTMLElement {
  const face = portraitOrb(state.who.title, layout.portrait, state.portrait ?? null, state.who.title);
  face.classList.add('wu-day-face');
  return face;
}

/** Who the character is (r06, left 120, top 84, 600 wide; 80 and 480 at 1440). */
function drawWho(state: CharacterPageState, layout: Layout, saved: boolean): { column: HTMLElement; title: HTMLElement } {
  const column = element('div', 'wu-day-who');
  px(column, layout.left, layout.top, layout.whoWidth);
  const title = element('h1', 'wu-day-name', state.who.title);
  title.tabIndex = -1;
  title.dataset['focusKey'] = 'title';
  column.append(portrait(state, layout), element('div', 'wu-hr-over', state.sub), title);
  if (state.doing) column.append(element('p', 'wu-day-doing', state.doing));
  if (state.personality) {
    const block = element('section', 'wu-day-personality');
    block.dataset['section'] = 'personality';
    // As the person wrote it: the words, or the name where only a name is written.
    const written = state.personality.character?.about?.trim() || state.personality.character?.name?.trim();
    if (written) block.append(element('p', 'wu-day-persona', writtenWords(written)), element('p', 'wu-day-by', PERSONALITY_WORDS.writtenByYou));
    else block.append(element('p', 'wu-day-none', PERSONALITY_WORDS.noneWritten));
    if (saved) {
      const note = element('p', 'wu-day-saved', savedNote(state.who));
      note.setAttribute('role', 'status');
      block.append(note);
    }
    column.append(block);
  }
  column.append(...decidesBlock(state));
  return { column, title };
}

/**
 * Who decides (Sans 18, with the Current tag for a model), then the small print: the price, the last run or, while one
 * is on, the running line; and where a run is offered and not on, what [R] would start, its length and most it may
 * spend ("10 minutes · at most $0.05") and who it asks, so a run never starts without its limits on screen.
 */
function decidesBlock(state: CharacterPageState): HTMLElement[] {
  const block = element('section', 'wu-day-decides-block');
  block.dataset['section'] = 'model';
  const decides = element('p', 'wu-day-decides');
  if (state.decides) decides.append(state.decides);
  else if (state.model) decides.append(sentence('span', '', [{ model: state.model.name }]));
  else if (state.model === null) decides.append(state.runLine ?? CHARACTER_WORDS.routine);
  else decides.append(CHARACTER_WORDS.readingModels);
  if (state.model && !state.decider) decides.append(element('span', 'wu-hr-tag', CHARACTER_WORDS.current));
  block.append(decides);
  const offered = Boolean(state.model) && state.connected;
  const lines: (string | HTMLElement)[] = [];
  if (state.model) lines.push(modelLine(state.model) ?? '');
  const running = !state.run.open ? null : state.running !== undefined ? state.running : offered ? state.run.big : null;
  if (running) lines.push(running);
  else if (state.lastRun) lines.push(state.lastRun);
  if (offered && !state.run.open) {
    // The run's figures wrap only between their parts, never inside a figure (J9).
    const figures = element('span');
    state.run.big.split(' \u00b7 ').forEach((part, index) => {
      if (index) figures.append(' \u00b7 ');
      figures.append(element('span', 'wu-nowrap', part));
    });
    lines.push(figures, state.run.small);
  }
  // Why a chosen model does not run here (J22); with no model, who decides already says the routine.
  if (state.model && state.runLine) lines.push(state.runLine);
  const small = element('p', 'wu-day-small');
  lines.filter(Boolean).forEach((line, index) => {
    if (index) small.append(element('br'));
    const shown = element('span', 'wu-day-line');
    shown.append(line);
    small.append(shown);
  });
  if (small.childNodes.length) block.append(small);
  if (state.run.refusal) {
    const refused = element('p', 'wu-day-refused', state.run.refusal);
    refused.setAttribute('role', 'status');
    block.append(refused);
  }
  return [block];
}

/** A card's who line (r06): "By Nemotron 3 Nano 30B · 7 choices", "By a person playing", "Routine". */
function decidedBy(row: DidRow): Parts | string | null {
  if (row.decider === 'person') return PATH_WORDS.personPlaying;
  if (row.decider === 'external') return PATH_WORDS.outsideProgram;
  if (row.model === undefined) return row.sub || null;
  if (!row.model) return CHARACTER_WORDS.routine;
  const by: Parts = byParts({ kind: 'model', model: { name: row.model } });
  return Number.isSafeInteger(row.choices) && (row.choices ?? 0) > 0 ? [...by, ` · ${plural(row.choices, 'choice')}`] : by;
}

const SVG = 'http://www.w3.org/2000/svg';

/** The path at x 880 from the newest card in view to the oldest, a hollow dot per card, the chosen one filled. */
function pathSvg(view: View, chosen: number | null, layout: Layout, width: number, height: number): SVGSVGElement {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'wu-day-path');
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.setAttribute('aria-hidden', 'true');
  if (!view.path) return svg;
  const line = document.createElementNS(SVG, 'path');
  line.setAttribute('class', 'line');
  line.setAttribute('d', `M ${view.path.x} ${view.path.from} L ${view.path.x} ${view.path.to}`);
  svg.append(line);
  for (const item of view.items) {
    const dot = document.createElementNS(SVG, 'circle');
    dot.setAttribute('class', 'dot');
    dot.setAttribute('cx', String(view.path.x));
    dot.setAttribute('cy', String(item.dot));
    dot.setAttribute('r', String(layout.dotRadius));
    dot.dataset['chosen'] = String(item.index === chosen);
    svg.append(dot);
  }
  return svg;
}

/** What Teo did (from x 860, top 84): its label, the path and the cards in view; dimmed to .32 while the fields are open. */
function drawDay(state: CharacterPageState, layout: Layout, view: View | null, width: number, height: number, dim: boolean, act: Act): HTMLElement {
  const day = element('div', 'wu-day-did');
  if (dim) {
    day.dataset['dim'] = '';
    day.setAttribute('aria-hidden', 'true');
  }
  const over = element('div', 'wu-hr-over wu-day-over', whatDid(state.who));
  px(over, layout.labelX, layout.top);
  day.append(over);
  if (!state.did || !view) {
    const note = element('p', 'wu-day-note', state.did ? nothingYet(state.who) : readingRecord(state.who));
    px(note, layout.labelX, layout.firstTop);
    day.append(note);
    return day;
  }
  day.append(pathSvg(view, state.didFocus, layout, width, height));
  for (const placed of view.items) {
    const row = state.did[placed.index]!;
    const chosen = placed.index === state.didFocus && !row.heard;
    const item = element('div', 'wu-day-item');
    px(item, layout.itemX, placed.top, view.itemWidth);
    if (row.heard) item.dataset['heard'] = '';
    else if (!dim) item.addEventListener('click', () => act('row', placed.index));
    if (chosen) item.setAttribute('aria-current', 'true');
    const words = element('div', 'wu-day-words');
    if (row.time) words.append(element('div', 'wu-hr-time', row.time));
    words.append(element('div', 'wu-day-title', row.title || row.what));
    if (row.said) words.append(element('div', 'wu-hr-said wu-day-said', row.said));
    const by = decidedBy(row);
    const whoLine = element('div', 'wu-hr-who wu-day-who-line');
    if (by) whoLine.append(sentence('span', 'wu-day-decided', by));
    if (chosen && row.decision && !dim) {
      const see = key(['Enter'], PATH_WORDS.seeDecision, 'Enter', () => act('inspect', placed.index));
      see.classList.add('wu-day-see');
      see.dataset['focusKey'] = 'see';
      see.addEventListener('click', (event) => event.stopPropagation());
      whoLine.append(see);
    }
    if (whoLine.childNodes.length) words.append(whoLine);
    // A choice that made no moment has no picture to come, so no tile: its words keep the pictured rows' column (R5e).
    const tile = row.moment ? pictureBox(row.picture ?? null, layout.picture.width, layout.picture.height) : element('div', 'wu-day-untiled');
    if (!row.moment) tile.style.width = `${layout.picture.width}px`;
    item.append(tile, words);
    day.append(item);
  }
  return day;
}

/** The day's keys (History's row), each only where it works (K6). */
function dayKeys(state: CharacterPageState, act: Act): HTMLElement[] {
  const did = state.did ?? [];
  const choosable = (index: number) => !did[index]?.heard;
  const offered = Boolean(state.model) && state.connected;
  // The button steps earlier, and from the oldest back to the newest; the keys step either way (the host's).
  const earlier = () => {
    const next = stepChoice(did.length, state.didFocus, 1, choosable);
    const target = next !== state.didFocus ? next : stepChoice(did.length, null, 1, choosable);
    if (target !== null && target !== state.didFocus) act('row', target);
  };
  return [
    ...(did.filter((row) => !row.heard).length >= 2 ? [key(['↑', '↓'], PATH_WORDS.earlierLater, 'ArrowUp ArrowDown', earlier)] : []),
    ...(state.assignable ? [key(['M'], CHARACTER_WORDS.model, 'M', () => act('model'))] : []),
    ...(state.personality ? [key(['N'], PERSONALITY_WORDS.label, 'N', () => act('personality'))] : []),
    ...(offered ? [key(['R'], state.run.open ? CHARACTER_WORDS.stop : CHARACTER_WORDS.run, 'R', () => act(state.run.open ? 'stop' : 'run'), state.run.busy)] : []),
    ...(state.canCompare ? [key(['C'], COMPARE_WORDS.compare, 'C', () => act('compare'))] : []),
    ...(state.canAsk ? [key(['Q'], CHARACTER_WORDS.ask, 'Q', () => act('ask'))] : []),
    key(['Esc'], CHARACTER_WORDS.back, 'Escape', () => act('back')),
  ];
}

/** The keys while choosing a model, asking Compare's question or Ask's. */
function sideKeys(state: CharacterPageState, act: Act): HTMLElement[] {
  const back = (word: string = CHARACTER_WORDS.back) => key(['Esc'], word, 'Escape', () => act('back'));
  const choose = () => hint(['↑', '↓'], CHARACTER_WORDS.choose, 'ArrowUp ArrowDown');
  if (state.compare) {
    if (state.compare.asking) return [back(COMPARE_WORDS.stop)];
    if (state.compare.nothing) return [back()];
    return [choose(), ...(state.compare.note ? [] : [key(['Enter'], COMPARE_WORDS.compare, 'Enter', () => act('compareStart'), !state.compare.canStart)]), back()];
  }
  if (state.choosing) return [choose(), key(['Enter'], CHARACTER_WORDS.useThisModel, 'Enter', () => act('use'), state.choosing.busy || !state.choosing.choices), back()];
  if (state.ask) return [choose(), key(['Enter'], CHARACTER_WORDS.ask, 'Enter', () => act('question'), state.ask.busy), back()];
  return [back()];
}

/** A model's row in a list: its name (with Current), its price at the right. */
function modelRows(choices: readonly ModelChoice[], focus: number, labelled: string, onChoose: ((index: number) => void) | null, onUse: ((index: number) => void) | null, current: boolean): HTMLElement {
  const list = element('ul', 'wu-model-rows');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', labelled);
  choices.forEach((choice, index) => {
    const item = element('li', 'wu-model-row');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(index === focus));
    const name = element('span', 'wu-model-name', choice.model ? choice.model.name : CHARACTER_WORDS.routine);
    if (current) {
      item.dataset['current'] = String(choice.current);
      if (choice.current) name.append(element('span', 'wu-model-current', CHARACTER_WORDS.current));
    }
    item.append(name, element('span', 'wu-model-price', choice.model ? priceWords(choice.model) ?? '' : routineRow()));
    if (onChoose) item.addEventListener('click', () => onChoose(index));
    if (onUse) item.addEventListener('dblclick', () => onUse(index));
    list.append(item);
  });
  return list;
}

function refusalLine(words: string): HTMLElement {
  const line = element('p', 'wu-small-text wu-refused', words);
  line.setAttribute('role', 'status');
  return line;
}

/** Choosing a model, Compare's question (12a) or Ask, in the right column in place of the day. */
function drawSide(state: CharacterPageState, layout: Layout, width: number, act: Act): HTMLElement {
  const side = element('section', 'wu-day-side');
  px(side, layout.labelX, layout.top, Math.min(560, width - layout.labelX - layout.keysRight));
  if (state.compare) {
    const compare = state.compare;
    side.classList.add('wu-cmp-ask');
    if (compare.asking) side.dataset['asking'] = '';
    side.append(label(COMPARE_WORDS.compare));
    if (compare.nothing) {
      // Nothing to ask of any model (C4): the line alone.
      const line = element('p', 'wu-small-text wu-cmp-nothing', compare.nothing);
      line.setAttribute('role', 'status');
      side.append(line);
      return side;
    }
    side.append(element('p', 'wu-big', compare.big), element('p', 'wu-small-text wu-cmp-explain', compare.explain));
    if (!compare.choices) side.append(element('p', 'wu-char-note', CHARACTER_WORDS.readingModels));
    else side.append(element('div', 'wu-model-head wu-small-text wu-faint', CHARACTER_WORDS.perMillion),
      modelRows(compare.choices, compare.focus, COMPARE_WORDS.compare, compare.asking ? null : (index) => act('compareChoose', index), null, false));
    if (compare.note) side.append(refusalLine(compare.note));
    else {
      const row = element('div', 'wu-orb-row');
      const button = runOrb({ word: COMPARE_WORDS.compare, onPress: () => act('compareStart'), disabled: !compare.canStart });
      button.dataset['focusKey'] = 'compare';
      if (!compare.canStart) button.tabIndex = -1;
      const words = element('div');
      // The figure wraps only between its parts, never inside a figure (as the Run line, J9).
      const figure = element('p', 'wu-big');
      (compare.figure ?? '').split(' · ').forEach((part, index) => {
        if (index) figure.append(' · ');
        figure.append(element('span', 'wu-nowrap', part));
      });
      words.append(figure, element('p', 'wu-small-text', COMPARE_WORDS.askedOnce));
      row.append(button, words);
      side.append(row);
    }
    return side;
  }
  if (state.choosing) {
    const choosing = state.choosing;
    side.append(label(CHARACTER_WORDS.chooseModel), element('p', 'wu-small-text wu-model-intro', CHARACTER_WORDS.pickingSpendsNothing));
    if (!choosing.choices) side.append(element('p', 'wu-char-note', CHARACTER_WORDS.readingModels));
    else side.append(element('div', 'wu-model-head wu-small-text wu-faint', CHARACTER_WORDS.perMillion),
      modelRows(choosing.choices, choosing.focus, CHARACTER_WORDS.chooseModel, (index) => act('choose', index), (index) => act('use', index), true));
    if (choosing.refusal) side.append(refusalLine(choosing.refusal));
    return side;
  }
  const ask = state.ask!;
  side.append(label(CHARACTER_WORDS.ask));
  const list = element('ul', 'wu-model-rows wu-ask-rows');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', CHARACTER_WORDS.ask);
  ask.questions.forEach((question, index) => {
    const item = element('li', 'wu-model-row wu-ask-row');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', String(index === ask.focus));
    item.append(element('span', 'wu-model-name', question));
    item.addEventListener('click', () => act('question', index));
    list.append(item);
  });
  side.append(list);
  const answer = element('div', 'wu-ask-answer');
  answer.setAttribute('role', 'status');
  if (ask.busy) answer.append(element('p', 'wu-char-note', CHARACTER_WORDS.askReading));
  else if (ask.failure) answer.append(element('p', 'wu-small-text wu-refused', ask.failure));
  else if (ask.answer) {
    if (ask.asked) answer.append(element('p', 'wu-ask-asked wu-small-text wu-faint', ask.asked));
    if (!ask.answer.length) answer.append(element('p', 'wu-char-note', CHARACTER_WORDS.noAnswer));
    for (const line of ask.answer) answer.append(element('p', line.note ? 'wu-char-note' : 'wu-ask-line', line.text));
  }
  side.append(answer);
  return side;
}

interface Editor {
  readonly session: string;
  readonly column: HTMLElement;
  readonly keys: HTMLElement[];
  update(editing: NonNullable<CharacterPageState['editing']>): void;
}

/**
 * The personality's fields in place of the who column (r11): Name and Personality, each with its count over it, what
 * the model makes of it, a refusal where one came; [Enter] Save and [Esc] Cancel in the key row. The fields keep what
 * is typed; each change goes to `act('draft', { name, about })`.
 */
function drawEditor(state: CharacterPageState, editing: NonNullable<CharacterPageState['editing']>, layout: Layout, act: Act): Editor {
  const column = element('div', 'wu-day-who wu-day-editor');
  px(column, layout.left, layout.top, layout.whoWidth);
  const written = state.personality?.character;
  const field = (labelText: string, value: string, maximum: number, multiline: boolean, className: string) => {
    const wrap = element('label', 'wu-day-field-wrap');
    const head = element('span', 'wu-day-label');
    const count = element('span', 'wu-day-count', counter(value, maximum));
    head.append(element('span', '', labelText), count);
    const input = multiline ? element('textarea', `wu-day-field ${className}`) : element('input', `wu-day-field ${className}`);
    if (input instanceof HTMLTextAreaElement) input.rows = 4; else input.type = 'text';
    input.value = value;
    input.autocomplete = 'off';
    wrap.append(head, input);
    return { wrap, input, count, maximum };
  };
  const name = field(PERSONALITY_WORDS.name, written?.name ?? '', PERSONALITY_LIMITS.name, false, 'wu-day-name-field');
  const about = field(PERSONALITY_WORDS.about, written?.about ?? '', PERSONALITY_LIMITS.about, true, 'wu-day-about-field');
  const reads = element('p', 'wu-day-reads', state.personality?.shown ? readsEach(state.who) : notRead(state.who));
  const refusal = element('p', 'wu-day-refused', editing.refusal ?? '');
  refusal.setAttribute('role', 'status');
  refusal.hidden = !editing.refusal;
  column.append(portrait(state, layout), element('div', 'wu-hr-over', state.sub), name.wrap, about.wrap, reads, refusal);
  const save = key(['Enter'], PERSONALITY_WORDS.save, 'Enter', () => act('save'), editing.busy);
  const cancel = key(['Esc'], PERSONALITY_WORDS.cancel, 'Escape', () => act('back'));
  const counts = () => {
    for (const one of [name, about]) {
      one.count.textContent = counter(one.input.value, one.maximum);
      one.count.classList.toggle('wu-over', length(one.input.value) > one.maximum);
    }
  };
  counts();
  for (const one of [name, about]) one.input.addEventListener('input', () => { counts(); act('draft', { name: name.input.value, about: about.input.value }); });
  queueMicrotask(() => {
    about.input.focus({ preventScroll: true });
    const end = about.input.value.length;
    about.input.setSelectionRange(end, end);
  });
  return {
    session: editing.session, column, keys: [save, cancel],
    update(now) {
      refusal.textContent = now.refusal ?? '';
      refusal.hidden = !now.refusal;
      save.disabled = now.busy;
      counts();
    },
  };
}
