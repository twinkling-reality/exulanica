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

/** The name of the window event a stage report travels on (seams.mjs dispatches it). */
export const OPENING_EVENT = 'exulanica:opening';

/**
 * Where the opening stands after these reports: how much of the line is drawn (0 to 1), the
 * words of the stage now running (null once all are done) and whether all are done. Reports out of
 * order count only up to the first stage not yet reported.
 */
export function openingProgress(reports, stages = OPENING_STAGES) {
  const seen = new Set(reports);
  let done = 0;
  while (done < stages.length && seen.has(stages[done].report)) done++;
  return { fraction: done / stages.length, words: done < stages.length ? stages[done].words : null, done: done === stages.length };
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
