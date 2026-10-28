// Making a creature where it will stand (DESIGN's R-CREATURE-BUILD-SHEET.md, pictures r-creature17t, 19t and
// 19b; the money words of WORDS.md's unit 9 entry of 22 October; web notes in Create's words of 25 October, with
// "creature" for "place", WORDS.md 12:34): the field low in the middle, the line under it and the web notes box,
// the label over the stand, the making group with the notes from the web, and the made group beside it. They only
// draw; what a key does is world-creature.ts's. Their look lives in world-ui-creature.css, from world-ui.css's
// tokens.
import { glyphRows, shade } from './world-ui.ts';
import { scrollingColumn } from './world-page-frame.ts';
import './world-ui-creature.css';

/** Each note aspect's label by its key, from the reference aspect catalogs (a later version's label wins). */
const ASPECT_LABELS: ReadonlyMap<string, string> = new Map(
  Object.entries(import.meta.glob('../../../assets/catalogs/reference-sources/reference-aspect.v*.json', { eager: true, import: 'default' }))
    .sort(([a], [b]) => a.localeCompare(b, 'en', { numeric: true }))
    .flatMap(([, catalog]) => ((catalog as { readonly entries?: readonly { readonly key: string; readonly label: string }[] }).entries ?? [])
      .map((entry) => [entry.key, entry.label] as const)),
);

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

/** Every word these screens show, as DESIGN worded them. */
export const CREATURE_WORDS = Object.freeze({
  fieldLabel: 'What does the creature look like?',
  appearsHere: 'The creature appears here',
  make: 'Make',
  place: 'Place',
  tryAgain: 'Try again',
  back: 'Back',
  making: 'Making your creature',
  waiting: 'Waiting to start',
  drafting: 'Making the creature',
  madeFrom: 'Made from your words',
  untitled: 'Creature',
  notOffered: 'Making creatures isn\'t offered here.',
  budgetSpent: 'The budget for AI models here is spent.',
  spendingPaused: 'Spending on AI models is paused here.',
  modelSilent: 'The AI model did not answer, so nothing was made. Try again in a minute.',
  stoppedPartWay: 'Making stopped part way, so nothing was kept. Try again.',
  notStarted: 'Making did not start in time, so nothing was made. Try again in a few minutes.',
  notSent: 'The rules here kept your words from being sent to the model, so nothing was made.',
  pictureWithdrawn: 'The picture it was to be made from was withdrawn, so nothing was made.',
  hourLimit: 'You\'ve made as many creatures as you can this hour. Try again later.',
  wentWrong: 'Something went wrong while making it, so nothing was made. Try again.',
  takingLonger: 'This is taking longer than usual. The creature waits in Creatures when it\'s done.',
  /** The draft could no longer be read (refused, or no answer): how it went is not known here. */
  cantTell: 'This page can\'t tell how the making went. If the creature was made, it waits in Creatures.',
  placingNow: 'Placing…',
  /** The made card where no stand was found ahead (rehearsal run 7): where the creature is and how to place it. */
  nowhereToStand: 'There is no open ground ahead to stand it on, so it waits in Creatures. Pick it there to place it.',
  /** The line under the field begins with what makes it: an open model, named where the offer names one (DESIGN, A1). */
  maker: 'An open model',
  makes: 'makes the creature from your words',
  seenSpend: 'and you see what it really spent',
  leave: 'You can leave this page: the making carries on, and the creature waits in Creatures.',
  kept: 'kept in Creatures',
  /** The web notes box under the line (Create's frame 20 words). */
  notesAsk: 'Read the web first for what such a creature looks like',
  /** The notes' steps before the drafting's (Create's frame 21), by the request's step names. */
  notesSteps: Object.freeze({ plan: 'Choosing what to look up', search: 'Searching the web', read: 'Writing notes from what it found' }) as Readonly<Record<string, string>>,
  fromWeb: 'From the web',
  notesFailed: 'The web notes could not be made, so it is made from your words alone.',
  notesNone: 'The searches found nothing to use, so it is made from your words alone.',
});

