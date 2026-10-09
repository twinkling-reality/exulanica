/**
 * Play this one: the band a person sees while they play one being of a society of things
 * (deliveries/UI/play-this-one/design.md). One dark band under the world's bar says whom they play,
 * the world's minute and when the next is due, what they chose for it, and Give it back (G).
 *
 * The world is the menu: clicking someone or something in the world acts on it (the controller,
 * `../composition/play-this-one.ts`, matches the click to the turn's options), and clicking open
 * ground walks there where the minute offers it. One quiet line says what a click under the pointer
 * would do. Options that act on
 * nothing a person can click (wait, carry on, say something to everyone near, leave) are small
 * buttons in the band. Where a click offers more than one thing, or a line to say, a small panel in
 * the band lists them by the server's own words. Nothing pretends to happen at once: a choice is
 * "At the next minute", and a later one before the minute replaces it.
 */

import type { PlayOption } from '../society-play-api.js';
import { el } from './dom.js';
import './play-this-one.css';

export const PLAY_WORDS = Object.freeze({
  playing: 'You are playing {name}',
  minute: 'Minute {minute}',
  nextIn: 'next in {seconds} s',
  paused: 'paused: play the world or move it on a minute',
  chosen: 'At the next minute: {label}',
  nothingChosen: 'Click someone or something in the world to act on it.',
  nothingChosenWalk: 'Click someone or something in the world to act on it, or open ground to walk there.',
  giveBack: 'Give it back',
  sayTo: 'Say to {name}',
  sayAll: 'Say to everyone near',
  say: 'Say',
  characters: '{count} of {maximum}',
  cancel: 'Cancel',
  givenBack: 'You gave {name} back. Its own mind decides again from the next minute.',
  stopped: 'You are no longer playing {name}: its own mind decides again.',
  starting: 'Starting to play {name}…',
});

const fill = (words: string, values: Readonly<Record<string, string | number>>): string =>
  words.replace(/\{(\w+)\}/gu, (all, key: string) => (key in values ? String(values[key]) : all));

/** What the band shows; null hides it. */
export interface PlayBandView {
  readonly name: string;
  readonly minute: number | null;
  /** Seconds to the next minute, or null while the world is paused. */
  readonly nextInSeconds: number | null;
  readonly chosen: string | null;
  /** A sentence about the last thing that happened (a refusal, a choice taken), or null. */
  readonly status: string | null;
  /** Whether the minute offers a walk to a spot the person clicks on the ground. */
  readonly walkOffered?: boolean;
  /** Options that act on nothing a person can click in the world. */
  readonly loose: readonly PlayOption[];
  /** What a click on someone or something offers, when it offers more than one thing or a line. */
  readonly asking: { readonly name: string; readonly options: readonly PlayOption[] } | null;
  readonly lineCharactersMaximum: number;
  /**
   * Whether a field being typed in is kept (the countdown's redraws); false after a choice or a new
   * minute, which close it and give the keys back to the world.
   */
  readonly keepFields?: boolean;
}

export interface PlayBand {
  readonly root: HTMLElement;
  show(view: PlayBandView): void;
  /** Say what a click under the pointer would do, or nothing with null; touches nothing else. */
  hint(words: string | null): void;
  /** Say one last sentence in place of the band's controls (given back, stopped). */
  say(words: string): void;
  hide(): void;
}

