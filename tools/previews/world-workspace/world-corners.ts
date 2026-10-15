// The world's corners (DESIGN's specification, section 5.2, frames 02 and 04): top left the way out
// (Your worlds, or Back), top right the world's clock with Play or Pause on P, top centre a mode
// word while a mode is on, bottom left the hints for what works now, which fade, the reticle, and
// one note at a time. Built from the shared parts (world-ui.ts); the world view (contextual-world.ts)
// and build mode tell the corners what to say.
import { clockLine, worldTime } from './world-clock.mjs';
import { CORNER_WORDS, NOTE_WORDS } from './world-words.mjs';
import { WORLD_UI_TIMING, hintsShown } from './world-ui-layout.mjs';
import { keyWord, notes as mountNotes, promptColumn, promptRow, setWord, type Notes } from './world-ui.ts';

/** What the corners read of the world's people and clock (environment-selection.ts, `people`). */
export interface CornerPeople {
  clock(): {
    readonly society: 'unconnected' | 'loading' | 'absent' | 'present' | 'unavailable';
    readonly mode: 'paused' | 'playing' | null;
    readonly minute: number | null;
    readonly startMinuteOfDay?: number | null;
    readonly busy: boolean;
  };
  play(): Promise<void>;
  pause(): Promise<void>;
}

/** One hint: its caps and word; `gapBefore` starts the keys that do something. */
export interface Hint { readonly keys: readonly string[] | 'mouse' | 'mouse-click'; readonly word: string; readonly shortcut?: string; readonly gapBefore?: boolean }

export interface Corners {
  /** The Back corner's element (build mode hides it while building, as before). */
  readonly backRoot: HTMLElement;
  /** The hints' element (build mode and inspecting hide it, as before). */
  readonly hintsRoot: HTMLElement;
  readonly reticle: HTMLElement;
  readonly notes: Notes;
  /** "Your worlds", "Back", or null while a question shows its own Esc. */
  back(word: string | null): void;
  /** A mode word at the top centre with its key, or null when no mode is on. */
  mode(word: string | null, prompt?: HTMLElement | null): void;
  /** The world's own hints, shown whenever no mode hands its own. */
  worldHints(list: readonly Hint[]): void;
  /** A mode's hints (a column when `vertical`), or null to give the world's own back. */
  hints(list: readonly Hint[] | null, options?: { readonly vertical?: boolean }): void;
  /** Brings faded hints back for a while (a hinted key, entering a mode). */
  wake(): void;
  /** Holds the hints shown while true (Tab held). */
  hold(on: boolean): void;
  /** Whether the world has a clock to play and pause (people live here). */
  hasClock(): boolean;
  /** Plays or pauses the world's time (P). */
  togglePlay(): void;
  /** Called every frame by the world view. */
  frame(now: number): void;
  dispose(): void;
}

const div = (className: string): HTMLDivElement => { const made = document.createElement('div'); made.className = className; return made; };

/** How often the clock reads the people's state, in ms (a minute of the world is seconds of real time). */
const CLOCK_READ_MS = 250;

