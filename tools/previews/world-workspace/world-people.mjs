// Bringing people into a world nobody lives in yet (DESIGN's K13, placed on the world screen by
// R-WORLD-BUILD-SHEET sections 2 and 3): what the top pill's people line says, what the clock holds in its
// place until people live here, and the People panel's own request that brings them in. It decides and
// asks; the corners (world-corners.ts) draw what it says, so the pill and the clock read one state.
// Plain JavaScript so verify-world-corners.mjs runs it with a stand-in for the people read.
import { NOTE_WORDS, PEOPLE_WORDS, bringInRefused, nowhereLine, peopleLine } from './world-words.mjs';

/** How long the pill says that people now live here once they arrive, in ms (one minute, the sheet's). */
export const PEOPLE_TIMING = Object.freeze({ arrivedMs: 60_000 });

/**
 * The people state of one world view. `people` is the corners' read (world-corners.ts CornerPeople:
 * clock() and the panel's bringIn()); `canBringIn` whether this page may bring people in (never the
 * read-only observer); `canBuild` whether the clock may offer Build where people have nowhere to go;
 * `note` shows one note. Returns:
 * - line(now?): the pill's people line, or null while the world's people are not read yet;
 * - clockOffer(): what the clock holds in its place, { state: 'offer' | 'bringing' | 'nowhere', keys, word },
 *   keys null while asking, or null where the clock shows or this page offers nothing;
 * - offersBringIn(): whether P brings people in now; bringIn(): asks, as P and the clock's prompt do;
 * - building(): build mode opened, so with nowhere for people to go the clock offers again;
 * - onChange(listener): called when an answer changes what the pill or the clock says; returns its removal.
 */
export function mountPeople({ people, canBringIn, canBuild, note, timing = PEOPLE_TIMING, now = () => performance.now() }) {
  let welcome = 'offer', bringing = false, arrivedAt = null;
  const listeners = new Set();
  const changed = () => { for (const listener of listeners) listener(); };
  const offering = () => canBringIn && typeof people?.bringIn === 'function';
  const absent = () => people?.clock().society === 'absent';

  function clockOffer() {
    if (!offering() || (!bringing && !absent())) return null;
    if (bringing) return { state: 'bringing', keys: null, word: PEOPLE_WORDS.bringing };
    if (welcome === 'nowhere') return canBuild ? { state: 'nowhere', keys: ['B'], word: PEOPLE_WORDS.build } : null;
    return { state: 'offer', keys: ['P'], word: PEOPLE_WORDS.bringIn };
  }

  function bringIn() {
    if (!offering() || bringing || welcome !== 'offer' || !absent()) return;
    bringing = true;
    changed();
    let asked;
    try { asked = Promise.resolve(people.bringIn()); } catch (error) { asked = Promise.reject(error); }
    asked.then(() => {
      const after = people.clock();
      bringing = false;
      // Once they live here the pill says so for a minute (line()); no note repeats it (DESIGN's K14).
      if (after.society === 'present') arrivedAt = now();
      else note(NOTE_WORDS.peopleRefused);
    }, (error) => {
      const refused = bringInRefused(error);
      bringing = false;
      welcome = refused.corner;
      if (refused.note) note(refused.note);
    }).finally(changed);
  }

  return {
    line(at = now()) {
      const read = people?.clock() ?? null;
      if (!read) return null;
      if (read.society === 'present') return peopleLine(read.population ?? NaN, { arrived: arrivedAt !== null && at - arrivedAt < timing.arrivedMs });
      if (!bringing && read.society !== 'absent') return null;
      return offering() && !bringing && welcome === 'nowhere' ? nowhereLine() : PEOPLE_WORDS.nobodyYet;
    },
    clockOffer,
    offersBringIn: () => clockOffer()?.state === 'offer',
    bringIn,
    building() { if (welcome === 'nowhere') { welcome = 'offer'; changed(); } },
    onChange(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}
