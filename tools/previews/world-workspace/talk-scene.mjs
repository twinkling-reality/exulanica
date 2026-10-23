// Talking while following a conversation (DESIGN's ruling T9, frame r24): when the scene shows, which
// lines it holds (the line said now and the line before it) and who is speaking. It keeps no clock of its
// own: every call is given `now` in milliseconds. contextual-world.ts feeds it the lines the world's
// talk feed reads and draws what `shown` answers with world-ui-talk.ts; talk-words.mjs words it.
// verify-talk-scene.mjs holds these.

/**
 * The scene's figures: how long it stays after the followed character's conversation stops showing
 * (T5's wait before the camera eases back), and how many lines it holds (the line now and the one
 * before it).
 */
export const TALK_SCENE = Object.freeze({ afterMs: 2000, lines: 2 });

/**
 * One followed character's scene. `follow(id, shown)` names whom the person follows (null when
 * following stops), starting a scene of their own from the lines by or to them still showing (`shown`,
 * talk-pops.mjs shown(), oldest first); `add(act)` keeps a line said by them or to them (a said act of
 * talk-pops.mjs talkActs: `{ subjectId, words, said, to }`); `shown(now, exchange)` answers
 * `{ showing, now, before }`: the scene shows while `exchange` (talk-pops.mjs exchangeOf for the
 * followed character) is not null and for `afterMs` once it is, and holds the newest line (`now`) and
 * the one before it (`before`), each `{ speaker, to, words }`; when it stops showing, its lines go.
 */
export function createScene(rule = TALK_SCENE) {
  let followed = null, lines = [], quietSince = null;
  const keep = act => {
    if (!followed || !act.said || (act.subjectId !== followed && act.to !== followed)) return;
    // Who chose it rides with the line where the act says (T14), for the plate.
    lines = [...lines, Object.freeze({ speaker: act.subjectId, to: act.to ?? null, words: act.words, ...(act.by ? { by: act.by } : {}) })].slice(-rule.lines);
  };
  return {
    follow(id, shown = []) {
      if ((id ?? null) === followed) return;
      followed = id ?? null; lines = []; quietSince = null;
      for (const pop of shown) keep(pop);
    },
    add: keep,
    shown(now, exchange) {
      if (!followed) return { showing: false, now: null, before: null };
      if (exchange) quietSince = null;
      else if (lines.length && quietSince === null) quietSince = now;
      const showing = Boolean(lines.length) && (Boolean(exchange) || now - quietSince < rule.afterMs);
      if (!showing) { lines = []; quietSince = null; return { showing: false, now: null, before: null }; }
      return { showing: true, now: lines[lines.length - 1], before: lines.length > 1 ? lines[lines.length - 2] : null };
    },
  };
}

/** Where the speaking dot sits over the speaker's head (r24): this many pixels above it. */
export const SPEAKING_ABOVE = 18;

/** The moment kinds a conversation is told by (R1's moments: a meeting, talking, speaking to someone or to all). */
const SPOKEN = new Set(['met', 'talked', 'spoke', 'spoke_to_all']);
/** The kinds that tell where they went on from it. */
const ONWARD = new Set(['went', 'followed', 'left']);

/**
 * What the scene's top line tells (T9): from a version's moments (R1's read, oldest first), the newest
 * moment of the conversation (spoken, with `followed` among its people, and `other` too where known),
 * and the first moment after it that tells one of the two going on from it ("Ines and Teo went to the
 * market"). Answers at most two moments, oldest first; none until the conversation has a moment.
 */
export function toldMoments(moments, followed, other = null) {
  const list = Array.isArray(moments) ? moments : [];
  const has = (moment, id) => Array.isArray(moment?.subjects) && moment.subjects.includes(id);
  let at = -1;
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const moment = list[index];
    if (SPOKEN.has(moment?.kind) && has(moment, followed) && (!other || has(moment, other) || moment.kind === 'spoke_to_all')) { at = index; break; }
  }
  if (at < 0) return [];
  const onward = list.slice(at + 1).find(moment => ONWARD.has(moment?.kind) && (has(moment, followed) || (other && has(moment, other))));
  return onward ? [list[at], onward] : [list[at]];
}
