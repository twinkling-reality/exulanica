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
  /** How long the pill says why a run ended before its people line returns (r09). */
  runEndedMs: 6_000,
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
 * What the clock says, its state in words (F2): the world's time (`at`, worldTime's answer) where the
 * world keeps one, with "Paused" after it while it does not play ("06:55 · Day 1 · Paused"); else
 * whether it plays ("Playing", "Paused"), as for a society that keeps no time of day.
 */
export function clockLabel(at, mode) {
  if (at) return mode === 'playing' ? clockText(at.hhmm, at.day) : `${clockText(at.hhmm, at.day)} · ${SCREEN_WORDS.paused}`;
  return mode === 'playing' ? SCREEN_WORDS.playing : SCREEN_WORDS.paused;
}

/**
 * The line under a clock set to play that this server does not advance, in the words the clock is handed (the page's
 * own sentence for `host_playback_code`: a guest's town waiting for a place among those playing, or a server that plays
 * nothing by itself); null for a clock that plays or one its person paused.
 */
export function clockWaiting({ mode, waiting = null }) {
  return mode === 'playing' && typeof waiting === 'string' && waiting.trim() !== '' ? waiting : null;
}

/**
 * Whether the first-minute hint leaves now: once the person has both walked and looked, or once it
 * has shown for its time. `shownMs` is how long it has shown; `walkedM` how far the person has moved
 * in plan; `turnedRad` how far the view has turned (yaw and pitch together).
 */
export function firstHintLeaves({ shownMs, walkedM, turnedRad }, rule = SCREEN_TIMING.firstHint) {
  return shownMs >= rule.leaveAfterMs || (walkedM >= rule.walkedM && turnedRad >= rule.lookedRad);
}

/**
 * One frame of the first-minute hint's measure: how far the person has walked and turned, counted
 * only from their own input. Until they press a moving key (`input.walked`) the place it counts
 * from follows the camera, and until they look with the mouse (`input.looked`) the view it counts
 * from does, so the world's own camera moves (its opening glide, its arrival) count as nothing.
 * `held` is the last answer, or null at first; `at` the pose now. Answers the new `held`.
 */
export function firstHintMeasure(held, at, input) {
  const place = input.walked ? (held?.place ?? { x: at.x, z: at.z }) : { x: at.x, z: at.z };
  const view = input.looked ? (held?.view ?? { yaw: at.yaw, pitch: at.pitch }) : { yaw: at.yaw, pitch: at.pitch };
  return {
    place,
    view,
    walked: Math.max(held?.walked ?? 0, Math.hypot(at.x - place.x, at.z - place.z)),
    turned: Math.max(held?.turned ?? 0, Math.abs(at.yaw - view.yaw) + Math.abs(at.pitch - view.pitch)),
  };
}
