/**
 * Make a creature: the sheet where a person describes a creature in their own words and the world
 * makes it, in the Look sheet's language on the dark stage.
 *
 * Before anyone types, it says whether creatures are made here and, when not, why in plain words,
 * and how long one usually takes. One line takes the words (at most `CREATURE_WORDS_CHARACTERS`),
 * and Make sends them; the sheet then says what is happening (imagining it, placing it) until the
 * creature stands in the world, or says why not: a refusal's own fixed sentence with the words kept
 * so they can be changed, or a failure in one sentence. Keys: Enter makes, Escape goes back.
 *
 * It builds elements and holds no client: the caller reads the offer, sends the words and places
 * what was made, and tells the sheet each state.
 */

import { CREATURE_WORDS_CHARACTERS } from '../creature-drafts-api.js';
import { el, setText } from './dom.js';
import './creature-sheet.css';

/** What the sheet says before anyone types. */
export interface CreatureSheetOffer {
  /** Null when creatures are made here; else why not, in one plain sentence. */
  readonly unavailable: string | null;
  /** How long one usually takes, in words, or null where the server did not say. */
  readonly timing: string | null;
}

export interface CreatureSheet {
  readonly root: HTMLElement;
  show(offer: CreatureSheetOffer): void;
  /** The words were sent: the world is imagining the creature. */
  imagining(): void;
  /** It was made: the world is placing it. */
  placing(label: string | null): void;
  /** It stands in the world. */
  made(label: string | null): void;
  /** It was not made: the sentence to show, the words kept for another try. */
  notMade(sentence: string): void;
  focus(): void;
}

export interface CreatureSheetHandlers {
  readonly onMake: (words: string) => void;
  readonly onClose: () => void;
}

export function buildCreatureSheet(handlers: CreatureSheetHandlers): CreatureSheet {
  const input = el('input', {
    class: 'creature-sheet-words', type: 'text', maxLength: String(CREATURE_WORDS_CHARACTERS),
    placeholder: 'What it looks like and how it moves', 'aria-label': 'Describe a creature',
  }) as HTMLInputElement;
  const make = el('button', { class: 'creature-sheet-make', type: 'button', text: 'Make' }) as HTMLButtonElement;
  const back = el('button', { class: 'creature-sheet-back', type: 'button', text: 'Back to the world' }) as HTMLButtonElement;
  const unavailable = el('p', { class: 'creature-sheet-unavailable', role: 'status' });
  const timing = el('p', { class: 'creature-sheet-timing' });
  const status = el('p', { class: 'creature-sheet-status', role: 'status', 'aria-live': 'polite' });
  const root = el('section', { class: 'creature-sheet', 'aria-label': 'Make a creature', hidden: '' }, [
    el('p', { class: 'creature-sheet-eyebrow', text: 'MAKE A CREATURE' }),
    el('h2', { class: 'creature-sheet-title', text: 'Describe a creature' }),
    el('p', { class: 'creature-sheet-lede', text: 'In your own words. The world drafts its body and it comes to stand in front of you.' }),
    unavailable,
    el('div', { class: 'creature-sheet-row' }, [input, make]),
    timing,
    status,
    back,
  ]);
  let offered = false;
  let busy = false;
  const ready = (): void => {
    make.disabled = !offered || busy || input.value.trim().length === 0;
    input.disabled = !offered || busy;
  };
  const send = (): void => {
    if (make.disabled) return;
    handlers.onMake(input.value.trim());
  };
  input.addEventListener('input', ready);
  make.addEventListener('click', send);
  back.addEventListener('click', () => handlers.onClose());
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); handlers.onClose(); }
    if (event.key === 'Enter' && event.target === input) { event.preventDefault(); send(); }
  });
  return {
    root,
    show(offer) {
      offered = offer.unavailable === null;
      busy = false;
      setText(unavailable, offer.unavailable ?? '');
      unavailable.hidden = offer.unavailable === null;
      setText(timing, offer.timing ?? '');
      setText(status, '');
      root.hidden = false;
      ready();
    },
    imagining() {
      busy = true;
      setText(status, 'Imagining your creature…');
      ready();
    },
    placing(label) {
      busy = true;
      setText(status, label === null ? 'Placing it in front of you…' : `Placing the ${label} in front of you…`);
      ready();
    },
    made(label) {
      busy = false;
      input.value = '';
      setText(status, label === null ? 'It stands in front of you.' : `The ${label} stands in front of you.`);
      ready();
    },
    notMade(sentence) {
      busy = false;
      setText(status, sentence);
      ready();
    },
    focus() {
      input.focus({ preventScroll: true });
    },
  };
}
