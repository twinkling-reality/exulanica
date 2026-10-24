// Talking in the world (DESIGN's rulings T1 to T8 and N28, WORDS.md): what pops over whom from the
// society's events, how long each pop holds, how a reply keeps the line it answers, how two pops that
// would overlap stack, which lines are heard and which only name their people, where a line said off
// screen sits, and which exchange a followed character is in. It keeps no clock of its own: every call
// is given `now` in milliseconds. contextual-world.ts reads the events while the world plays and draws
// what `shown(now)` returns; talk-words.mjs words it. verify-talk-pops.mjs holds these.
import { byParts, partsText } from './history-words.mjs';
import { chosePop, saidPop } from './talk-words.mjs';

/** How long a pop holds before it fades, and the fade (T4): 67 ms a character, 3.6 s to 9 s. */
export const TALK_HOLD = Object.freeze({ perCharacterMs: 67, leastMs: 3600, mostMs: 9000, outMs: 600 });

/**
 * Following an exchange (T5): how near the other person stands, the ease, the wait after the last pop,
 * and how far from the middle of the view the two heads may sit, as a share of the half width, so
 * their pops stay inside the corners and the card fits on the far side even at 1440 by 900.
 */
export const TALK_FRAMING = Object.freeze({ nearMetres: 15, easeMs: 600, backAfterMs: 2000, safe: 0.4 });

/** The gap between two stacked pops, in reference pixels (T4). */
export const STACK_GAP = 8;

/**
 * How far a line is heard (N28 section 5): a speaker within this of the view has the line over their
 * head; farther off, the line's people are named instead. A speaker the person attends to is heard at
 * any distance (T8).
 */
export const TALK_HEARING = Object.freeze({ metres: 20 });

/** How far over the head a line sits and a name sits, in pixels (N28 sections 4 and 5). */
export const OVER_HEAD = Object.freeze({ speech: 24, name: 16 });

/** The most people named at once (N28 section 5), so the view stays the world's. */
export const NAMES_MOST = 3;

/**
 * How tall someone must stand on screen to be named, in reference pixels (N28 section 5: people the person
 * can see): a figure a few pixels tall far off is not someone seen (the live check, 16 October).
 */
export const NAMED_LEAST_PX = 24;

/**
 * Where a pop's words start across the view (N28, T8): centred over the speaker, but never nearer
 * either edge than `inset`, the edge inset every screen keeps, so a speaker near the edge keeps a whole
 * line on screen. A line wider than the room between the insets starts at the left inset.
 */
export const popLeft = (centreX, width, viewWidth, inset) =>
  Math.max(inset, Math.min(viewWidth - inset - width, centreX - width / 2));

/**
 * The decision contract's kinds of choice that change nothing to see (T11): waiting a minute and carrying on.
 * They never pop; they stay rows in What Teo did and decisions in History.
 */
export const QUIET_KINDS = Object.freeze(['wait', 'carry_on']);

/**
 * The words of the quiet choices, from every version of the decision-action catalog given (the data the
 * choices are worded from), lower case; a word with a placeholder names no single choice and is left out.
 */
export function quietWords(catalogs, kinds = QUIET_KINDS) {
  const words = new Set();
  for (const catalog of catalogs) {
    for (const entry of catalog?.entries ?? []) {
      if (kinds.includes(entry?.kind) && typeof entry.words === 'string' && !entry.words.includes('{')) words.add(entry.words.trim().toLowerCase());
    }
  }
  return words;
}

/** Who may decide a minute whose choice pops (T1): a model, an outside program, a person playing; never a routine. */
const MINDS = new Set(['model', 'external', 'person']);

/** How long `words` hold before they fade (T4). */
export const holdMs = (words, rule = TALK_HOLD) =>
  Math.min(rule.mostMs, Math.max(rule.leastMs, [...String(words ?? '')].length * rule.perCharacterMs));

/**
 * What pops from a page of the society's events, oldest first (T1): every line said, whoever decided
 * it, `{ subjectId, words, said: true, to }` (`to` the person it was said to, or null for everyone
 * near), and every choice a mind made and the world applied that said nothing, `{ ..., said: false,
 * to: null }`. A said event keeps its request under `thing` (society_things.py); an applied decision
 * states who decided as its `origin` (a record made before it did names a model as `model`). A choice
 * whose words are among `quiet` (quietWords) changes nothing to see and does not pop (T11).
 */
