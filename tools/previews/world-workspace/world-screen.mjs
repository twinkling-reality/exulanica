// The world screen as r02 draws it (DESIGN's R-WORLD-BUILD-SHEET, APPROVALS item 12), as data in and
// data out: the rail's buttons, the keys card's rows, the clock's one line and when the first-minute
// hint leaves. Pure, so verify-world-screen.mjs checks it in Node; world-corners.ts draws it.
import { CORNER_WORDS, SCREEN_WORDS } from './world-words.mjs';

/**
 * How the screen behaves, each figure a field a world or look could want different: a rail button's
 * tip stays `tipMs` after its key is pressed; the first-minute hint leaves once the person has walked
 * `walkedM` metres and turned `lookedRad` radians, or after `leaveAfterMs`, fading over `fadeMs`, and
 * is not shown again in that world on that computer (`hintKey` and the world's id name the record).
 */
export const SCREEN_TIMING = Object.freeze({
  tipMs: 3_000,
  firstHint: Object.freeze({ leaveAfterMs: 60_000, walkedM: 1.5, lookedRad: 0.35, fadeMs: 400, hintKey: 'exulanica.world-first-hint.v1:' }),
});

/**
 * The rail's buttons, top to bottom (the sheet's section 1): Your worlds, a divider, then Build and
 * History where they work here, and Fly (Land while flying, then lit). Each { id, key, shortcut,
 * word, lit } or the string 'divider'. `state`: { build, history, flying }.
 * @returns {Array<'divider' | { id: string, key: string, shortcut: string, word: string, lit: boolean }>}
 */
export function railEntries(state) {
  /** @type {Array<'divider' | { id: string, key: string, shortcut: string, word: string, lit: boolean }>} */
  const entries = [{ id: 'worlds', key: 'Esc', shortcut: 'Escape', word: CORNER_WORDS.yourWorlds, lit: false }, 'divider'];
  if (state.build) entries.push({ id: 'build', key: 'B', shortcut: 'B', word: CORNER_WORDS.build, lit: false });
  if (state.history) entries.push({ id: 'history', key: 'H', shortcut: 'H', word: CORNER_WORDS.history, lit: false });
  entries.push({ id: 'fly', key: 'F', shortcut: 'F', word: state.flying ? CORNER_WORDS.land : CORNER_WORDS.fly, lit: Boolean(state.flying) });
  return entries;
}

/** Which rail button a key's tip belongs to, by the key's code, or null. */
export function railButtonOf(code) {
  return { Escape: 'worlds', KeyB: 'build', KeyH: 'history', KeyF: 'fly' }[code] ?? null;
}

/**
 * The keys card's rows (the sheet's section 8, WORDS.md's key table for the world view): each
 * { keys, word }, keys a list of key names or 'mouse-click'. A key is listed only where it works here
 * (ruling K6): Build, History and Play where `state` says so. No new key; E Inspect is the one place a
 * person learns how to choose someone once the hint row is gone.
 */
export function keysCardRows(state) {
  const w = CORNER_WORDS;
  /** @type {Array<{ keys: string[] | 'mouse-click', word: string }>} */
  const rows = [
    { keys: ['W', 'A', 'S', 'D'], word: w.move },
    { keys: ['Shift'], word: w.sprint },
    { keys: 'mouse-click', word: SCREEN_WORDS.drag },
    { keys: ['E'], word: w.inspect },
    { keys: ['F'], word: w.fly },
  ];
  if (state.build) rows.push({ keys: ['B'], word: w.build });
  if (state.history) rows.push({ keys: ['H'], word: w.history });
  if (state.clock) rows.push({ keys: ['P'], word: w.play });
  rows.push({ keys: ['V'], word: SCREEN_WORDS.follow }, { keys: ['Esc'], word: w.yourWorlds });
  return rows;
}

/** The clock's one line: "06:55 · Day 1". */
export function clockText(hhmm, day) {
  return `${hhmm} · Day ${day}`;
}

/**
 * Whether the first-minute hint leaves now: once the person has both walked and looked, or once it
 * has shown for its time. `shownMs` is how long it has shown; `walkedM` how far the person has moved
 * in plan; `turnedRad` how far the view has turned (yaw and pitch together).
 */
export function firstHintLeaves({ shownMs, walkedM, turnedRad }, rule = SCREEN_TIMING.firstHint) {
  return shownMs >= rule.leaveAfterMs || (walkedM >= rule.walkedM && turnedRad >= rule.lookedRad);
}
