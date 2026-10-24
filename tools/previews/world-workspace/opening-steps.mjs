// The numbers and words behind opening a world (DESIGN's specification 8.1 to 8.3 and 5.18), kept
// apart from the DOM so verify-world-opening.mjs can check them in Node.

/**
 * The loader's real stages, in order, each with the report that ends it and the words shown while
 * it runs. The line moves only on a report; a stage the loader does not report is not shown.
 */
export const OPENING_STAGES = Object.freeze([
  Object.freeze({ report: 'world-read', words: 'Reading the world' }),
  Object.freeze({ report: 'land-drawn', words: 'Drawing the land' }),
  Object.freeze({ report: 'people-in', words: 'Bringing in its people' }),
]);

/**
 * The stage a town still baking opens with, before the loader's own (C3): the page waits for its
 * land to be made, and the line moves as the bake's tiles, or their steps, finish. It ends when the
 * town reads baked.
 */
export const BAKING_STAGE = Object.freeze({ report: 'land-made', words: 'Making the land' });

/** The name of the window event a stage report travels on (seams.mjs dispatches it). */
export const OPENING_EVENT = 'exulanica:opening';

/**
 * Where the opening stands after these reports: how much of the line is drawn (0 to 1), the
 * words of the stage now running (null once all are done) and whether all are done. Reports out of
 * order count only up to the first stage not yet reported. `share` (0 to 1) is how much of the
 * running stage is done, where the loader can say.
 */
export function openingProgress(reports, stages = OPENING_STAGES, share = 0) {
  const seen = new Set(reports);
  let done = 0;
  while (done < stages.length && seen.has(stages[done].report)) done++;
  const part = done < stages.length && Number.isFinite(share) ? Math.min(1, Math.max(0, share)) : 0;
  return { fraction: (done + part) / stages.length, words: done < stages.length ? stages[done].words : null, done: done === stages.length };
}

/**
 * How much of a town's bake is done (0 to 1), from the tiles its entry serves, each counting the
 * same: a baked tile whole, a baking tile the share of its steps it states finished (stepsFinished
 * of steps, the entry's steps_finished and steps) or none where it states none. Only facts the entry
 * serves move it.
 */
export function bakeShare(tiles) {
  if (!Array.isArray(tiles) || tiles.length === 0) return 0;
  let done = 0;
  for (const tile of tiles) {
    if (tile?.state === 'baked') done += 1;
    else if (tile?.state === 'baking' && Number.isSafeInteger(tile.steps) && tile.steps > 0 && Number.isSafeInteger(tile.stepsFinished)) {
      done += Math.min(Math.max(tile.stepsFinished, 0), tile.steps) / tile.steps;
    }
  }
  return done / tiles.length;
}

/** The flying speeds the renderer allows (atlas-react controls.ts FLY_SPEED), as defaults. */
export const SPEED_SCALE = Object.freeze({ least: 2, most: 150, bars: 7 });

/** How many of the speed scale's bars are lit at `speed` metres a second: one at the least, all at the most, evenly by ratio. */
export function speedBars(speed, scale = SPEED_SCALE) {
  if (!(speed > 0)) return 1;
  const share = Math.log(speed / scale.least) / Math.log(scale.most / scale.least);
  return Math.min(scale.bars, Math.max(1, 1 + Math.round(share * (scale.bars - 1))));
}

/** The banner's line under a world's name: how many people live there, or null where nobody does. */
export function populationLine(count) {
  if (!Number.isSafeInteger(count) || count <= 0) return null;
  return count === 1 ? '1 person lives here' : `${count} people live here`;
}

/** What the front door hands the opening page for one world, under this key in sessionStorage. */
export const OPENING_HANDOFF_KEY = 'exulanica.opening.v1';

/** The handoff read back for `entryId`, or null where it names another world or is not well formed. */
export function readHandoff(text, entryId) {
  try {
    const value = JSON.parse(text ?? 'null');
    if (!value || value.entryId !== entryId || typeof value.title !== 'string') return null;
    const picture = typeof value.picture === 'string' && value.picture.startsWith('data:image/') ? value.picture : null;
    return { entryId, title: value.title, picture };
  } catch {
    return null;
  }
}