/** At most this many notes in the making group; the rest are counted under them (DESIGN, 12:34). */
export const NOTES_SHOWN = 4;

const searchesWord = (count: number): string => `${count} web ${count === 1 ? 'search' : 'searches'}`;

/** Under the web notes box: where the person's words go and the most the notes add (Create's frame 20). */
export function notesAskLine(searchesAtMost: number, maximumUsd: string): string {
  return `Up to ${searchesWord(searchesAtMost)} ${searchesAtMost === 1 ? 'goes' : 'go'} to Tavily, made from your words with the names and details this install holds as yours left out, and Tavily keeps them. Adds at most ${money(maximumUsd)}.`;
}

/** Under the notes from the web: what wrote them and what they are (Create's frame 21). */
export function notesWrote(searches: number): string {
  return `A model wrote these from ${searchesWord(searches)}. They help make the creature and are never facts about it.`;
}

/** The made group's line: "Made from your words", and where its drafter was handed notes, "... and 7 notes from the web". */
export function madeFromLine(notes: number): string {
  return notes > 0 ? `${CREATURE_WORDS.madeFrom} and ${notes} ${notes === 1 ? 'note' : 'notes'} from the web` : CREATURE_WORDS.madeFrom;
}

/** Dollars as the workspace writes them (P1): "$0.37", under a cent "$0.0042", "less than $0.0001". */
export function money(usd: string): string {
  const value = Number(usd);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value === 0) return '$0';
  if (value < 0.00005) return 'less than $0.0001';
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

/**
 * The line under the field: what makes it (the model by its served name, where named), the most it
 * may cost and how long it takes, where served (M1), and that the made creature says what it really
 * spent (its small print does): "An open model, Nemotron 3 Super 120B, makes the creature from your
 * words: at most $0.10, about 18 seconds, and you see what it really spent."
 */
export function makerLine(priceUsdAtMost: string | null, typicalSeconds: number | null, modelName: string | null = null): string {
  const who = modelName === null ? CREATURE_WORDS.maker : `${CREATURE_WORDS.maker}, ${modelName},`;
  if (priceUsdAtMost === null) return `${who} ${CREATURE_WORDS.makes}.`;
  // With web notes asked for, no measured time covers the searches, so the line gives the most alone.
  const about = typicalSeconds === null ? '' : ` about ${typicalSeconds} seconds,`;
  return `${who} ${CREATURE_WORDS.makes}: at most ${money(priceUsdAtMost)},${about} ${CREATURE_WORDS.seenSpend}.`;
}

/** The made group's small print: the model, the whole spend where served (M2), and where it is kept. */
export function madeSmallPrint(modelName: string | null, spentUsd: string | null): string {
  return [modelName === null ? null : `Made by ${modelName}`, spentUsd === null ? null : `spent ${money(spentUsd)}`, CREATURE_WORDS.kept]
    .filter((part): part is string => part !== null).join(' · ');
}

const quoted = (words: string): string => `“${words}”`;

/**
 * A group's words in a part of their own (world-page-frame.ts): where a short window leaves less room than they take,
 * that part scrolls with the shared frame's fades and track, and the shade's soft backing stays whole around it.
 */
function groupBody(root: HTMLElement): HTMLElement {
  const body = element('div', 'wu-creature-body');
  const scroll = scrollingColumn(body);
  root.append(scroll.column);
  // A window's height moves the room the group has, and words come and go (a step's, placeRow's): read again whenever
  // the part's own size or its words change.
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => scroll.update()).observe(body);
  new MutationObserver(() => scroll.update()).observe(body, { childList: true, subtree: true, characterData: true });
  return body;
}

