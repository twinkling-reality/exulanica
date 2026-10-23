// Making a creature where it will stand (DESIGN's R-CREATURE-BUILD-SHEET.md, pictures r-creature17t, 19t and
// 19b; the money words of WORDS.md's unit 9 entry of 22 October): the field low in the middle, the line under
// it, the label over the stand, the making group and the made group beside it. They only draw; what a key does
// is world-creature.ts's. Their look lives in world-ui-creature.css, from world-ui.css's tokens.
import { glyphRows, shade } from './world-ui.ts';
import './world-ui-creature.css';

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
  placingNow: 'Placing…',
  maker: 'An AI model makes the creature from your words',
  leave: 'You can leave this page: the making carries on, and the creature waits in Creatures.',
  kept: 'kept in Creatures',
});

/** Dollars as the workspace writes them (P1): "$0.37", under a cent "$0.0042", "less than $0.0001". */
export function money(usd: string): string {
  const value = Number(usd);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value === 0) return '$0';
  if (value < 0.00005) return 'less than $0.0001';
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

/** The line under the field: what makes it, the most it may cost and how long it takes, where served (M1). */
export function makerLine(priceUsdAtMost: string | null, typicalSeconds: number | null): string {
  if (priceUsdAtMost === null || typicalSeconds === null) return `${CREATURE_WORDS.maker}.`;
  return `${CREATURE_WORDS.maker}: at most ${money(priceUsdAtMost)}, about ${typicalSeconds} seconds.`;
}

/** The made group's small print: the model, the whole spend where served (M2), and where it is kept. */
export function madeSmallPrint(modelName: string | null, spentUsd: string | null): string {
  return [modelName === null ? null : `Made by ${modelName}`, spentUsd === null ? null : `spent ${money(spentUsd)}`, CREATURE_WORDS.kept]
    .filter((part): part is string => part !== null).join(' · ');
}

const quoted = (words: string): string => `“${words}”`;

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
  root.append(element('h2', 'wu-creature-title', CREATURE_WORDS.making), element('p', 'wu-creature-quote', quoted(words)), step, small);
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
  };
}

/**
 * Made (r19b): the name, how it was made, the quote, [Enter] Place and the small print. Place is said, not pressed
 * here: the creature is held at the stand by build mode, whose own Enter places it. With no stand it is left out, and
 * the creature waits in Creatures.
 */
export function madeGroup({ label, words, modelName, spentUsd, sketch, placeable }: {
  readonly label: string | null;
  readonly words: string;
  readonly modelName: string | null;
  readonly spentUsd: string | null;
  /** True while the creature wears its sketch, its made look not ready yet (M15). */
  readonly sketch: boolean;
  readonly placeable: boolean;
}): HTMLElement {
  const root = shade();
  root.classList.add('wu-creature-group', 'wu-creature-made');
  const name = label === null ? CREATURE_WORDS.untitled : label.charAt(0).toUpperCase() + label.slice(1);
  const lines = [madeSmallPrint(modelName, spentUsd)];
  if (sketch && label !== null) lines.push(`${name} wears a sketch until the made look is ready.`);
  root.append(
    element('h2', 'wu-creature-title', name),
    element('p', 'wu-creature-from', CREATURE_WORDS.madeFrom),
    element('p', 'wu-creature-quote', quoted(words)),
    ...(placeable ? [glyphRows([{ key: 'Enter', word: CREATURE_WORDS.place, shortcut: 'Enter' }])] : []),
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
