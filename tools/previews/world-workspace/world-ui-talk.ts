// Talking's own parts in the world (DESIGN's rulings N28, T1 to T9): the line over whoever said it, with
// who said it and to whom, and a name over someone farther off, each on the shared soft shade
// (world-ui.ts shade()), and the scene while following a conversation (T9). talk-pops.mjs and
// talk-scene.mjs decide what shows and where; contextual-world.ts places them. Their look lives in
// world-ui-talk.css.
import './world-ui-talk.css';
import { glyphRows, shade } from './world-ui.ts';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text) made.textContent = text;
  return made;
}

/** What one line over a speaker draws (talk-pops.mjs decides it). */
export interface SpeechShown {
  /** Who said it and to whom: "Ines, to Teo", or "Ines" (talk-words.mjs speechLabel). */
  readonly label: string;
  /** A line in quotes, said (italic), or an action chosen (upright). */
  readonly words: string;
  readonly said: boolean;
  /** A line kept up by its reply: dimmed (T4). */
  readonly earlier: boolean;
  /** Its hold has run, so it fades. */
  readonly leaving: boolean;
}

/** A part placed by its top left, by transform alone, and put out of sight when its subject is. */
export interface Placed {
  readonly root: HTMLElement;
  /** Its size on screen, for placing and stacking. */
  size(): { readonly width: number; readonly height: number };
  place(x: number, y: number): void;
  away(): void;
  remove(): void;
}

export interface Speech extends Placed {
  /** Draws what was said or chosen; new words come in again. */
  draw(shown: SpeechShown): void;
}

export interface NameOver extends Placed {
  draw(name: string): void;
}

