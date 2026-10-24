// History's path (r23, the user's yes on 16 October; DESIGN's R23 build sheet, amended 08:36), from the reads alone
// (pure, checked in verify-history.mjs): how the world began, each moment the characters made (its picture, when in
// the world's time, what happened, the lines said, who decided, who was in it, another model's answer: the same
// as one small line, a different one as a branch), the person's own changes as small dots, the runs as brackets
// over their moments, and Now. Words come from history-words.mjs; where each item sits and which items a view
// draws, from `pathLayout` and `pathView`.

import { timeLeft } from './run-words.mjs';
import {
  answerParts,
  askedAgainParts,
  branchWords,
  byParts,
  changesWords,
  creationPathWords,
  creationWhen,
  dayMark,
  moreLinesWords,
  momentWords,
  personWhen,
  possessive,
  runSpanWords,
  saidWords,
  sameChoiceParts,
  personSpan,
  spanWhen,
  worldWhen,
  youChangeWords,
  youModelParts,
  youPersonalityWords,
} from './history-words.mjs';

/** Lines a card shows; the rest are counted under them and every one is in the opened moment. */
export const CARD_LINES = 2;
/** Why a run ended, said in the opened moment only where it did not end at its own limit of time (H3). */
const ENDED_AT_ITS_TIME = new Set(['session_deadline', 'session_minutes']);

const at = (text) => {
  const value = Date.parse(text);
  return Number.isFinite(value) ? value : null;
};

/** The person's own changes, each { at, words }: build mode's edits, model choices, personalities. */
function changes(reads, names, partsOf) {
  const found = [];
  for (const edit of reads.edits ?? []) {
    const time = at(edit.recorded_at);
    if (time !== null) found.push({ at: time, words: youChangeWords(partsOf(edit, reads.edits)) });
  }
  // A model given, changed or taken away; a person's play and an outside program are not changes of model, and a
  // choice of the model the same characters already have changes nothing (F12b), oldest first.
  const held = new Map();
  for (const choice of [...(reads.models ?? [])].sort((a, b) => a.choice_seq - b.choice_seq)) {
    const time = at(choice.recorded_at);
    if (time === null || choice.ended || !['model', 'routine'].includes(choice.decider?.kind)) continue;
    const who = [...choice.subjects].sort().join();
    const what = choice.decider.kind === 'model' ? `model:${choice.model?.model_id ?? choice.model?.name ?? ''}` : 'routine';
    const same = held.get(who) === what;
    held.set(who, what);
    if (same) continue;
    const whose = choice.subjects.length === 1 ? `${possessive(names.subject(choice.subjects[0]))} model` : `${choice.subjects.length} characters' models`;
    found.push({ at: time, words: youModelParts(whose, choice.decider?.kind === 'model' ? choice.model?.name ?? null : null) });
  }
  // Personalities: the first record of a being wrote one, a record stating nothing cleared it.
  const seen = new Set();
  for (const record of [...(reads.characters ?? [])].sort((a, b) => a.revision - b.revision)) {
    const states = record.states_name || record.states_about;
    const change = !states ? 'cleared' : seen.has(record.placed_id) ? 'changed' : 'wrote';
    seen.add(record.placed_id);
    const time = at(record.written_at);
    if (time !== null) found.push({ at: time, words: youPersonalityWords(names.placed(record.placed_id), change) });
  }
  return found;
}

const AUTHORED = 'authored:';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:/i;

/**
 * The placed thing a going's (or an answer's) target names, by its object id, or null. A society's target is
 * "authored:<version_id>:<object_id>:<affordance>" (a placed thing's use; the object id may itself hold ':') or a
 * navigation destination with no placed thing behind it, which has no name and is worded by its activity.
 */
export function targetObject(targetId) {
  if (typeof targetId !== 'string' || !targetId.startsWith(AUTHORED)) return null;
  const rest = targetId.slice(AUTHORED.length);
  if (!UUID.test(rest)) return null;
  const use = rest.slice(37);
  const last = use.lastIndexOf(':');
  return last > 0 ? use.slice(0, last) : null;
}

