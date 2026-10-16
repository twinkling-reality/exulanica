// The world's corners (DESIGN's specification, section 5.2, frames 02 and 04): top left the way out
// (Your worlds, or Back), top right the world's clock with Play or Pause on P, top centre a mode
// word while a mode is on, bottom left the hints for what works now, which fade, the reticle, and
// one note at a time. Where nobody lives yet, the clock's corner offers to bring people in (K13).
// Built from the shared parts (world-ui.ts); the world view (contextual-world.ts) and build mode tell
// the corners what to say.
import { clockLine, worldTime } from './world-clock.mjs';
import { SPEED_SCALE, speedBars } from './opening-steps.mjs';
import { CORNER_WORDS, NOTE_WORDS, PEOPLE_WORDS, withoutCornerKeys } from './world-words.mjs';
import { mountPeople } from './world-people.mjs';
import { WORLD_UI_TIMING, hintsShown } from './world-ui-layout.mjs';
import { keyWord, notes as mountNotes, promptColumn, promptRow, setWord, type Notes } from './world-ui.ts';

/** What the corners read of the world's people and clock (environment-selection.ts, `people`). */
export interface CornerPeople {
  clock(): {
    readonly society: 'unconnected' | 'loading' | 'absent' | 'present' | 'unavailable';
    readonly mode: 'paused' | 'playing' | null;
    readonly minute: number | null;
    readonly startMinuteOfDay?: number | null;
    readonly population?: number | null;
    readonly busy: boolean;
  };
  play(): Promise<void>;
  pause(): Promise<void>;
  /** The People panel's own request to bring people in; a refusal rejects with the server's code. */
  bringIn?(): Promise<void>;
}

/** One hint: its caps and word; `gapBefore` starts the keys that do something. */
export interface Hint { readonly keys: readonly string[] | 'mouse' | 'mouse-click'; readonly word: string; readonly shortcut?: string; readonly gapBefore?: boolean; readonly gauge?: boolean }

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
  /** Where nobody lives yet (K13): the people line and what the clock holds in its place. */
  readonly people: ReturnType<typeof mountPeople>;
  /** Whether the clock's corner offers to bring people in now (P brings them in). */
  offersBringIn(): boolean;
  /** Brings people in, as the corner's prompt does (P where nobody lives yet). */
  bringIn(): void;
  /** Called every frame by the world view. */
  frame(now: number): void;
  dispose(): void;
}

const div = (className: string): HTMLDivElement => { const made = document.createElement('div'); made.className = className; return made; };

/** How often the clock reads the people's state, in ms (a minute of the world is seconds of real time). */
const CLOCK_READ_MS = 250;