function placed(root: HTMLElement): Placed {
  return {
    root,
    size() { return { width: root.offsetWidth, height: root.offsetHeight }; },
    place(x, y) {
      const transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0)`;
      if (root.style.transform !== transform) root.style.transform = transform;
    },
    away() {
      const transform = 'translate3d(-9999px,0,0)';
      if (root.style.transform !== transform) root.style.transform = transform;
    },
    remove() { root.remove(); },
  };
}

const put = (target: Element, value: string | null, name: string): void => {
  if (value === null) target.removeAttribute(name); else if (target.getAttribute(name) !== value) target.setAttribute(name, value);
};

/** A line over the character who said it or whose mind chose an action (N28 section 4, T1 to T4, T8). */
export function speech(): Speech {
  const root = shade();
  root.classList.add('wu-anchored', 'wu-speech');
  const who = element('div', 'wu-speech-who');
  const line = element('div', 'wu-speech-line');
  root.append(who, line);
  let drawn = '';
  return {
    ...placed(root),
    draw({ label, words, said, earlier, leaving }) {
      if (words !== drawn) {
        drawn = words;
        line.textContent = words;
        root.getAnimations().forEach(animation => animation.cancel());
        root.classList.remove('wu-speech-in'); void root.offsetWidth; root.classList.add('wu-speech-in');
      }
      if (who.textContent !== label) who.textContent = label;
      put(line, said ? 'true' : null, 'data-said');
      put(root, earlier ? 'true' : null, 'data-earlier');
      put(root, leaving ? 'true' : null, 'data-leaving');
    },
  };
}

/** A name over someone farther off: in a conversation out of hearing (N28 section 5). */
export function nameOver(): NameOver {
  const root = shade({ small: true });
  root.classList.add('wu-anchored', 'wu-name-over');
  return {
    ...placed(root),
    draw(name) { if (root.textContent !== name) root.textContent = name; },
  };
}

/**
 * The edge inset every screen keeps (world-ui.css --edge-inset), in CSS pixels, read from the layout
 * rather than retyped: a probe in `layer` takes the token as its width.
 */
export function edgeInset(layer: HTMLElement): () => number {
  const probe = element('div', 'wu-edge-probe');
  probe.setAttribute('aria-hidden', 'true');
  layer.append(probe);
  return () => probe.offsetWidth;
}

/** The line before the line now in the talking scene (T9): who said it and the line, quoted. */
export interface SceneLine {
  readonly speaker: string;
  readonly words: string;
}

/** What the talking scene draws (T9, frame r24); contextual-world.ts words it with talk-words.mjs. */
export interface SceneShown {
  readonly before: SceneLine | null;
  /** The line said now, in quotes. */
  readonly now: string;
  /** The speaker's plate: their portrait (or the letter until it is made), name and whom they spoke to, and who chose
   * the line said now (T14: "By Nemotron 3 Super 120B"), null for a line no mind chose. */
  readonly plate: { readonly name: string; readonly to: string; readonly letter: string; readonly portrait: string | null; readonly by: string | null };
  /** The speaker's page's word: "Ines's day". */
  readonly day: string;
  readonly stopFollowing: string;
  /** Over the speaker's head on screen, or null when they are not seen. */
  readonly dot: { readonly x: number; readonly y: number } | null;
  /** What they did, top right: the conversation's moment title, then the going on from it; none until it is read. */
  readonly told: readonly string[];
}

export interface TalkScene {
  readonly root: HTMLElement;
  /** Whether the scene is drawn: its bars slide in, or out. */
  open(open: boolean): void;
  draw(shown: SceneShown): void;
  remove(): void;
}

/**
 * Talking while following a conversation (T9, frame r24): thin bars above and below, the line said
 * now low at the left over the line before it and the speaker's plate, a dot over whoever speaks,
 * and two choices on thin bars at the right. `onStop` stops following; `onDay` opens the speaker's page.
 */
export function talkScene({ onStop, onDay }: { readonly onStop: () => void; readonly onDay: () => void }): TalkScene {
  const root = element('div', 'wu-scene');
  root.setAttribute('aria-live', 'polite');
  const fade = element('div', 'wu-scene-fade'), top = element('div', 'wu-scene-bar wu-scene-top'), bottom = element('div', 'wu-scene-bar wu-scene-bottom');
  const dot = element('div', 'wu-scene-dot');
  dot.setAttribute('aria-hidden', 'true');
  const lines = element('div', 'wu-scene-lines');
  const before = element('div', 'wu-scene-before'), beforeName = element('b'), beforeWords = element('span');
  before.append(beforeName, beforeWords);
  const now = element('div', 'wu-scene-now');
  const plate = element('div', 'wu-scene-plate');
  const orb = element('span', 'wu-scene-orb'), name = element('span', 'wu-scene-name'), to = element('span', 'wu-scene-to');
  orb.setAttribute('aria-hidden', 'true');
  plate.append(orb, name, to);
  const by = element('div', 'wu-scene-by');
  lines.append(before, now, plate, by);
  const choices = element('div', 'wu-scene-choices');
  const told = shade();
  told.classList.add('wu-scene-told');
  root.append(fade, top, bottom, dot, lines, choices, told);
  let drawnNow = '', drawnChoices = '', drawnTold = '', portrait = '';
  return {
    root,
    open(open) { put(root, open ? 'true' : null, 'data-open'); },
    draw(shown) {
      if (shown.now !== drawnNow) {
        drawnNow = shown.now;
        now.textContent = shown.now;
        // A new line slides the line now up into the line before (r24, 200 ms).
        lines.getAnimations().forEach(animation => animation.cancel());
        lines.classList.remove('wu-scene-new'); void lines.offsetWidth; lines.classList.add('wu-scene-new');
      }
      before.hidden = !shown.before;
      if (shown.before) {
        if (beforeName.textContent !== shown.before.speaker) beforeName.textContent = shown.before.speaker;
        if (beforeWords.textContent !== shown.before.words) beforeWords.textContent = shown.before.words;
      }
      if (name.textContent !== shown.plate.name) name.textContent = shown.plate.name;
      if (to.textContent !== shown.plate.to) to.textContent = shown.plate.to;
      by.hidden = !shown.plate.by;
      if (shown.plate.by && by.textContent !== shown.plate.by) by.textContent = shown.plate.by;
      const face = shown.plate.portrait ?? '';
      if (face !== portrait || (!face && orb.textContent !== shown.plate.letter)) {
        portrait = face;
        orb.replaceChildren();
        if (face) { const image = element('img'); image.alt = ''; image.src = face; orb.append(image); } else orb.textContent = shown.plate.letter;
      }
      const words = `${shown.stopFollowing}\n${shown.day}`;
      if (words !== drawnChoices) {
        drawnChoices = words;
        choices.replaceChildren(glyphRows([
          { key: 'V', word: shown.stopFollowing, shortcut: 'V', onPress: onStop },
          { key: 'Enter', word: shown.day, shortcut: 'Enter', onPress: onDay },
          // The sheet's talking rows at both sizes (T9: at 1440 only the bars and the line now change).
        ], { glyph: 'max(32px, calc(32 * var(--u)))', rowGap: 'max(16px, calc(16 * var(--u)))', colGap: 'max(16px, calc(16 * var(--u)))',
          word: 'max(18px, calc(18 * var(--u)))', nudge: 1, bars: true }));
      }
      if (shown.told.join('\n') !== drawnTold) {
        drawnTold = shown.told.join('\n');
        told.replaceChildren(...shown.told.map(line => element('p', '', line)));
      }
      told.hidden = !shown.told.length;
      dot.hidden = !shown.dot;
      if (shown.dot) dot.style.transform = `translate3d(${shown.dot.x.toFixed(1)}px,${shown.dot.y.toFixed(1)}px,0)`;
    },
    remove() { root.remove(); },
  };
}