export interface CreatureField {
  readonly root: HTMLElement;
  readonly input: HTMLTextAreaElement;
  /** The line under the field: the maker line, or a refusal in the refused ink. */
  line(words: string, refused?: boolean): void;
  /** The count "81 of 400" and the key at .55 with the field empty. */
  count(characters: number, maximum: number): void;
}

/** The describe field (r17t): its label, the words, the count and the key, and the line under it. */
export function creatureField({ maximum, onMake }: { readonly maximum: number; readonly onMake: () => void }): CreatureField {
  const root = element('section', 'wu-creature-field');
  const glass = element('div', 'wu-glass-thin wu-creature-glass');
  const label = element('label', 'wu-creature-label', CREATURE_WORDS.fieldLabel);
  const input = element('textarea', 'wu-creature-words');
  input.id = `wu-creature-words-${Math.random().toString(36).slice(2, 8)}`;
  label.htmlFor = input.id;
  input.maxLength = maximum;
  input.rows = 1;
  const row = element('div', 'wu-creature-row');
  const counted = element('span', 'wu-creature-count');
  const keys = glyphRows([{ key: 'Enter', word: CREATURE_WORDS.make, shortcut: 'Enter', onPress: onMake }]);
  row.append(counted, keys);
  glass.append(label, input, row);
  const under = shade({ small: true });
  under.classList.add('wu-creature-line');
  root.append(glass, under);
  return {
    root,
    input,
    line(words, refused = false) { under.textContent = words; under.classList.toggle('wu-refused', refused); },
    count(characters, most) {
      counted.textContent = `${characters} of ${most}`;
      keys.classList.toggle('wu-creature-quiet', characters === 0);
    },
  };
}

export interface NotesAsk {
  readonly root: HTMLElement;
  readonly input: HTMLInputElement;
}

/**
 * The web notes box under the line (Create's frame 20): off until the person ticks it, each creature its own choice;
 * a click, or Tab and Space, ticks it, and Enter still makes. Its line says where the words go and the most it adds.
 */
export function notesAsk({ searchesAtMost, maximumUsd, onChange }: { readonly searchesAtMost: number; readonly maximumUsd: string; readonly onChange: (on: boolean) => void }): NotesAsk {
  const root = shade({ small: true });
  root.classList.add('wu-creature-notes-ask');
  const label = element('label', 'wu-creature-notes-label');
  const input = element('input', 'wu-creature-notes-box');
  input.type = 'checkbox';
  input.addEventListener('change', () => onChange(input.checked));
  label.append(input, element('span', '', CREATURE_WORDS.notesAsk));
  root.append(label, element('span', 'wu-creature-notes-line', notesAskLine(searchesAtMost, maximumUsd)));
  return { root, input };
}

/** The small label over the stand (r17t). */
export function standLabel(): HTMLDivElement {
  const made = shade({ small: true });
  made.classList.add('wu-creature-stand');
  made.textContent = CREATURE_WORDS.appearsHere;
  return made;
}

export interface MakingGroup {
  readonly root: HTMLElement;
  /** The one served step with its live dot and time, or, with no time, a refusal's sentence in the refused ink. */
  step(words: string, refused?: boolean, time?: string | null): void;
  /**
   * Ended with nothing made: the step becomes why, in the refused ink; "[↵] Try again" shows under it where making is
   * still offered (`onRetry`); the small print says what was spent before it stopped, or goes (DESIGN, 23 October).
   */
  ended(words: string, onRetry: (() => void) | null, spentUsd: string | null): void;
  /** Still being made when the page stops following it: the step says so, and the small print keeps only the price. */
  late(words: string): void;
  /** A step that has ended, above the current one, with its time: done, or not done (`missed`) and drawn faint. */
  passed(words: string, time: string, missed?: boolean): void;
  /** The notes from the web under the steps, as the request serves them, and what wrote them. */
  notes(notes: readonly { readonly aspect: string; readonly text: string }[], searches: number): void;
  /** Why the creature is made from the words alone, where the notes would stand. */
  alone(words: string): void;
}