/** Answers whose target is a thing in hand rather than a place to go. */
const HANDS = new Set(['picked_up', 'put_down', 'gave', 'took']);

/**
 * What another model's answer would have done, in JOURNEY's catalog forms, said of the one whose decision it
 * answers (`by`; on a going two people made together, each person's own), else of the moment's first subject.
 */
function answerWords(branch, actor, names) {
  const named = branch.target ? names.target(branch.target) : null;
  return branchWords({
    kind: branch.kind,
    to: HANDS.has(branch.kind) ? null : named,
    activity: branch.target?.activity ?? null,
    thing: HANDS.has(branch.kind) ? named : null,
    withName: branch.with ? names.subject(branch.with) : null,
    line: branch.said?.line ?? null,
  }, branch.by ? names.subject(branch.by) : actor);
}

/** Whether a decider is a decision: a model's, a person playing's or an outside program's, never the routine's. */
const decided = (decider) => Boolean(decider?.kind) && decider.kind !== 'routine';

/**
 * How a moment is titled: its kind, its people in the title's order and the line that says whether it asks. A meeting
 * a decision opened is titled as that decision (DESIGN, 24 October): where a decision said its line, the speaker
 * first, "Teo spoke to Ines" (or "asked"); where a decision to talk opened it, "Teo talked with Ines". "met" stays
 * only where no decision opened it.
 */
function titled(moment) {
  const subjects = moment.subjects ?? [];
  if (moment.kind === 'met' || (moment.kind === 'talked' && !decided(moment.decider))) {
    const line = (moment.said ?? []).find((said) => decided(said.decider) && subjects.includes(said.by));
    if (line) return { kind: 'spoke', subjects: [line.by, ...subjects.filter((id) => id !== line.by)], firstLine: line.line };
    if (moment.kind === 'met' && decided(moment.decider)) return { kind: 'talked', subjects, firstLine: moment.said?.[0]?.line ?? null };
  }
  return { kind: moment.kind, subjects, firstLine: moment.said?.[0]?.line ?? null };
}

/** A moment's people in its title's order, the decider first: the order its card's portraits follow (DESIGN). */
export const titledSubjects = (moment) => titled(moment).subjects;

/**
 * A moment's title as History says it, from the moments read's moment and the names the page holds (`names` as
 * historyPath takes them): "Teo met Ines at the bench". Other pages that title a moment read it here, so a moment
 * reads alike on History, the day page and the decision page (`titled`).
 */
export function momentTitle(moment, names) {
  const { kind, subjects: [first, ...rest], firstLine } = titled(moment);
  return momentWords({
    kind,
    place: moment.place ? names.place(moment.place) : null,
    to: moment.target ? names.target(moment.target) : null,
    activity: moment.target?.activity ?? null,
    thing: moment.with?.thing ? names.thing(moment.with.thing) : null,
    firstLine,
  }, first ? names.subject(first) : '', rest.map((id) => names.subject(id)));
}

/** A moment, as the path and its opened view show it (the R1 moments read's shape). */
function momentItem(moment, names, clock) {
  const subjects = titledSubjects(moment);
  const first = subjects[0];
  const actor = first ? names.subject(first) : '';
  const lines = (moment.said ?? []).map((line) => ({
    tick: line.tick, subject: line.by, request: line.request_id ?? null,
    words: saidWords((names.speaker ?? names.subject)(line.by), line.line),
    quote: `\u201c${line.line}\u201d`,
    by: byParts(line.decider),
  }));
  const branches = [...(moment.branches ?? [])];
  const newest = (list) => [...list].sort((a, b) => (at(b.asked_at) ?? 0) - (at(a.asked_at) ?? 0))[0];
  const differing = newest(branches.filter((branch) => branch.same_choice !== true));
  const same = newest(branches.filter((branch) => branch.same_choice === true));
  return {
    id: `moment:${moment.moment_id}`, kind: 'moment', moment_id: moment.moment_id, request: moment.request_id ?? null, at: at(moment.at), tick: moment.tick,
    day: clock(moment.tick)?.day ?? null,
    when: worldWhen(clock(moment.tick)),
    words: momentTitle(moment, names),
    lines,
    shown: lines.slice(0, CARD_LINES).map((line) => line.words),
    more: lines.length > CARD_LINES ? moreLinesWords(lines.length - CARD_LINES) : null,
    // Who chose it, else who chose the first of its lines (H19): a model's words are never shown unnamed.
    by: byParts(moment.decider) ?? lines.find((line) => line.by)?.by ?? null,
    same: same ? sameChoiceParts(same.model?.name ?? '') : null,
    branch: differing ? { head: askedAgainParts(differing.model?.name ?? ''), outcome: answerWords(differing, actor, names) } : null,
    answers: branches.map((branch) => answerParts(branch.model?.name ?? '', branch.same_choice === true, answerWords(branch, actor, names))),
    // Its people as its title names them, the decider first: its portraits' order.
    subjects,
    session: moment.session_id ?? null,
    picture: moment.picture ?? null,
    // What its picture is drawn from where none is kept (MOTION's renderMomentPicture).
    scene: moment.scene ?? null,
    decided: moment.decider?.kind ?? 'routine',
  };
}