export function talkActs(events, quiet = new Set()) {
  const said = new Set(events.filter(event => event.event_kind === 'said').map(event => event.document?.thing?.request_id).filter(Boolean));
  return events.map((event, index) => ({ event, index }))
    .sort((a, b) => (a.event.tick ?? 0) - (b.event.tick ?? 0) || a.index - b.index)
    .flatMap(({ event }) => {
      const document = event.document || {};
      if (event.event_kind === 'said') {
        const thing = document.thing || {};
        if (typeof thing.line !== 'string' || !thing.line.trim()) return [];
        // Who chose the line, where the minute recorded it (T14): a model, a person playing or an outside program.
        const by = typeof thing.decider === 'string' ? Object.freeze({ kind: thing.decider, model: thing.model ?? null }) : null;
        return [{ subjectId: event.subject_id, words: saidPop(thing.line), said: true, to: typeof thing.to === 'string' ? thing.to : null, by }];
      }
      if (event.event_kind !== 'decision_applied' || said.has(document.request_id)) return [];
      if (document.disposition !== undefined && document.disposition !== 'applied') return [];
      if (quiet.has(String(document.chose ?? '').trim().toLowerCase())) return [];
      const mind = document.origin !== undefined ? MINDS.has(document.origin) : Boolean(document.model);
      const words = mind ? chosePop(document.chose) : null;
      return words ? [{ subjectId: event.subject_id, words, said: false, to: null }] : [];
    });
}

/**
 * Who chose a said line, as the scene's plate says it under the name (T14), in History's who-line words (H19):
 * "By Nemotron 3 Super 120B", "By a person playing", "By an outside program", or "By an outside AI agent" where the
 * speaker's outside program is one (`agent`, AG1d 3); null for a line no mind chose. `modelName` names a recorded
 * `{ provider, model_id }`, the model id where it cannot.
 */
export function sceneBy(by, modelName = () => null, agent = false) {
  if (!by) return null;
  const name = by.model ? modelName(by.model) ?? by.model.model_id ?? null : null;
  const parts = byParts({ kind: by.kind === 'external' && agent ? 'agent' : by.kind, model: name ? { name } : null });
  return parts ? partsText(parts) : null;
}

/**
 * The pops of one world: at most one per character (T4). `add` shows an act from `now`; a line said
 * to a person whose said line still shows is a reply, and keeps that line up, dimmed, until the reply
 * fades. `shown` answers the pops still up, oldest first: `{ subjectId,
 * words, said, to, earlier, leaving, serial }`, `leaving` while it fades.
 */
export function createTalk(rule = TALK_HOLD) {
  const pops = new Map();
  let serial = 0;
  const up = (pop, now) => now < pop.until + rule.outMs;
  return {
    add(act, now) {
      const until = now + holdMs(act.words, rule);
      // A reply: a line to someone whose said line still shows and was said to the new speaker, or to
      // everyone near (T4). A line to oneself answers nothing.
      const answered = act.said && act.to && act.to !== act.subjectId ? pops.get(act.to) : null;
      if (answered && answered.said && up(answered, now) && (answered.to === act.subjectId || answered.to === null)) {
        answered.earlier = true;
        answered.until = Math.max(answered.until, until);
      }
      pops.set(act.subjectId, { subjectId: act.subjectId, words: act.words, said: act.said, to: act.to ?? null, earlier: false, until, serial: ++serial });
    },
    clear() { pops.clear(); },
    shown(now) {
      for (const [subjectId, pop] of pops) if (!up(pop, now)) pops.delete(subjectId);
      return [...pops.values()].sort((a, b) => a.serial - b.serial).map(pop => Object.freeze({
        subjectId: pop.subjectId, words: pop.words, said: pop.said, to: pop.to, earlier: pop.earlier,
        leaving: now >= pop.until, serial: pop.serial,
      }));
    },
  };
}

/**
 * Where pops that would overlap sit (T4): each is a box `{ serial, x, y, width, height }` placed over
 * its own speaker; an earlier one that meets a newer one rises until its lower edge is `gap` above
 * the newer one's top, so a pair reads top to bottom, oldest first. `fixed` are boxes that do not move
 * (the looked-at name tag): a pop that meets one rises above it too. Answers each box's top by serial.
 */
export function stackPops(boxes, gap = STACK_GAP, fixed = []) {
  const placed = [...fixed];
  const tops = new Map();
  for (const box of [...boxes].sort((a, b) => b.serial - a.serial)) {
    let top = box.y;
    for (let tries = 0; tries <= placed.length; tries += 1) {
      const meets = placed.find(other => box.x < other.x + other.width && other.x < box.x + box.width && top < other.y + other.height + gap && other.y < top + box.height + gap);
      if (!meets) break;
      top = meets.y - gap - box.height;
    }
    placed.push({ ...box, y: top });
    tops.set(box.serial, top);
  }
  return tops;
}

/**
 * The exchange a followed character is in (T5): the newest pop showing that is a line said to a
 * person, by `subjectId` or to them; answers `{ other, serial }`, the other person's id and that
 * line's serial, or null. A line to everyone near is no exchange.
 */
export function exchangeOf(shown, subjectId) {
  for (let index = shown.length - 1; index >= 0; index -= 1) {
    const pop = shown[index];
    if (!pop.said || !pop.to || pop.to === pop.subjectId) continue;
    if (pop.subjectId === subjectId) return { other: pop.to, serial: pop.serial };
    if (pop.to === subjectId) return { other: pop.subjectId, serial: pop.serial };
  }
  return null;
}