export function mountCorners({ host, people, onLeave, readOnly = false, timing = WORLD_UI_TIMING }: {
  readonly host: HTMLElement;
  readonly people: CornerPeople | null;
  readonly onLeave: () => void;
  /** A copy that may not change the world: Play and Pause show dimmed and do nothing. */
  readonly readOnly?: boolean;
  readonly timing?: typeof WORLD_UI_TIMING;
}): Corners {
  const scrims = Object.fromEntries(['tl', 'tr', 'bl', 'tc'].map((corner) => [corner, div(`wu-scrim wu-${corner}`)])) as Record<'tl' | 'tr' | 'bl' | 'tc', HTMLDivElement>;
  const backRoot = div('wu-back');
  const backPrompt = keyWord({ keys: ['Esc'], word: CORNER_WORDS.yourWorlds, shortcut: 'Escape', onPress: () => onLeave() });
  backRoot.append(backPrompt);

  const clock = div('wu-clock');
  const time = div('wu-clock-time'), hhmm = div('wu-clock-hhmm'), state = div('wu-clock-state');
  const glyph = div('wu-glyph-pause'), stateWords = document.createElement('span');
  state.append(glyph, stateWords);
  time.append(hhmm, state);
  const playPrompt = keyWord({ keys: ['P'], word: CORNER_WORDS.play, shortcut: 'P', onPress: () => togglePlay() });
  clock.append(time, div('wu-divider'), playPrompt);
  clock.setAttribute('role', 'group');
  clock.setAttribute('aria-label', 'The world\'s clock');
  clock.hidden = true; scrims.tr.hidden = true;

  const modeRoot = div('wu-mode');
  modeRoot.hidden = true; scrims.tc.hidden = true;
  const reticle = div('wu-reticle');
  reticle.setAttribute('role', 'img'); reticle.setAttribute('aria-label', 'Centre aim');
  for (let corner = 0; corner < 4; corner++) reticle.append(document.createElement('i'));
  const hintsRoot = div('wu-hints');
  hintsRoot.setAttribute('aria-label', 'Keys');

  host.append(scrims.tl, scrims.tr, scrims.bl, scrims.tc, backRoot, clock, modeRoot, reticle, hintsRoot);
  const notes = mountNotes(host, { place: 'world' });

  let own: readonly Hint[] = [], handed: readonly Hint[] | null = null, vertical = false;
  let since = performance.now(), wokenAt = -Infinity, held = false, lastRead = -Infinity, shownTime = '', shownLine = '';
  let playing = false, present = false, sending = false;

  function drawHints(): void {
    const list = handed ?? own;
    const prompts = list.map((hint) => keyWord({ keys: hint.keys, word: hint.word, ...(hint.shortcut ? { shortcut: hint.shortcut } : {}) }));
    const gaps = list.flatMap((hint, index) => (hint.gapBefore && index > 0 ? [index - 1] : []));
    const drawn = vertical && handed ? promptColumn(prompts) : promptRow(prompts, gaps);
    hintsRoot.className = `wu-hints ${drawn.className}`;
    hintsRoot.replaceChildren(...drawn.childNodes);
  }

  function readClock(): void {
    const read = people?.clock() ?? null;
    present = read?.society === 'present';
    const at = present && read ? worldTime(read.minute ?? NaN, read.startMinuteOfDay ?? NaN) : null;
    clock.hidden = at === null; scrims.tr.hidden = at === null;
    if (!at || !read) return;
    playing = read.mode === 'playing';
    const line = clockLine(at.day, read.mode);
    if (at.hhmm !== shownTime) { hhmm.textContent = at.hhmm; shownTime = at.hhmm; }
    if (line !== shownLine) {
      stateWords.textContent = line; shownLine = line;
      glyph.className = playing ? 'wu-glyph-play' : 'wu-glyph-pause';
      setWord(playPrompt, playing ? CORNER_WORDS.pause : CORNER_WORDS.play);
    }
    (playPrompt as HTMLButtonElement).disabled = readOnly || read.busy || sending;
  }

  function togglePlay(): void {
    if (!people || !present || sending || readOnly) return;
    sending = true;
    const wanted = playing ? 'paused' : 'playing';
    const refused = wanted === 'playing' ? NOTE_WORDS.playRefused : NOTE_WORDS.pauseRefused;
    // The people's controls draw a refusal in their own panel and resolve, so the clock is read
    // again: where it did not change, the note says so.
    (wanted === 'playing' ? people.play() : people.pause())
      .then(() => { if (people.clock().mode !== wanted) notes.show(refused); }, () => notes.show(refused))
      .finally(() => { sending = false; lastRead = -Infinity; });
  }

  const corners: Corners = {
    backRoot, hintsRoot, reticle, notes,
    back(word) {
      backRoot.hidden = word === null;
      if (word !== null) setWord(backPrompt, word);
    },
    mode(word, prompt = null) {
      modeRoot.hidden = word === null; scrims.tc.hidden = word === null;
      modeRoot.replaceChildren();
      if (word === null) return;
      const words = div('wu-mode-word');
      words.append(div('wu-marker'), word);
      modeRoot.append(words);
      if (prompt) modeRoot.append(prompt);
      corners.wake();
    },
    worldHints(list) { own = list; if (!handed) drawHints(); },
    hints(list, options = {}) { handed = list; vertical = options.vertical === true; drawHints(); corners.wake(); },
    wake() { wokenAt = performance.now(); },
    hold(on) { held = on; },
    hasClock: () => present && !clock.hidden,
    togglePlay,
    frame(now) {
      if (now - lastRead >= CLOCK_READ_MS) { lastRead = now; readClock(); }
      const shown = hintsShown(now, { since, wokenAt, held, wake: timing.hintsWake, fadeAfter: timing.hintsFadeAfter });
      const faded = String(!shown);
      if (hintsRoot.dataset.faded !== faded) { hintsRoot.dataset.faded = faded; scrims.bl.style.opacity = shown ? '' : '0'; }
    },
    dispose() {
      notes.clear();
      for (const part of [...Object.values(scrims), backRoot, clock, modeRoot, reticle, hintsRoot, notes.root]) part.remove();
    },
  };
  since = performance.now();
  readClock();
  return corners;
}