/**
 * Everything on the path, oldest first, ordered by the person's own time: `items` (creation, moment, change,
 * day), `spans` (a run over its first to last moment, with the opened moment's small print) and `now`.
 *
 * `reads`: `creation` ({at, readyWorld, blank, sentence, picture}), `edits`, `models`, `characters`, `runs`
 * (each {session_id, start_tick, end_tick, spent, ends_by, closed: {reason, words} or null, world_minutes}),
 * `moments` (the moments read's list), `nowTick`. `names`: subject(id), placed(id), thing(thingId), place({placed_id,
 * thing_id}) and target({target_id, activity}), each a name or null. `partsOf(edit, edits)`: build mode's change
 * parts (build-words.mjs's changeParts). `clock(tick)`: {hhmm, day} or null. `now`: the reader's time in ms.
 */
export function historyPath(reads, names, partsOf, clock, now = Date.now()) {
  const timed = [];
  const creation = reads.creation;
  if (creation && at(creation.at) !== null) {
    const time = at(creation.at);
    timed.push({
      id: 'creation', kind: 'creation', at: time, when: creationWhen(time, now),
      words: creationPathWords(creation.readyWorld ?? null, creation.blank === true),
      quote: creation.readyWorld || creation.blank ? null : creation.sentence || null,
      picture: creation.picture ?? null,
    });
  }
  for (const moment of reads.moments ?? []) {
    if (at(moment.at) !== null) timed.push(momentItem(moment, names, clock));
  }
  for (const change of changes(reads, names, partsOf)) timed.push({ kind: 'change-one', ...change });
  timed.sort((a, b) => a.at - b.at || (a.kind === 'creation' ? -1 : b.kind === 'creation' ? 1 : 0));

  // The person's changes between the same two moments become one dot, so labels never overlap; a grouped dot keeps
  // each change, oldest first, for the list it opens (H15). A single change's words are the whole of it.
  const items = [];
  let lastDay = null;
  for (const entry of timed) {
    if (entry.kind === 'change-one') {
      const previous = items[items.length - 1];
      const row = { when: personSpan(entry.at, entry.at, now), words: entry.words };
      if (previous?.kind === 'change' && previous.merging) {
        previous.count += 1;
        previous.words = changesWords(previous.count);
        previous.span = personSpan(previous.first, entry.at, now);
        previous.changes.push(row);
      } else {
        // On the line a change carries no time: none records the world's time it was made, and the wall clock never
        // stands among world times (F12b). Its opened list keeps its span and each change's own time.
        items.push({ id: `change:${entry.at}:${items.length}`, kind: 'change', merging: true, count: 1, first: entry.at, at: entry.at, when: null, span: row.when, words: entry.words, changes: [row] });
      }
      continue;
    }
    if (entry.kind === 'moment' && entry.day !== null) {
      if (lastDay !== null && entry.day !== lastDay) items.push({ id: `day:${entry.day}:${items.length}`, kind: 'day', at: entry.at, words: dayMark(entry.day) });
      lastDay = entry.day;
    }
    items.push(entry);
  }
  for (const item of items) {
    if (item.kind === 'change' && item.count < 2) {
      delete item.changes;
      delete item.span;
    }
    delete item.merging;
    delete item.count;
    delete item.first;
  }

  const spans = [];
  for (const run of reads.runs ?? []) {
    const inside = items.filter((item) => item.kind === 'moment' && item.session === run.session_id);
    if (!inside.length) continue;
    // Whose models were deciding: the characters a model decided for, in the order they first acted.
    const deciding = [...new Set(inside.filter((item) => item.decided === 'model' && item.subjects.length).map((item) => item.subjects[0]))];
    const running = !run.closed;
    const facts = {
      names: deciding.map((id) => names.subject(id)),
      from: clock(run.start_tick)?.hhmm ?? null,
      to: running ? null : clock(run.end_tick)?.hhmm ?? null,
      worldMinutes: Number.isSafeInteger(run.world_minutes) ? run.world_minutes : null,
      running, left: running && run.ends_by ? timeLeft(run.ends_by, now) : null,
    };
    const early = run.closed && !ENDED_AT_ITS_TIME.has(run.closed.reason) ? run.closed.words ?? null : null;
    spans.push({
      id: `run:${run.session_id}`, session: run.session_id, first: inside[0].id, last: inside[inside.length - 1].id,
      words: runSpanWords({ ...facts, spent: run.spent }),
      small: runSpanWords({ ...facts, spent: null }),
      ended: early,
    });
  }
  return { items, spans, now: { when: worldWhen(clock(reads.nowTick)) } };
}

