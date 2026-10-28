// Making a creature where it will stand (DESIGN's R-CREATURE-BUILD-SHEET.md, pictures r-creature17t, 19t and
// 19b; the money words of WORDS.md's unit 9 entry of 22 October; web notes in Create's words of 25 October, with
// "creature" for "place", WORDS.md 12:34): its title over Create's composer low in the middle (ROOT's sweep of 27
// October), the label over the stand, and the making view and the made card beside it in Create's making view's
// design, from its own parts (world-ui-create.ts): plain type, the title, the words in quotes, one row per step with
// its time, what was spent, and the web notes in a column beside the rows. They only draw; what a key does is
// world-creature.ts's. Their look lives in world-ui-creature.css, and Create's parts' in create-world.css.
import { glyphRows, shade, type Step } from './world-ui.ts';
import { scrollingColumn } from './world-page-frame.ts';
import { composer, fitQuote, makingSteps, webNotes, type Composer } from './world-ui-create.ts';
import { spentUpTo, webNotesLabel } from './create-words.mjs';
import './world-ui-creature.css';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

/** Every word these screens show, as DESIGN worded them; a step and the notes say Create's (create-words.mjs). */
export const CREATURE_WORDS = Object.freeze({
  title: 'Make a creature',
  /** The composer's placeholder, and the field's name. */
  fieldLabel: 'What does the creature look like?',
  appearsHere: 'The creature appears here',
  make: 'Make',
  place: 'Place',
  tryAgain: 'Try again',
  back: 'Back',
  making: 'Making your creature',
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
  notesFailed: 'The web notes could not be made, so it is made from your words alone.',
  notesNone: 'The searches found nothing to use, so it is made from your words alone.',
});

/** The made card's line: "Made from your words", and where its drafter was handed notes, "... and 7 notes from the web". */
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
 * The made group's small print, the one place the model is named: "Made by <model> · spent $x", the whole spend where
 * served (M2); empty where neither is.
 */
export function madeSmallPrint(modelName: string | null, spentUsd: string | null): string {
  return [modelName === null ? null : `Made by ${modelName}`, spentUsd === null ? null : `spent ${money(spentUsd)}`]
    .filter((part): part is string => part !== null).join(' · ');
}

const quoted = (words: string): string => `“${words}”`;

/**
 * A group's words in a part of their own (world-page-frame.ts): where a short window leaves less room than they take,
 * that part scrolls with the shared frame's fades and track.
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

let serial = 0;

/** The making view or the made card: a section named by its title, its words in a part of their own. */
function group(kind: string, title: HTMLElement): { readonly root: HTMLElement; readonly body: HTMLElement } {
  const root = element('section', `wu-creature-group ${kind}`);
  title.id = `wu-creature-title-${++serial}`;
  root.setAttribute('aria-labelledby', title.id);
  return { root, body: groupBody(root) };
}

/** The words quoted as Create's making view quotes them, sized to show whole once on the page. */
function quote(words: string): HTMLParagraphElement {
  const made = element('p', 'wu-making-quote wu-creature-quote', quoted(words));
  queueMicrotask(() => { if (made.isConnected) fitQuote(made); });
  return made;
}

export interface CreatureField {
  readonly root: HTMLElement;
  /** Create's composer: the words, the web search toggle where offered, the price or why it cannot make, and Make. */
  readonly composer: Composer;
}

/** The describe field: "Make a creature" over Create's composer, with the creature's own placeholder and Make. */
export function creatureField({ maximum, onInput, onMake }: { readonly maximum: number; readonly onInput: (words: string) => void; readonly onMake: () => void }): CreatureField {
  const root = element('section', 'wu-creature-field');
  const title = element('h2', 'wu-creature-heading', CREATURE_WORDS.title);
  title.id = `wu-creature-heading-${Math.random().toString(36).slice(2, 8)}`;
  root.setAttribute('aria-labelledby', title.id);
  const made = composer({ onInput, onCreate: onMake, wording: { placeholder: CREATURE_WORDS.fieldLabel, label: CREATURE_WORDS.fieldLabel, pill: CREATURE_WORDS.make } });
  made.field.maxLength = maximum;
  root.append(title, made.root);
  return { root, composer: made };
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
  /** The steps as Create's making view draws them: a row each with its time ("17 s"), the one under way with its dot. */
  steps(steps: readonly Step[]): void;
  /**
   * What the making has spent so far of the most it may, under the steps, as Create's making view says it once a read
   * states it: "Spent $0.0042 of up to $0.38", with what calls under way hold as not known yet.
   */
  spent(spent: { readonly spentUsd: number; readonly unknownUsd: number }, mostUsd: string): void;
  /**
   * Ended with nothing made: why, in the refused ink, under the steps; "[↵] Try again" under it where making is still
   * offered (`onRetry`); then what was spent before it stopped, or no spend at all (DESIGN, 23 October).
   */
  ended(words: string, onRetry: (() => void) | null, spentUsd: string | null): void;
  /** Still being made when the page stops following it: says so under the steps, and the spend last read stays. */
  late(words: string): void;
  /** The notes from the web beside the steps, under the searches the request sent, each under its aspect's label. */
  notes(notes: readonly { readonly aspect: string; readonly text: string }[], searches: number): void;
  /** Why the creature is made from the words alone, where the notes would stand. */
  alone(words: string, searches?: number): void;
}