/**
 * Whether following frames an exchange now (T5), as one pure step. `exchange` is exchangeOf's answer;
 * `ended` the serial of the line whose exchange the person's own movement ended, or null; `framed`
 * whether a framing holds; `near` and `seen` of the other person. Answers `{ frame, ended }`: an ended
 * exchange stays ended until no exchange shows or a newer line comes; a framing starts only on a seen
 * person near enough, and holds while they stay near.
 */
export function framingStep({ exchange, ended = null, framed = false, near = false, seen = false }) {
  if (!exchange) return { frame: false, ended: null };
  if (ended !== null && exchange.serial <= ended) return { frame: false, ended };
  return { frame: Boolean(near && (framed || seen)), ended: null };
}

/** The person moved the camera: the exchange showing now stays ended (T5); its serial, or null. */
export const endedBy = exchange => exchange ? exchange.serial : null;

/** The pops up now (T2): none while the world is paused, which also puts away what was showing. */
export function shownWhile(talk, mode, now) {
  if (mode !== 'playing') { talk.clear(); return []; }
  return talk.shown(now);
}

/**
 * How a pop shows (N28, T8, T10): 'over' its speaker's head; at the view's 'edge' for a line said off
 * screen by a speaker the person attends to; 'far', not drawn, its people named instead, for a speaker
 * on screen beyond hearing; 'none' for a line said off screen by anyone else. `onScreen`: the speaker's
 * head is in view and seen; `metres`: how far the speaker is from the view; `chosen`: the chosen or
 * followed character, heard at any distance; `attended`: T8's speakers for a line off screen (the
 * chosen or followed character, a character whose model the open run asks, a speaker whose listener is
 * on screen). On screen only the chosen one is heard from afar: in a run every speaker is one the run
 * asks, so the run's set would never let a far line give way to names (the live check, 16 October).
 */
export function popPlacement({ onScreen, metres, chosen = false, attended, hearing = TALK_HEARING }) {
  if (!onScreen) return attended ? 'edge' : 'none';
  return chosen || metres <= hearing.metres ? 'over' : 'far';
}

/**
 * Where a line said off screen sits (T8): at the side of the view nearest the speaker (`right`: the
 * speaker is to the right of where the camera looks), its words `inset` from that edge; in height where
 * it would sit over the speaker (`overY`, the top it would take there), kept between `top` and
 * `bottom`, or halfway between them for a speaker behind the camera (`overY` null). Answers its top left.
 */
export function edgePlace({ right, overY, width, height, viewWidth, inset, top, bottom }) {
  const x = right ? viewWidth - inset - width : inset;
  const y = overY === null ? top + (bottom - top - height) / 2 : Math.max(top, Math.min(bottom - height, overY));
  return { x, y };
}

/**
 * Names that would overlap become one label centred over them (T10): `boxes` are `{ id, x, y, width, height }`,
 * each label's top left as drawn alone. Answers the groups, each its ids from left to right, a group of one for
 * a name that meets no other; two labels meet when their boxes come within `gap` pixels of each other.
 */
export function nameGroups(boxes, gap = 4) {
  const groups = boxes.map(box => [box]);
  const meet = (a, b) => a.some(one => b.some(other => one.x < other.x + other.width + gap && other.x < one.x + one.width + gap
    && one.y < other.y + other.height + gap && other.y < one.y + one.height + gap));
  for (let merged = true; merged;) {
    merged = false;
    for (let i = 0; i < groups.length && !merged; i += 1) {
      for (let j = i + 1; j < groups.length && !merged; j += 1) {
        if (meet(groups[i], groups[j])) { groups[i] = [...groups[i], ...groups[j]]; groups.splice(j, 1); merged = true; }
      }
    }
  }
  return groups.map(group => group.sort((a, b) => a.x + a.width / 2 - (b.x + b.width / 2)).map(box => box.id));
}

/**
 * Who is named over their head (N28 section 5). `candidates` are `{ id, metres, last }`, each seen on
 * screen: the speaker and listener of a line beyond hearing, and the person chosen last (`last`).
 * `skip` holds whoever has a line showing, carries the looked-at tag, or is chosen now. Answers at most
 * `most` ids: the person chosen last first, then the nearest.
 */
export function namedPeople(candidates, skip, most = NAMES_MOST) {
  const people = new Map();
  for (const one of candidates) {
    if (skip.has(one.id) || !Number.isFinite(one.metres)) continue;
    const known = people.get(one.id);
    people.set(one.id, { id: one.id, metres: Math.min(one.metres, known?.metres ?? Infinity), last: Boolean(one.last || known?.last) });
  }
  return [...people.values()].sort((a, b) => Number(b.last) - Number(a.last) || a.metres - b.metres).slice(0, most).map(one => one.id);
}