/**
 * The page's sizes at 1920 by 1080 and at 1440 by 900 (sheet sections 3 to 12 and "1440 x 900"). `band`, from the
 * page's bottom: the key row's caps and the 24px of it nothing on the story line enters (H15). At 1440 the story line
 * stands 32px higher than r23 drew it (H15), so a branch under it clears that band; the bracket stays.
 */
export const LAYOUTS = Object.freeze({
  wide: Object.freeze({
    band: 85, margin: 120, lineY: 560, gap: 420, card: 300, picture: 170, orb: 52, bracketY: 344, nowFromRight: 120,
    branchY: 750, branchCard: 260, branchPicture: 146, branchWords: 260, branchMeet: 67, branchUnder: 16,
    opened: Object.freeze({ left: 120, top: 260, width: 960, height: 540, orb: 64, column: 1130, columnRight: 1800 }),
    // A grouped dot's changes, opened (H15): `foot` from the page's bottom, 40 above the key row (40 up, caps 21 tall).
    changes: Object.freeze({ left: 120, top: 260, width: 680, foot: 101 }),
  }),
  narrow: Object.freeze({
    band: 77, margin: 80, lineY: 438, gap: 360, card: 260, picture: 148, orb: 46, bracketY: 254, nowFromRight: 120,
    branchY: 608, branchCard: 220, branchPicture: 124, branchWords: 300, branchMeet: 57, branchUnder: 16,
    opened: Object.freeze({ left: 80, top: 240, width: 720, height: 405, orb: 56, column: 850, columnRight: 1360 }),
    changes: Object.freeze({ left: 80, top: 240, width: 600, foot: 93 }),
  }),
});

/** How far past its picture a card's words run: the card's box is 30 wider, its words 6 short of that edge. */
const CARD_WORDS = 24;
/** A change's words: a block 150 wide, its left edge 70 left of the dot, at least 16 clear of the picture before. */
const CHANGE_LEFT = 70, CHANGE_WIDTH = 150, CHANGE_CLEAR = 16;
/** At least this much line between the last card and Now (sheet section 3). */
const BEFORE_NOW = 60;

/**
 * Where each item sits on the line, in the layout's pixels before any slide, and what it draws: `x` a card's
 * left edge (its dot), a dot's centre, a day mark's centre; `extent` [left, right] of everything it draws (a
 * card's picture and words and its branch, a change's words block); `nowAt` the least place for Now. A dot sits
 * 30 before where the next card would be, and the card after it 90 after the dot (r23: creation 120, a change
 * 510, a moment 600).
 */