/** The light rising from the stand while the creature is made (r19t; still, M13). The caller places it. */
export function standLight(): HTMLDivElement {
  const made = element('div', 'wu-creature-light');
  made.setAttribute('aria-hidden', 'true');
  return made;
}

/** Making (r19t): the title, the person's words, the step with its time and the small print. */
export function makingGroup({ words, priceUsdAtMost }: { readonly words: string; readonly priceUsdAtMost: string | null }): MakingGroup {
  const root = shade();
  root.classList.add('wu-creature-group');
  const step = element('p', 'wu-creature-step');
  const atMost = priceUsdAtMost === null ? null : `At most ${money(priceUsdAtMost)}.`;
  const small = element('p', 'wu-creature-small', [atMost, CREATURE_WORDS.leave].filter(Boolean).join(' '));
  groupBody(root).append(element('h2', 'wu-creature-title', CREATURE_WORDS.making), element('p', 'wu-creature-quote', quoted(words)), step, small);
  // The notes from the web, or why there are none, between the steps and the small print once the request ends.
  const fromWeb = element('div', 'wu-creature-notes');
  fromWeb.setAttribute('aria-live', 'polite');
  return {
    root,
    step(words, refused = false, time = null) {
      step.classList.toggle('wu-refused', refused);
      if (time === null) { step.textContent = words; return; }
      const dot = element('span', 'wu-creature-dot');
      dot.setAttribute('aria-hidden', 'true');
      step.replaceChildren(dot, element('span', '', words), element('span', 'wu-creature-time', time));
    },
    ended(words, onRetry, spentUsd) {
      step.classList.add('wu-refused');
      step.textContent = words;
      const spent = spentUsd !== null && Number(spentUsd) > 0 ? element('p', 'wu-creature-small', `Spent ${money(spentUsd)} before it stopped.`) : null;
      small.replaceWith(...(onRetry === null ? [] : [glyphRows([{ key: 'Enter', word: CREATURE_WORDS.tryAgain, shortcut: 'Enter', onPress: onRetry }])]), ...(spent === null ? [] : [spent]));
    },
    late(words) {
      step.classList.remove('wu-refused');
      step.textContent = words;
      if (atMost === null) small.remove(); else small.textContent = atMost;
    },
    passed(words, time, missed = false) {
      const done = element('p', missed ? 'wu-creature-step wu-creature-passed wu-creature-missed' : 'wu-creature-step wu-creature-passed');
      const mark = element('span', 'wu-creature-tick');
      mark.setAttribute('aria-hidden', 'true');
      done.append(mark, element('span', '', words), element('span', 'wu-creature-time', time));
      step.before(done);
    },
    notes(notes, searches) {
      const list = element('ul', 'wu-creature-notes-list');
      for (const note of notes.slice(0, NOTES_SHOWN)) {
        const item = element('li');
        const aspect = ASPECT_LABELS.get(note.aspect);
        if (aspect) item.append(element('span', 'wu-creature-notes-aspect', `${aspect} · `));
        item.append(element('span', '', note.text));
        list.append(item);
      }
      const more = notes.length - NOTES_SHOWN;
      if (more > 0) list.append(element('li', 'wu-creature-notes-aspect', `And ${more} more ${more === 1 ? 'note' : 'notes'}.`));
      fromWeb.replaceChildren(element('p', 'wu-creature-notes-over', CREATURE_WORDS.fromWeb), list, element('p', 'wu-creature-notes-line', notesWrote(searches)));
      if (!fromWeb.isConnected) small.before(fromWeb);
    },
    alone(words) {
      fromWeb.replaceChildren(element('p', 'wu-creature-notes-line', words));
      if (!fromWeb.isConnected) small.before(fromWeb);
    },
  };
}

