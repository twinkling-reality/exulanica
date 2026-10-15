// The corners' words (DESIGN's WORDS.md, "Arriving and moving") and which keys the hints draw: a
// key is drawn only when its action works here (ruling K6).

export const CORNER_WORDS = Object.freeze({
  yourWorlds: 'Your worlds', back: 'Back', play: 'Play', pause: 'Pause', flying: 'Flying', land: 'Land',
  move: 'Move', sprint: 'Sprint', look: 'Look', fly: 'Fly', up: 'Up', down: 'Down', inspect: 'Inspect', build: 'Build', history: 'History',
});

export const NOTE_WORDS = Object.freeze({
  closer: 'Walk closer to inspect.',
  playRefused: 'The world did not start playing. Try again in a moment.',
  pauseRefused: 'The world did not pause. Try again in a moment.',
  offline: 'Not connected to your world. Trying again.',
});

/**
 * The hints for this moment, in order, each { keys, word, gapBefore? }: moving keys first, then a
 * gap and the keys that do something. `state`: { flying, build, history, clock }; `build` and
 * `history` say whether B and H work here.
 */
export function availableHints(state) {
  const w = CORNER_WORDS;
  if (state.flying) {
    return [
      { keys: ['W', 'A', 'S', 'D'], word: w.move }, { keys: ['Space'], word: w.up }, { keys: ['C'], word: w.down },
      { keys: ['Shift'], word: w.sprint },
    ];
  }
  const doing = [{ keys: ['F'], word: w.fly, gapBefore: true }, { keys: ['E'], word: w.inspect }];
  if (state.build) doing.push({ keys: ['B'], word: w.build });
  if (state.history) doing.push({ keys: ['H'], word: w.history });
  return [{ keys: ['W', 'A', 'S', 'D'], word: w.move }, { keys: ['Shift'], word: w.sprint }, { keys: 'mouse-click', word: w.look }, ...doing];
}