export function buildPlayBand(handlers: {
  readonly onGiveBack: () => void;
  readonly onChoose: (option: PlayOption, line: string | null) => void;
  readonly onCloseAsking: () => void;
}): PlayBand {
  const title = el('p', { class: 'play-band-title' });
  const when = el('p', { class: 'play-band-when' });
  const chosen = el('p', { class: 'play-band-chosen', role: 'status', 'aria-live': 'polite' });
  const status = el('p', { class: 'play-band-status', role: 'status', 'aria-live': 'polite' });
  // Follows the pointer, so it is no live region: the same words are on what the click acts on.
  const hint = el('p', { class: 'play-band-hint' });
  const loose = el('div', { class: 'play-band-loose', role: 'group' });
  const asking = el('div', { class: 'play-band-asking', hidden: true });
  const giveBack = el('button', { type: 'button', class: 'play-band-give-back', 'data-action': 'play.give-back', 'aria-keyshortcuts': 'G' }, [
    el('span', { text: PLAY_WORDS.giveBack }), el('kbd', { text: 'G' }),
  ]);
  giveBack.addEventListener('click', () => handlers.onGiveBack());
  const root = el('section', { class: 'play-band', role: 'region', 'aria-label': 'Play this one', 'data-ui-stage': 'dark', hidden: true }, [
    el('div', { class: 'play-band-head' }, [title, when, giveBack]),
    chosen,
    hint,
    status,
    loose,
    asking,
  ]);

  /** A field for a line: Enter says it, Escape leaves it; a count against the server's bound. */
  const lineField = (option: PlayOption, placeholder: string, maximum: number): HTMLElement => {
    const input = el('input', { type: 'text', class: 'play-band-line', maxlength: String(maximum), placeholder, 'aria-label': placeholder });
    const left = el('span', { class: 'play-band-count', text: fill(PLAY_WORDS.characters, { count: 0, maximum }) });
    const send = el('button', { type: 'button', class: 'play-band-say', text: PLAY_WORDS.say, disabled: true });
    const reflect = (): void => {
      const length = [...input.value].length;
      left.textContent = fill(PLAY_WORDS.characters, { count: length, maximum });
      send.disabled = input.value.trim() === '' || length > maximum;
    };
    const say = (): void => { if (!send.disabled) handlers.onChoose(option, input.value.trim()); };
    input.addEventListener('input', reflect);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); say(); }
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); handlers.onCloseAsking(); }
    });
    send.addEventListener('click', say);
    queueMicrotask(() => input.focus({ preventScroll: true }));
    return el('div', { class: 'play-band-field' }, [input, left, send]);
  };

  const optionButton = (option: PlayOption, view: PlayBandView, into: HTMLElement): HTMLButtonElement => {
    const button = el('button', { type: 'button', class: 'play-band-option', text: option.label, 'data-kind': option.kind });
    button.addEventListener('click', () => {
      if (!option.takesLine) { handlers.onChoose(option, null); return; }
      const placeholder = option.kind === 'say_all' ? PLAY_WORDS.sayAll
        : fill(PLAY_WORDS.sayTo, { name: view.asking?.name ?? '' });
      into.replaceChildren(lineField(option, placeholder, view.lineCharactersMaximum));
    });
    return button;
  };

  return {
    root,
    show(view) {
      root.hidden = false;
      giveBack.hidden = false;
      title.textContent = fill(PLAY_WORDS.playing, { name: view.name });
      when.textContent = [
        view.minute === null ? null : fill(PLAY_WORDS.minute, { minute: view.minute }),
        view.nextInSeconds === null ? PLAY_WORDS.paused : fill(PLAY_WORDS.nextIn, { seconds: view.nextInSeconds }),
      ].filter((part) => part !== null).join(' · ');
      chosen.textContent = view.chosen !== null ? fill(PLAY_WORDS.chosen, { label: view.chosen })
        : view.walkOffered === true ? PLAY_WORDS.nothingChosenWalk : PLAY_WORDS.nothingChosen;
      status.textContent = view.status ?? '';
      // A field being typed in is kept across the countdown's redraws; a choice closes it.
      const active = document.activeElement;
      const inField = active !== null && (loose.contains(active) || asking.contains(active));
      if (inField && view.keepFields !== false) return;
      if (inField) (active as HTMLElement).blur();
      const looseField = el('div', { class: 'play-band-field-slot' });
      loose.replaceChildren(...view.loose.map((option) => optionButton(option, view, looseField)), looseField);
      asking.hidden = view.asking === null;
      if (view.asking !== null) {
        const field = el('div', { class: 'play-band-field-slot' });
        const close = el('button', { type: 'button', class: 'play-band-close', text: PLAY_WORDS.cancel });
        close.addEventListener('click', () => handlers.onCloseAsking());
        asking.replaceChildren(
          el('p', { class: 'play-band-asking-name', text: view.asking.name }),
          ...view.asking.options.map((option) => optionButton(option, view, field)),
          field,
          close,
        );
        // One option that takes a line opens its field at once.
        if (view.asking.options.length === 1 && view.asking.options[0]!.takesLine) {
          field.replaceChildren(lineField(view.asking.options[0]!, fill(PLAY_WORDS.sayTo, { name: view.asking.name }), view.lineCharactersMaximum));
        }
      } else {
        asking.replaceChildren();
      }
    },
    hint(words) {
      if (hint.textContent !== (words ?? '')) hint.textContent = words ?? '';
    },
    say(words) {
      root.hidden = false;
      hint.textContent = '';
      giveBack.hidden = true;
      when.textContent = '';
      chosen.textContent = '';
      title.textContent = words;
      status.textContent = '';
      loose.replaceChildren();
      asking.replaceChildren();
      asking.hidden = true;
    },
    hide() {
      root.hidden = true;
    },
  };
}
