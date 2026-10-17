// The corners' words (DESIGN's WORDS.md, "Arriving and moving") and which keys the hints draw: a
// key is drawn only when its action works here (ruling K6).

export const CORNER_WORDS = Object.freeze({
  yourWorlds: 'Your worlds', back: 'Back', play: 'Play', pause: 'Pause', flying: 'Flying', land: 'Land',
  move: 'Move', sprint: 'Sprint', look: 'Look', fly: 'Fly', up: 'Up', down: 'Down', inspect: 'Inspect', build: 'Build', history: 'History',
  speed: 'Speed',
});

/** The world screen's own words (R-WORLD-BUILD-SHEET): the first-minute hint, the keys card and its button. */
export const SCREEN_WORDS = Object.freeze({
  firstHint: 'W A S D to walk, the mouse to look', keys: 'Keys', playing: 'Playing', paused: 'Paused', drag: 'Look', follow: 'Follow', clock: 'The world\'s clock', rail: 'The world',
});

/** The opening's words (frame 01): its label, the tip's label and its one tip. */
export const OPENING_WORDS = Object.freeze({
  opening: 'Opening', tip: 'Tip',
  tipKeys: Object.freeze([{ keys: ['F'], word: 'Fly' }, { keys: ['Space'], word: 'Up' }, { keys: ['C'], word: 'Down' }]),
});

export const NOTE_WORDS = Object.freeze({
  closer: 'Walk closer to inspect.',
  playRefused: 'The world did not start playing. Try again in a moment.',
  pauseRefused: 'The world did not pause. Try again in a moment.',
  offline: 'Not connected to your world. Trying again.',
  peopleChanged: 'The world changed a moment ago, so nobody came in. Try again.',
  peopleNotNow: 'People cannot come in right now. Try again in a moment.',
  peopleRefused: 'People could not be brought in. Try again.',
});

/**
 * Bringing people in where nobody lives yet (DESIGN's K13): what the clock's corner holds before the
 * clock, while they come in, and when there is nowhere for them to go.
 */
export const PEOPLE_WORDS = Object.freeze({
  nobodyYet: 'Nobody lives here yet', bringIn: 'Bring people in', bringing: 'Bringing people in…',
  nowhere: 'People need somewhere', nowhereSecond: 'to rest or visit nearby', build: 'Build',
  invented: 'invented for this world',
});

/**
 * The top pill's people line where people live: "24 people live here", or for a minute after they
 * arrive, "24 people now live here, invented for this world" (DESIGN's K14: the pill alone says it,
 * with no note beside it); null for a count it cannot say.
 */
export function peopleLine(count, { arrived = false } = {}) {
  if (!Number.isSafeInteger(count) || count <= 0) return null;
  if (arrived) return `${count === 1 ? '1 person now lives' : `${count} people now live`} here, ${PEOPLE_WORDS.invented}`;
  return count === 1 ? '1 person lives here' : `${count} people live here`;
}

/** The pill's people line when there is nowhere for people to go: the corner's two lines as one. */
export const nowhereLine = () => `${PEOPLE_WORDS.nowhere} ${PEOPLE_WORDS.nowhereSecond}`;


/**
 * What a refused bring-in shows (K13): with nowhere they could reach, the corner's own state, which
 * stays until the person acts; any other refusal is one note and the corner offers it again. `error`
 * is the request's refusal, read by its code and status.
 */
export function bringInRefused(error) {
  const code = typeof error?.code === 'string' ? error.code : null;
  if (code === 'no_reachable_targets') return { corner: 'nowhere', note: null };
  if (code === 'society_engine_differs') return { corner: 'offer', note: NOTE_WORDS.peopleChanged };
  if (error?.status === 424) return { corner: 'offer', note: NOTE_WORDS.peopleNotNow };
  return { corner: 'offer', note: NOTE_WORDS.peopleRefused };
}

/** `list` without the hints for the single keys a corner draws itself, so each key is drawn once (K13). */
export function withoutCornerKeys(list, keys) {
  return list.filter((hint) => !(Array.isArray(hint.keys) && hint.keys.length === 1 && keys.includes(hint.keys[0])));
}

/**
 * The hints for this moment, in order, each { keys, word, gapBefore?, gauge? }: moving keys first, then a
 * gap and the keys that do something. `state`: { flying, build, history, clock }; `build` and
 * `history` say whether B and H work here.
 */
export function availableHints(state) {
  const w = CORNER_WORDS;
  if (state.flying) {
    return [
      { keys: ['W', 'A', 'S', 'D'], word: w.move }, { keys: ['Space'], word: w.up }, { keys: ['C'], word: w.down },
      { keys: ['Shift'], word: w.sprint }, { keys: 'mouse', word: w.speed, gauge: true },
    ];
  }
  const doing = [{ keys: ['F'], word: w.fly, gapBefore: true }, { keys: ['E'], word: w.inspect }];
  if (state.build) doing.push({ keys: ['B'], word: w.build });
  if (state.history) doing.push({ keys: ['H'], word: w.history });
  return [{ keys: ['W', 'A', 'S', 'D'], word: w.move }, { keys: ['Shift'], word: w.sprint }, { keys: 'mouse-click', word: w.look }, ...doing];
}