export function pathLayout(items, layout) {
  const x = new Map(), extent = new Map();
  let nextCard = layout.margin;
  let lastCard = null;
  let afterDot = null;
  for (const item of items) {
    if (item.kind === 'creation' || item.kind === 'moment') {
      const left = afterDot ?? nextCard;
      x.set(item.id, left);
      const branch = item.branch ? left + 32 + Math.max(layout.branchCard, layout.branchWords) : 0;
      extent.set(item.id, [left, Math.max(left + layout.card + CARD_WORDS, branch)]);
      lastCard = left;
      nextCard = left + layout.gap;
      afterDot = null;
    } else if (item.kind === 'change') {
      const dot = afterDot !== null ? afterDot
        : lastCard === null ? layout.margin + CHANGE_LEFT
          : Math.max(nextCard - 30, lastCard + layout.card + CHANGE_CLEAR + CHANGE_LEFT);
      x.set(item.id, dot);
      extent.set(item.id, [dot - CHANGE_LEFT, dot - CHANGE_LEFT + CHANGE_WIDTH]);
      afterDot = dot + 90;
    } else if (item.kind === 'day') {
      const centre = (afterDot ?? nextCard) - 45;
      x.set(item.id, centre);
      extent.set(item.id, [centre - 24, centre + 24]);
    }
  }
  const nowAt = Math.max(afterDot ?? 0, lastCard === null ? layout.margin + layout.card + BEFORE_NOW : lastCard + layout.card + BEFORE_NOW);
  return { x, extent, nowAt };
}

/**
 * What one view of the path draws (sheet section 3), for a window `width` wide: `offset` (how far the line has
 * slid, never right of its start), `drawn` (the ids of the items wholly inside the view: no card, picture or word
 * is ever cut by the window's edge), `now` (Now's place on screen while the newest end is in view, else null) and
 * the line's ends `from` and `to` (to the window's edge where more lies beyond).
 *
 * The page opens at the newest end. A choice wholly in view moves nothing; else the line slides by whole items,
 * the smallest slide that brings the chosen card whole in, after which the first item drawn starts exactly at the
 * margin. The first moment chosen slides the line back to its start where that card stays whole there.
 */
export function pathView(items, placed, layout, width, chosen = null, previous = null) {
  const order = items.filter((item) => placed.extent.has(item.id));
  const ext = (id) => placed.extent.get(id);
  const right = width - layout.margin;
  const nowPlace = width - layout.nowFromRight;
  const whole = (id, offset) => ext(id)[0] + offset >= layout.margin && ext(id)[1] + offset <= right;
  // A view starts at a card or a change, never at a day's mark.
  const anchors = order.filter((item) => item.kind !== 'day');
  // The newest end: the fewest items from the start left out so the rest and Now fit, the first at the margin.
  let newest = 0;
  for (const item of anchors) {
    const offset = layout.margin - ext(item.id)[0];
    newest = Math.min(0, offset);
    if (placed.nowAt + offset <= nowPlace) break;
  }
  if (!order.length || placed.nowAt <= nowPlace) newest = 0;
  const firstWholeFrom = (offset) => anchors.find((item) => ext(item.id)[0] + offset >= layout.margin);
  let offset = previous ?? newest;
  if (chosen && placed.extent.has(chosen)) {
    const firstMoment = order.find((item) => item.kind === 'moment');
    if (firstMoment?.id === chosen && whole(chosen, 0)) offset = 0;
    else if (!whole(chosen, offset)) {
      const [left, end] = ext(chosen);
      if (left + offset < layout.margin) offset = layout.margin - left;
      else {
        offset = right - end;
        const first = firstWholeFrom(offset);
        if (first) offset = layout.margin - ext(first.id)[0];
      }
    }
  }
  offset = Math.min(0, Math.max(newest, offset));
  const drawn = new Set(order.filter((item) => whole(item.id, offset)).map((item) => item.id));
  const now = placed.nowAt + offset <= nowPlace ? nowPlace : null;
  const firstDrawn = order.find((item) => drawn.has(item.id));
  const hiddenBefore = order.some((item) => !drawn.has(item.id) && firstDrawn && ext(item.id)[0] < ext(firstDrawn.id)[0]);
  const start = order.find((item) => item.kind === 'creation' || item.kind === 'moment');
  const from = hiddenBefore ? 0 : start ? placed.x.get(start.id) + offset : layout.margin;
  return { offset, drawn, now, from, to: now ?? width };
}