/**
 * Made (r19b): the name, how it was made, the quote, [Enter] Place and the small print. Place is said, not pressed
 * here: the creature is held at the stand by build mode, whose own Enter places it. With no stand the creature waits
 * in Creatures: the card says so and how to place it, and [Esc] Back opens Creatures with it in focus, as Esc does.
 */
export function madeGroup({ label, words, modelName, spentUsd, sketch, placeable, notes = 0, onBack }: {
  readonly label: string | null;
  readonly words: string;
  readonly modelName: string | null;
  readonly spentUsd: string | null;
  /** True while the creature wears its sketch, its made look not ready yet (M15). */
  readonly sketch: boolean;
  readonly placeable: boolean;
  /** How many web notes its drafter was handed; 0 or absent where it had none. */
  readonly notes?: number;
  /** Back where it is not placeable, as Esc does: to the tray's Creatures with the creature in focus. */
  readonly onBack?: () => void;
}): HTMLElement {
  const root = shade();
  root.classList.add('wu-creature-group', 'wu-creature-made');
  const name = label === null ? CREATURE_WORDS.untitled : label.charAt(0).toUpperCase() + label.slice(1);
  const lines = [madeSmallPrint(modelName, spentUsd)];
  if (sketch && label !== null) lines.push(`${name} wears a sketch until the made look is ready.`);
  groupBody(root).append(
    element('h2', 'wu-creature-title', name),
    element('p', 'wu-creature-from', madeFromLine(notes)),
    element('p', 'wu-creature-quote', quoted(words)),
    ...(placeable
      ? [glyphRows([{ key: 'Enter', word: CREATURE_WORDS.place, shortcut: 'Enter' }])]
      : [element('p', 'wu-creature-from', CREATURE_WORDS.nowhereToStand), glyphRows([{ key: 'Esc', word: CREATURE_WORDS.back, shortcut: 'Escape', ...(onBack ? { onPress: onBack } : {}) }])]),
    ...lines.map((line) => element('p', 'wu-creature-small', line)),
  );
  return root;
}

/**
 * The made card's Place row as build mode's placing stands (DESIGN, 23 October): "[↵] Place"; once Enter lets the
 * creature go, "Placing…" with its key dimmed until the server answers; a refused place says why in build mode's own
 * words, in the refused ink, under "Place" dimmed as build mode's own refused placing offers no Place (Esc puts it back,
 * and it waits in Creatures).
 */
export function placeRow(card: HTMLElement, state: { readonly placing: boolean; readonly refused: string | null }): void {
  const rows = card.querySelector('.wu-rows');
  if (rows === null) return;
  const row = glyphRows([{ key: 'Enter', word: state.placing ? CREATURE_WORDS.placingNow : CREATURE_WORDS.place, shortcut: 'Enter', disabled: state.placing || state.refused !== null }]);
  rows.replaceWith(row);
  card.querySelector('.wu-creature-unplaced')?.remove();
  if (state.refused !== null && !state.placing) row.after(element('p', 'wu-creature-small wu-refused wu-creature-unplaced', state.refused));
}

export interface Leader {
  readonly root: SVGSVGElement;
  /** A thin line from the creature's head to the card, both points in the screen's pixels. */
  draw(from: { readonly x: number; readonly y: number }, to: { readonly x: number; readonly y: number }): void;
  hide(): void;
}

/** The made card's leader from the creature's head (r19b: "on one shade with a leader from its head"). */
export function leader(): Leader {
  const root = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  root.setAttribute('class', 'wu-creature-leader');
  root.setAttribute('aria-hidden', 'true');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  root.append(line);
  return {
    root,
    draw(from, to) {
      root.style.display = '';
      line.setAttribute('x1', String(from.x)); line.setAttribute('y1', String(from.y));
      line.setAttribute('x2', String(to.x)); line.setAttribute('y2', String(to.y));
    },
    hide() { root.style.display = 'none'; },
  };
}