/** The light rising from the stand while the creature is made (r19t; still, M13). The caller places it. */
export function standLight(): HTMLDivElement {
  const made = element('div', 'wu-creature-light');
  made.setAttribute('aria-hidden', 'true');
  return made;
}

/**
 * Making (Create's making view): the title, the person's words, the steps with their times and, once a read states it,
 * the spend; the web notes in the column beside them once the request ends, or why there are none.
 */
export function makingGroup({ words }: { readonly words: string }): MakingGroup {
  const title = element('h2', 'wu-create-title wu-creature-title', CREATURE_WORDS.making);
  const { root, body } = group('wu-creature-making', title);
  const rows = makingSteps();
  // Under the steps: why it ended or that it takes longer, then what was spent.
  const why = element('p', 'wu-creature-why');
  why.setAttribute('role', 'status');
  why.hidden = true;
  const small = element('p', 'wu-making-spent wu-creature-small');
  small.setAttribute('role', 'status');
  small.hidden = true;
  const steps = element('div', 'wu-creature-steps');
  steps.append(rows.root, why, small);
  const web = webNotes();
  const columns = element('div', 'wu-making');
  columns.append(steps, web.root);
  body.append(title, quote(words), columns);
  return {
    root,
    steps(next) { rows.set(next); },
    spent(spent, mostUsd) {
      small.textContent = spentUpTo(spent, mostUsd);
      small.hidden = false;
    },
    ended(words, onRetry, spentUsd) {
      why.classList.add('wu-refused');
      why.textContent = words;
      why.hidden = false;
      const spent = spentUsd !== null && Number(spentUsd) > 0 ? element('p', 'wu-making-spent wu-creature-small', `Spent ${money(spentUsd)} before it stopped.`) : null;
      small.replaceWith(...(onRetry === null ? [] : [glyphRows([{ key: 'Enter', word: CREATURE_WORDS.tryAgain, shortcut: 'Enter', onPress: onRetry }])]), ...(spent === null ? [] : [spent]));
    },
    late(words) {
      why.classList.remove('wu-refused');
      why.textContent = words;
      why.hidden = false;
    },
    notes(notes, searches) { web.notes(webNotesLabel(searches), notes); },
    alone(words, searches = 0) { web.instead(webNotesLabel(searches), words); },
  };
}

/**
 * Made (r19b) in the making view's type, and only this (ROOT's sweep of 27 October): "Made from your words" over the
 * name, as a made world's banner says it over its name, then the words, [Enter] Place and "Made by <model> · spent $x".
 * Place is said, not pressed here: the creature is held at the stand by build mode, whose own Enter places it. With no
 * stand the creature waits in Creatures: the card says so and how to place it, and [Esc] Back opens Creatures with it
 * in focus, as Esc does.
 */
export function madeGroup({ label, words, modelName, spentUsd, placeable, notes = 0, onBack }: {
  readonly label: string | null;
  readonly words: string;
  readonly modelName: string | null;
  readonly spentUsd: string | null;
  readonly placeable: boolean;
  /** How many web notes its drafter was handed; 0 or absent where it had none. */
  readonly notes?: number;
  /** Back where it is not placeable, as Esc does: to the tray's Creatures with the creature in focus. */
  readonly onBack?: () => void;
}): HTMLElement {
  const name = label === null ? CREATURE_WORDS.untitled : label.charAt(0).toUpperCase() + label.slice(1);
  const title = element('h2', 'wu-create-title wu-creature-title', name);
  const { root, body } = group('wu-creature-made', title);
  const small = madeSmallPrint(modelName, spentUsd);
  body.append(
    element('p', 'wu-creature-from', madeFromLine(notes)),
    title,
    quote(words),
    ...(placeable
      ? [glyphRows([{ key: 'Enter', word: CREATURE_WORDS.place, shortcut: 'Enter' }])]
      : [element('p', 'wu-creature-nowhere', CREATURE_WORDS.nowhereToStand), glyphRows([{ key: 'Esc', word: CREATURE_WORDS.back, shortcut: 'Escape', ...(onBack ? { onPress: onBack } : {}) }])]),
    ...(small === '' ? [] : [element('p', 'wu-making-spent wu-creature-small', small)]),
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
  if (state.refused !== null && !state.placing) row.after(element('p', 'wu-creature-why wu-refused wu-creature-unplaced', state.refused));
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