/** A run's words left at the page's margin keep at least this far from another run's words, or are left out (H16). */
const RUN_WORDS_CLEAR = 16;

/**
 * Where each run's bracket is drawn in a view (sheet section 8, amended by H16): a line, as the story line is, over the
 * part of the run in view, from its first moment's dot to its last moment's card edge, or to the window's edge where
 * the run goes on past it, with no leg at a cut end. Its words stand above its left end where that end is in view;
 * where the run began before the view, at the page's margin, and left out there if they would meet another run's
 * words. A run with no moment in view draws nothing. `wordsWidth(id)` is a run's words' drawn width. Places are the
 * track's own (before the view's slide); `words` is the words' left edge, or null.
 */
export function runBrackets(spans, items, placed, view, layout, width, wordsWidth) {
  const made = [];
  for (const span of spans) {
    if (!items.some((item) => item.kind === 'moment' && item.session === span.session && view.drawn.has(item.id))) continue;
    const startsIn = view.drawn.has(span.first), endsIn = view.drawn.has(span.last);
    const from = startsIn ? placed.x.get(span.first) : -view.offset;
    const to = endsIn ? placed.x.get(span.last) + layout.card : width - view.offset;
    made.push({ id: span.id, from, to, legs: [startsIn, endsIn], words: startsIn ? from : layout.margin - view.offset });
  }
  const meets = (one, other) => other.words !== null && other.words < one.words + wordsWidth(one.id) + RUN_WORDS_CLEAR
    && one.words < other.words + wordsWidth(other.id) + RUN_WORDS_CLEAR;
  for (const one of made) {
    if (!one.legs[0] && made.some((other) => other !== one && meets(one, other))) one.words = null;
  }
  return made;
}

/**
 * Where the story line breaks for moments not yet read (H17, sheet section 3 amended): while the moments read says more
 * lie before the oldest moment held (`more`), the line is broken midway between that moment's dot and the item drawn
 * before it (a card's picture end, or a change's dot), in the track's places. Where nothing is drawn before it, 'edge':
 * the line runs on to the window's left edge. Null where nothing lies unread, or the oldest moment is out of view.
 */
export function earlierBreak(items, placed, view, layout, more) {
  if (!more) return null;
  const at = items.findIndex((item) => item.kind === 'moment');
  if (at < 0 || !view.drawn.has(items[at].id)) return null;
  const before = items.slice(0, at).reverse().find((item) => view.drawn.has(item.id));
  if (!before) return 'edge';
  const end = placed.x.get(before.id) + (before.kind === 'creation' ? layout.card : 0);
  return Math.round((end + placed.x.get(items[at].id)) / 2);
}

/**
 * The opened changes' window (H15, sheet section 7): a list longer than the column moves a row at a time. `rows` are
 * each row's [top, bottom] in the list, `height` what the column has room for; `first` the row asked to stand at its
 * top, held where the last row ends at the foot and never past it. Answers that row, how far the list is moved, the
 * height it shows (ending on a whole row, never a time without its sentence; null before it is laid out), and
 * whether rows lie before it or past its foot (where [↑] [↓] Earlier, later and the foot's fade are shown).
 */
export function rowsWindow(rows, height, first = 0) {
  if (!rows.length || !(height > 0)) return { first: 0, scroll: 0, height: null, earlier: false, later: false };
  const start = rows[0][0], end = rows[rows.length - 1][1];
  let most = 0;
  while (most < rows.length - 1 && end - rows[most][0] > height) most += 1;
  const at = Math.min(most, Math.max(0, first));
  let last = at;
  while (last < rows.length - 1 && rows[last + 1][1] - rows[at][0] <= height) last += 1;
  return { first: at, scroll: rows[at][0] - start, height: rows[last][1] - rows[at][0], earlier: at > 0, later: last < rows.length - 1 };
}