export function mountCorners({ host, people, onLeave, readOnly = false, canBringIn = false, onBuild = null, flySpeed = () => NaN, timing = WORLD_UI_TIMING }: {
  readonly host: HTMLElement;
  readonly people: CornerPeople | null;
  readonly onLeave: () => void;
  /** A copy that may not change the world: Play and Pause show dimmed and do nothing. */
  readonly readOnly?: boolean;
  /** Whether this page may bring people into a world nobody lives in; elsewhere that corner stays empty (K13). */
  readonly canBringIn?: boolean;
  /** Opens build mode, as B does, for the corner's Build where people have nowhere to go; null where there is none. */
  readonly onBuild?: (() => void) | null;
  /** The flying speed in metres a second, for the speed scale beside the Speed hint. */
  readonly flySpeed?: () => number;
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

  // Where nobody lives yet (K13): the same corner in the clock's own layout, a line where the time
  // goes, the divider and the prompt; the line describes the prompt.
  const welcome = div('wu-clock wu-welcome');
  const welcomeLine = div('wu-welcome-line'), welcomeFirst = document.createElement('span'), welcomeSecond = div('wu-welcome-second');
  welcomeLine.id = `wu-welcome-${Math.random().toString(36).slice(2)}`;
  welcomeLine.append(welcomeFirst, welcomeSecond);
  const welcomeDivider = div('wu-divider');
  const bringPrompt = keyWord({ keys: ['P'], word: PEOPLE_WORDS.bringIn, shortcut: 'P', onPress: () => folk.bringIn() });
  const buildPrompt = keyWord({ keys: ['B'], word: PEOPLE_WORDS.build, shortcut: 'B', onPress: () => onBuild?.() });
  bringPrompt.setAttribute('aria-describedby', welcomeLine.id);
  buildPrompt.setAttribute('aria-describedby', welcomeLine.id);
  welcome.append(welcomeLine, welcomeDivider, bringPrompt, buildPrompt);
  welcome.hidden = true;

  const modeRoot = div('wu-mode');
  modeRoot.hidden = true; scrims.tc.hidden = true;
  const reticle = div('wu-reticle');
  reticle.setAttribute('role', 'img'); reticle.setAttribute('aria-label', 'Centre aim');
  for (let corner = 0; corner < 4; corner++) reticle.append(document.createElement('i'));
  const hintsRoot = div('wu-hints');
  hintsRoot.setAttribute('aria-label', 'Keys');

  host.append(scrims.tl, scrims.tr, scrims.bl, scrims.tc, backRoot, clock, welcome, modeRoot, reticle, hintsRoot);
  const notes = mountNotes(host, { place: 'world' });

  let own: readonly Hint[] = [], handed: readonly Hint[] | null = null, vertical = false;
  let since = performance.now(), wokenAt = -Infinity, held = false, lastRead = -Infinity, shownTime = '', shownLine = '';
  let playing = false, present = false, sending = false;
  // Bringing people in (K13): world-people.mjs decides; the clock's corner draws it (drawWelcome) and
  // redraws at once when an answer comes.
  const folk = mountPeople({ people, canBringIn: canBringIn && !readOnly, canBuild: onBuild !== null, note: (words) => notes.show(words) });
  folk.onChange(() => { drawWelcome(); scrims.tr.hidden = clock.hidden && welcome.hidden; });

  // The speed scale (frame 03): seven bars, the lit ones the flying speed's share of its range.
  let gauge: HTMLElement[] = [], litBars = -1;
  function drawHints(): void {
    // The corner's Build stands for the hint row's own B while it shows, so B is drawn once (K13).
    const list = handed ?? (!welcome.hidden && welcome.dataset.state === 'nowhere' ? withoutCornerKeys(own, ['B']) : own);
    gauge = []; litBars = -1;
    const prompts = list.map((hint) => {
      const prompt = keyWord({ keys: hint.keys, word: hint.word, ...(hint.shortcut ? { shortcut: hint.shortcut } : {}) });
      if (hint.gauge) {
        const scale = div('wu-gauge');
        scale.setAttribute('aria-hidden', 'true');
        gauge = Array.from({ length: SPEED_SCALE.bars }, (_, index) => {
          const bar = document.createElement('i');
          bar.style.height = `calc(${6 + index * 2} * var(--u))`;
          return bar;
        });
        scale.append(...gauge);
        prompt.append(scale);
      }
      return prompt;
    });
    const gaps = list.flatMap((hint, index) => (hint.gapBefore && index > 0 ? [index - 1] : []));
    const drawn = vertical && handed ? promptColumn(prompts) : promptRow(prompts, gaps);
    hintsRoot.className = `wu-hints ${drawn.className}`;
    hintsRoot.replaceChildren(...drawn.childNodes);
  }

  /** The welcome corner: what world-people.mjs says the clock holds where nobody lives yet (K13). */
  function drawWelcome(): void {
    const offer = clock.hidden ? folk.clockOffer() : null;
    const was = welcome.hidden ? null : welcome.dataset.state;
    welcome.hidden = offer === null;
    if (!offer) { if (was !== null && !handed) drawHints(); return; }
    if (was === offer.state) return;
    welcome.dataset.state = offer.state;
    const nowhere = offer.state === 'nowhere';
    welcomeFirst.textContent = offer.state === 'bringing' ? offer.word : nowhere ? PEOPLE_WORDS.nowhere : PEOPLE_WORDS.nobodyYet;
    welcomeSecond.textContent = PEOPLE_WORDS.nowhereSecond;
    welcomeSecond.hidden = !nowhere;
    bringPrompt.hidden = offer.state !== 'offer';
    buildPrompt.hidden = !nowhere;
    welcomeDivider.hidden = bringPrompt.hidden && buildPrompt.hidden;
    if (!handed) drawHints();
  }

  function readClock(): void {
    const read = people?.clock() ?? null;
    present = read?.society === 'present';
    const at = present && read ? worldTime(read.minute ?? NaN, read.startMinuteOfDay ?? NaN) : null;
    clock.hidden = at === null;
    drawWelcome();
    scrims.tr.hidden = clock.hidden && welcome.hidden;
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
      // Going to build with nowhere for people to go is the step the corner asked for: it offers again.
      if (word !== null) folk.building();
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
    people: folk,
    offersBringIn: () => !welcome.hidden && folk.offersBringIn(),
    bringIn: () => folk.bringIn(),
    frame(now) {
      if (now - lastRead >= CLOCK_READ_MS) { lastRead = now; readClock(); }
      if (gauge.length) {
        const lit = speedBars(flySpeed());
        if (lit !== litBars) { litBars = lit; gauge.forEach((bar, index) => bar.classList.toggle('wu-on', index < lit)); }
      }
      const shown = hintsShown(now, { since, wokenAt, held, wake: timing.hintsWake, fadeAfter: timing.hintsFadeAfter });
      const faded = String(!shown);
      if (hintsRoot.dataset.faded !== faded) { hintsRoot.dataset.faded = faded; scrims.bl.style.opacity = shown ? '' : '0'; }
    },
    dispose() {
      notes.clear();
      for (const part of [...Object.values(scrims), backRoot, clock, welcome, modeRoot, reticle, hintsRoot, notes.root]) part.remove();
    },
  };
  since = performance.now();
  readClock();
  return corners;
}
