// The world screen as r02 draws it (DESIGN's R-WORLD-BUILD-SHEET, APPROVALS item 12): a short glass rail
// of icons at the top left (Your worlds, Build, History, Fly) with one tip at a time, one quiet pill at the
// top (the world's name and who lives here), the clock at the top right with Play or Pause on P, the
// reticle, a first-minute hint at the bottom that leaves once the person has walked and looked, and the
// keys behind one button at the bottom right. The rail gives way to "[Esc] Back" while something is chosen
// and to a mode's own pill (Building) while a mode is on. Where nobody lives yet, the pill says so and
// the clock's place offers to bring people in (K13, world-people.mjs). A mode's own hints (build mode's,
// flying's) still show at the bottom left as they did. One note at a time. Built from the shared parts
// (world-ui.ts) on the redraws' craft; the world view (contextual-world.ts) and build mode tell the
// corners what to say.
import { worldTime } from './world-clock.mjs';
import { SPEED_SCALE, speedBars } from './opening-steps.mjs';
import { CORNER_WORDS, NOTE_WORDS, PEOPLE_WORDS, SCREEN_WORDS } from './world-words.mjs';
import { mountPeople } from './world-people.mjs';
import { SCREEN_TIMING, clockText, firstHintLeaves, keysCardRows, railButtonOf, railEntries } from './world-screen.mjs';
import { WORLD_UI_TIMING, hintsShown } from './world-ui-layout.mjs';
import { keyWord, notes as mountNotes, pill, promptColumn, promptRow, tip as railTip, type Notes } from './world-ui.ts';
import './world-ui-world.css';

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

/** One row of the keys card: its key caps (or the mouse, its left button lit with 'mouse-click') and word. */
export interface KeysRow { readonly keys: readonly string[] | 'mouse' | 'mouse-click'; readonly word: string }

/** Where the person stands and looks (the controls' pose), for when the first-minute hint leaves. */
export interface CornerPose { readonly x: number; readonly z: number; readonly yaw: number; readonly pitch: number }

export interface Corners {
  /** The top left (the rail, or Back, or a mode's pill); a page hides it while it shows. */
  readonly backRoot: HTMLElement;
  /** A mode's hints at the bottom left (build mode and inspecting hide it, as before). */
  readonly hintsRoot: HTMLElement;
  readonly reticle: HTMLElement;
  readonly notes: Notes;
  /** "Your worlds" (the rail), "Back", or null while a question shows its own Esc. */
  back(word: string | null): void;
  /** A mode's word and its key as the top left's pill (Building), or null when no mode is on. */
  mode(word: string | null, prompt?: HTMLElement | null): void;
  /** Flying or not: Fly lit in the rail (Land its word), and flying's own hints. */
  flying(on: boolean): void;
  /** The world's own hints (flying's, while flying); otherwise nothing runs along the bottom. */
  worldHints(list: readonly Hint[]): void;
  /** A mode's hints (a column when `vertical`), or null to give the world's own back. */
  hints(list: readonly Hint[] | null, options?: { readonly vertical?: boolean }): void;
  /** Brings faded hints back for a while (a hinted key, entering a mode). */
  wake(): void;
  /** Holds the hints shown while true (Tab held). */
  hold(on: boolean): void;
  /** A key was pressed in the world: its rail button's tip shows for a while. */
  pressed(code: string): void;
  /** Closes the keys card if it is open; true when it was (Esc closes it before anything else). */
  closeKeys(): boolean;
  /** A mode's own rows for the keys card (build mode's), or null to give the world's own back. */
  keys(rows: readonly KeysRow[] | null): void;
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
const span = (className: string, text = ''): HTMLSpanElement => { const made = document.createElement('span'); made.className = className; made.textContent = text; return made; };
const button = (className: string): HTMLButtonElement => { const made = document.createElement('button'); made.type = 'button'; made.className = className; return made; };

/** A small key cap, its name only (hidden from a screen reader: the control's own name says it). */
function cap(name: string): HTMLSpanElement {
  const made = span('wu-key wu-small', name);
  made.setAttribute('aria-hidden', 'true');
  return made;
}

/** The rail's icons (the sheet's section 1: 20 px, a 1.4 px white stroke, round caps). */
const ICONS: Readonly<Record<string, string>> = Object.freeze({
  worlds: '<rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="11" y="3" width="6" height="6" rx="1.5"/><rect x="3" y="11" width="6" height="6" rx="1.5"/><rect x="11" y="11" width="6" height="6" rx="1.5"/>',
  build: '<path d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6z M3.5 6 10 9.5 16.5 6 M10 9.5v8"/>',
  history: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.8 1.8"/>',
  fly: '<path d="M2.5 12.5c4 0 7-2.6 9-8 .8 4.2 3 6.6 6 7-2.8 2-6 3-9.5 3-2 0-3.8-.6-5.5-2z"/>',
  keys: '<rect x="2.5" y="5" width="15" height="10" rx="2"/><path d="M5.5 8h1 M8.5 8h1 M11.5 8h1 M14.5 8h0 M5.5 11h0 M8 11.5h4"/>',
});
const icon = (name: string): string => `<svg viewBox="0 0 20 20" aria-hidden="true">${ICONS[name]}</svg>`;

/** How often the clock reads the people's state, in ms (a minute of the world is seconds of real time). */
const CLOCK_READ_MS = 250;

export function mountCorners({
  host, people, onLeave, title = '', worldId = '', readOnly = false, canBringIn = false, onBuild = null, onHistory = null, onFly = null,
  pose = () => null, flySpeed = () => NaN, timing = WORLD_UI_TIMING, screen = SCREEN_TIMING,
}: {
  readonly host: HTMLElement;
  readonly people: CornerPeople | null;
  readonly onLeave: () => void;
  /** The world's name, for the top pill. */
  readonly title?: string;
  /** The world's id: the first-minute hint is shown once per world on this computer. */
  readonly worldId?: string;
  /** A copy that may not change the world: Play and Pause show dimmed and do nothing. */
  readonly readOnly?: boolean;
  /** Whether this page may bring people into a world nobody lives in; elsewhere that corner stays empty (K13). */
  readonly canBringIn?: boolean;
  /** Opens build mode, as B does (the rail's Build, K13's Build); null where there is none. */
  readonly onBuild?: (() => void) | null;
  /** Opens History, as H does; null where it does not open. */
  readonly onHistory?: (() => void) | null;
  /** Starts or stops flying, as F does; null where there is no flying. */
  readonly onFly?: (() => void) | null;
  /** Where the person stands and looks now, or null before the world is drawn. */
  readonly pose?: () => CornerPose | null;
  /** The flying speed in metres a second, for the speed scale beside the Speed hint. */
  readonly flySpeed?: () => number;
  readonly timing?: typeof WORLD_UI_TIMING;
  readonly screen?: typeof SCREEN_TIMING;
}): Corners {
  // ---------- The top left: the rail, or Back, or a mode's pill ----------
  const backRoot = div('wu-corner wu-screen-in');
  const rail = div('wu-glass-thin wu-rail');
  rail.setAttribute('role', 'toolbar');
  rail.setAttribute('aria-label', SCREEN_WORDS.rail);
  rail.setAttribute('aria-orientation', 'vertical');
  type RailEntry = 'divider' | { readonly id: string; readonly key: string; readonly shortcut: string; readonly word: string; readonly lit: boolean };
  const railTips = new Map<string, HTMLButtonElement>();
  let flyingNow = false, tipShown: { id: string; until: number } | null = null, hovered: string | null = null;
  const tipRoot = div('');
  function drawRail(): void {
    railTips.clear();
    const parts = railEntries({ build: onBuild !== null, history: onHistory !== null, flying: flyingNow }).map((entry: RailEntry) => {
      if (entry === 'divider') return div('wu-rail-divider');
      const made = button('wu-rail-button');
      made.innerHTML = icon(entry.id);
      made.dataset.id = entry.id;
      made.dataset.lit = String(entry.lit);
      made.setAttribute('aria-label', entry.word);
      made.setAttribute('aria-keyshortcuts', entry.shortcut);
      if (entry.id === 'fly') made.setAttribute('aria-pressed', String(entry.lit));
      made.addEventListener('click', () => {
        if (entry.id === 'worlds') onLeave();
        else if (entry.id === 'build') onBuild?.();
        else if (entry.id === 'history') onHistory?.();
        else onFly?.();
      });
      made.addEventListener('pointerenter', () => { hovered = entry.id; drawTip(); });
      made.addEventListener('pointerleave', () => { if (hovered === entry.id) hovered = null; drawTip(); });
      made.addEventListener('focus', () => { hovered = entry.id; drawTip(); });
      made.addEventListener('blur', () => { if (hovered === entry.id) hovered = null; drawTip(); });
      railTips.set(entry.id, made);
      return made;
    });
    rail.replaceChildren(...parts, tipRoot);
    drawTip();
  }
  /** One tip at a time: the hovered or focused button's, else the one whose key was just pressed. */
  function drawTip(now = performance.now()): void {
    const id = hovered ?? (tipShown && now < tipShown.until ? tipShown.id : null);
    const target = id === null ? null : railTips.get(id) ?? null;
    if (target === null) { tipRoot.replaceChildren(); return; }
    const entry = railEntries({ build: onBuild !== null, history: onHistory !== null, flying: flyingNow }).find((one: RailEntry) => one !== 'divider' && one.id === id);
    if (!entry || entry === 'divider') { tipRoot.replaceChildren(); return; }
    const made = railTip(entry.word, entry.key);
    made.setAttribute('aria-hidden', 'true');
    made.style.top = `${target.offsetTop + target.offsetHeight / 2}px`;
    tipRoot.replaceChildren(made);
  }
  const backPill = button('wu-glass-thin wu-pill wu-corner-pill');
  const backWord = span('');
  backPill.append(cap('Esc'), backWord);
  backPill.setAttribute('aria-keyshortcuts', 'Escape');
  backPill.addEventListener('click', () => onLeave());
  const modePill = button('wu-glass-thin wu-pill wu-corner-pill');
  let modePrompt: HTMLElement | null = null;
  modePill.addEventListener('click', () => modePrompt?.click());
  backRoot.append(rail, backPill, modePill);
  let backWordNow: string | null = CORNER_WORDS.yourWorlds, modeWordNow: string | null = null;
  function drawTopLeft(): void {
    rail.hidden = modeWordNow !== null || backWordNow !== CORNER_WORDS.yourWorlds;
    backPill.hidden = modeWordNow !== null || backWordNow === null || backWordNow === CORNER_WORDS.yourWorlds;
    modePill.hidden = modeWordNow === null;
    if (!backPill.hidden) { backWord.textContent = backWordNow; backPill.setAttribute('aria-label', backWordNow ?? ''); }
  }

  // ---------- The top pill: the world's name and who lives here ----------
  const topName = span('', title), topRule = span('wu-top-rule'), topPeople = span('wu-top-people');
  topRule.setAttribute('aria-hidden', 'true');
  const top = pill(topName, topRule, topPeople);
  top.classList.add('wu-top', 'wu-screen-in');
  top.setAttribute('role', 'status');
  let shownPeople: string | null = '';
  function drawTop(now: number): void {
    const line = folk.line(now);
    if (line === shownPeople) return;
    shownPeople = line;
    topPeople.textContent = line ?? '';
    topPeople.hidden = line === null; topRule.hidden = line === null;
  }

  // ---------- The clock, and K13's offer in its place ----------
  const clock = button('wu-glass-thin wu-pill wu-clock-pill wu-screen-in');
  const glyph = span('wu-pause'), time = span('');
  glyph.setAttribute('aria-hidden', 'true');
  clock.append(glyph, time);
  clock.setAttribute('aria-keyshortcuts', 'P');
  clock.addEventListener('click', () => togglePlay());
  clock.hidden = true;
  // Where nobody lives yet (K13): "[P] Bring people in", then "Bringing people in…", or "[B] Build"
  // where people have nowhere to go (the pill's people line says why).
  const offer = button('wu-glass-thin wu-pill wu-clock-pill wu-screen-in');
  offer.hidden = true;
  offer.addEventListener('click', () => { if (offer.dataset.state === 'offer') folk.bringIn(); else if (offer.dataset.state === 'nowhere') onBuild?.(); });

  // ---------- The reticle, the hints, the first-minute hint, the keys ----------
  const reticle = div('wu-reticle');
  reticle.setAttribute('role', 'img'); reticle.setAttribute('aria-label', 'Centre aim');
  for (let corner = 0; corner < 4; corner++) reticle.append(document.createElement('i'));
  const scrim = div('wu-scrim wu-bl');
  scrim.hidden = true;
  const hintsRoot = div('wu-hints');
  hintsRoot.setAttribute('aria-label', 'Keys');
  hintsRoot.hidden = true;

  const hintKey = screen.firstHint.hintKey + worldId;
  const hintSeen = (() => { try { return worldId !== '' && localStorage.getItem(hintKey) === '1'; } catch { return false; } })();
  const firstHint = pill(SCREEN_WORDS.firstHint);
  firstHint.classList.add('wu-first-hint');
  firstHint.setAttribute('role', 'note');
  firstHint.hidden = hintSeen;
  let hintStart: number | null = null, hintFrom: CornerPose | null = null, hintWalked = 0, hintTurned = 0, hintLeftAt: number | null = null;

  const keysButton = button('wu-glass-thin wu-keys-button wu-screen-in');
  keysButton.innerHTML = icon('keys');
  keysButton.setAttribute('aria-label', SCREEN_WORDS.keys);
  keysButton.setAttribute('aria-expanded', 'false');
  const keysCard = div('wu-glass-thin wu-keys-card');
  keysCard.id = `wu-keys-${Math.random().toString(36).slice(2)}`;
  keysCard.setAttribute('role', 'dialog');
  keysCard.setAttribute('aria-label', SCREEN_WORDS.keys);
  keysCard.hidden = true;
  keysButton.setAttribute('aria-controls', keysCard.id);
  keysButton.addEventListener('click', () => (keysCard.hidden ? openKeys() : closeKeys()));
  let handedKeys: readonly KeysRow[] | null = null;
  function openKeys(): void {
    const rows: readonly KeysRow[] = handedKeys ?? keysCardRows({ build: onBuild !== null, history: onHistory !== null, clock: present });
    keysCard.replaceChildren(...rows.flatMap((row) => {
      const caps = span('wu-caps');
      if (row.keys === 'mouse-click' || row.keys === 'mouse') {
        const mouse = span(row.keys === 'mouse' ? 'wu-key wu-small wu-mouse' : 'wu-key wu-small wu-mouse wu-click');
        mouse.setAttribute('aria-hidden', 'true');
        caps.append(mouse);
      } else caps.append(...row.keys.map((name) => cap(name)));
      const keyNames = row.keys === 'mouse-click' || row.keys === 'mouse' ? 'Mouse' : row.keys.join(' ');
      const word = span('', row.word);
      word.setAttribute('aria-label', `${keyNames}: ${row.word}`);
      return [caps, word];
    }));
    keysCard.hidden = false;
    keysButton.setAttribute('aria-expanded', 'true');
  }
  function closeKeys(): boolean {
    if (keysCard.hidden) return false;
    keysCard.hidden = true;
    keysButton.setAttribute('aria-expanded', 'false');
    return true;
  }

  host.append(scrim, backRoot, top, clock, offer, reticle, hintsRoot, firstHint, keysCard, keysButton);
  const notes = mountNotes(host, { place: 'world' });

  let own: readonly Hint[] = [], handed: readonly Hint[] | null = null, vertical = false;
  let since = performance.now(), wokenAt = -Infinity, held = false, lastRead = -Infinity, shownTime = '', shownMode: string | null = null;
  let playing = false, present = false, sending = false;
  // Bringing people in (K13): world-people.mjs decides; the clock's place and the pill draw it.
  const folk = mountPeople({ people, canBringIn: canBringIn && !readOnly, canBuild: onBuild !== null, note: (words: string) => notes.show(words) });
  folk.onChange(() => { drawOffer(); shownPeople = ''; drawTop(performance.now()); });

  // The speed scale (frame 03): seven bars, the lit ones the flying speed's share of its range.
  let gauge: HTMLElement[] = [], litBars = -1;
  /** A mode's hints, or flying's; with neither, nothing runs along the bottom. */
  function drawHints(): void {
    const list = handed ?? (flyingNow ? own : []);
    hintsRoot.hidden = list.length === 0; scrim.hidden = list.length === 0;
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

  /** What the clock's place holds where nobody lives yet (K13). */
  function drawOffer(): void {
    const offered = clock.hidden ? folk.clockOffer() : null;
    offer.hidden = offered === null;
    if (!offered || offer.dataset.state === offered.state) return;
    offer.dataset.state = offered.state;
    offer.classList.toggle('wu-offer', offered.keys !== null);
    offer.classList.toggle('wu-waiting', offered.keys === null);
    offer.disabled = offered.keys === null;
    offer.replaceChildren(...(offered.keys ?? []).map((name: string) => cap(name)), span('', offered.word));
    offer.setAttribute('aria-keyshortcuts', offered.keys?.join(' ') ?? '');
    offer.setAttribute('aria-label', offered.state === 'nowhere' ? `${offered.word}: ${PEOPLE_WORDS.nowhere} ${PEOPLE_WORDS.nowhereSecond}` : offered.word);
  }

  function readClock(): void {
    const read = people?.clock() ?? null;
    present = read?.society === 'present';
    const at = present && read ? worldTime(read.minute ?? NaN, read.startMinuteOfDay ?? NaN) : null;
    clock.hidden = at === null;
    drawOffer();
    if (!at || !read) return;
    playing = read.mode === 'playing';
    const text = clockText(at.hhmm, at.day);
    if (text !== shownTime) { time.textContent = text; shownTime = text; }
    if (read.mode !== shownMode) {
      shownMode = read.mode;
      glyph.className = playing ? 'wu-play' : 'wu-pause';
      glyph.replaceChildren(...(playing ? [] : [document.createElement('i'), document.createElement('i')]));
    }
    // The clock is the play and pause button: it names what pressing it does.
    clock.setAttribute('aria-label', `${playing ? CORNER_WORDS.pause : CORNER_WORDS.play}, ${text}`);
    clock.disabled = readOnly || read.busy || sending;
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

  /** The first-minute hint: leaves once the person has walked and looked, or after its time, and stays gone in this world here. */
  function frameFirstHint(now: number): void {
    if (firstHint.hidden || hintLeftAt !== null) {
      if (hintLeftAt !== null && now - hintLeftAt >= screen.firstHint.fadeMs) firstHint.hidden = true;
      return;
    }
    // Flying and a mode's own hints take the bottom while they show; the minute counts on.
    firstHint.style.visibility = flyingNow || handed !== null ? 'hidden' : '';
    const at = pose();
    if (at === null) return;
    hintStart ??= now;
    if (hintFrom !== null) {
      hintWalked = Math.max(hintWalked, Math.hypot(at.x - hintFrom.x, at.z - hintFrom.z));
      hintTurned = Math.max(hintTurned, Math.abs(at.yaw - hintFrom.yaw) + Math.abs(at.pitch - hintFrom.pitch));
    } else hintFrom = at;
    if (!firstHintLeaves({ shownMs: now - hintStart, walkedM: hintWalked, turnedRad: hintTurned }, screen.firstHint)) return;
    hintLeftAt = now;
    firstHint.dataset.leaving = 'true';
    try { if (worldId !== '') localStorage.setItem(hintKey, '1'); } catch { /* Shown again next time. */ }
  }

  const corners: Corners = {
    backRoot, hintsRoot, reticle, notes,
    back(word) { backWordNow = word; drawTopLeft(); },
    mode(word, prompt = null) {
      // Going to build with nowhere for people to go is the step the corner asked for: it offers again.
      if (word !== null) folk.building();
      modeWordNow = word; modePrompt = prompt;
      const key = prompt?.getAttribute('aria-keyshortcuts') ?? null;
      modePill.replaceChildren(span('', word ?? ''), ...(key ? [cap(key)] : []));
      if (key) modePill.setAttribute('aria-keyshortcuts', key); else modePill.removeAttribute('aria-keyshortcuts');
      modePill.setAttribute('aria-label', [word, prompt?.textContent].filter(Boolean).join(': '));
      drawTopLeft();
      if (word !== null) corners.wake();
    },
    flying(on) { if (on === flyingNow) return; flyingNow = on; drawRail(); drawHints(); if (on) corners.wake(); },
    worldHints(list) { own = list; if (!handed) drawHints(); },
    hints(list, options = {}) { handed = list; vertical = options.vertical === true; drawHints(); corners.wake(); },
    wake() { wokenAt = performance.now(); },
    hold(on) { held = on; },
    pressed(code) {
      const id = railButtonOf(code);
      if (id === null || !railTips.has(id) || rail.hidden) return;
      tipShown = { id, until: performance.now() + screen.tipMs };
      drawTip();
    },
    closeKeys,
    keys(rows) {
      handedKeys = rows;
      // An open card shows the new rows at once.
      if (!keysCard.hidden) openKeys();
    },
    hasClock: () => present && !clock.hidden,
    togglePlay,
    people: folk,
    offersBringIn: () => !offer.hidden && folk.offersBringIn(),
    bringIn: () => folk.bringIn(),
    frame(now) {
      if (now - lastRead >= CLOCK_READ_MS) { lastRead = now; readClock(); drawTop(now); }
      if (tipShown && now >= tipShown.until) { tipShown = null; drawTip(now); }
      frameFirstHint(now);
      if (gauge.length) {
        const lit = speedBars(flySpeed());
        if (lit !== litBars) { litBars = lit; gauge.forEach((bar, index) => bar.classList.toggle('wu-on', index < lit)); }
      }
      const shown = hintsShown(now, { since, wokenAt, held, wake: timing.hintsWake, fadeAfter: timing.hintsFadeAfter });
      const faded = String(!shown);
      if (hintsRoot.dataset.faded !== faded) { hintsRoot.dataset.faded = faded; scrim.style.opacity = shown ? '' : '0'; }
    },
    dispose() {
      notes.clear();
      for (const part of [scrim, backRoot, top, clock, offer, reticle, hintsRoot, firstHint, keysCard, keysButton, notes.root]) part.remove();
    },
  };
  drawRail();
  drawTopLeft();
  since = performance.now();
  readClock();
  drawTop(since);
  return corners;
}
