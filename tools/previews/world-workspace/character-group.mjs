// A chosen character's group beside them in the world (DESIGN's J30, the r05 picture;
// BUILD-SHEETS-CHARACTER-TALKING-BUILDING.md section 1): what it says, from the reads the page holds, and where
// it stands. Pure: the reads come in as data and the words from character-words.mjs; character-group.ts draws
// the answer. verify-character-group.mjs holds it.
import { ANOTHER_MODEL, CHARACTER_WORDS, GROUP_WORDS, decidesPrint, declaredParts, makerLine, modelsDecide, modelsNamed, overLine, quoted, readingRecord, saidUnder } from './character-words.mjs';
import { RUN_WORDS, atMost, runFor, runRefusalWords } from './run-words.mjs';
import { dayWord } from './talk-words.mjs';
import { worldTime } from './world-clock.mjs';

/**
 * The group's figures, in reference pixels at 1920 by 1080 (scaled by the page's --ui-scale): the gap from
 * the person's on-screen edge to the group's words, the leader's elbow and end before the words, the name
 * line's middle below the group's top, the inset the group keeps from the screen's sides, and the bands it
 * keeps clear of at the top and bottom, where the world screen's pills and keys sit (32 in, 40 tall, then
 * the shade's own 24 and a gap of 16); and the least room it leaves under itself where it is taller than the room
 * between those bands (a short window): its whole height then shows that far above the bottom.
 */
export const GROUP_LAYOUT = Object.freeze({ gap: 100, elbow: 56, end: 36, nameMiddle: 24, inset: 32, top: 112, bottom: 112, least: 24 });

/**
 * How many said events a page of the events read holds, how many pages back the last line is looked for, and
 * how often it is read again while the character stays chosen, in ms.
 */
export const SAID_READ = Object.freeze({ limit: 256, pages: 4, every: 3000 });

const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;

/**
 * The last line a character said, from the society's said events (newest first, as the events read serves
 * them): { line, to, tick }, `to` the id it was said to or null for everyone near; null when the events hold
 * none of theirs.
 */
export function lastSaid(events, subjectId) {
  for (const event of events ?? []) {
    if (event?.event_kind !== 'said' || event.subject_id !== subjectId) continue;
    const thing = event.document?.thing ?? {};
    const line = plain(thing.line);
    if (!line) continue;
    return Object.freeze({ line, to: typeof thing.to === 'string' && thing.to ? thing.to : null, tick: Number.isSafeInteger(event.tick) ? event.tick : null });
  }
  return null;
}

/**
 * Reads back through the said events until the character's last line is found or `pages` pages are read.
 * `readPage(before)` answers one page ({ events, next }); returns lastSaid's answer, or null.
 */
export async function readLastSaid(readPage, subjectId, { pages = SAID_READ.pages } = {}) {
  let before = null;
  for (let page = 0; page < pages; page += 1) {
    const read = await readPage(before);
    const found = lastSaid(read?.events, subjectId);
    if (found || !read?.next) return found;
    before = read.next;
  }
  return null;
}

/**
 * Keeps the last line the chosen character said, read again every `every` ms while they stay chosen.
 * `readPage(before)` reads one page of said events. `of(subjectId, now)` answers what is known (lastSaid's
 * answer, or null) and starts a read when the character is newly chosen or the last read is `every` old; a
 * read for someone no longer chosen is dropped. `onRead` is called when a read changes the answer.
 */
export function keepLastSaid({ readPage, every = SAID_READ.every, pages = SAID_READ.pages, onRead = () => {} }) {
  let subject = null, known = null, readAt = -Infinity, reading = false;
  return {
    of(subjectId, now) {
      if (subjectId !== subject) { subject = subjectId; known = null; readAt = -Infinity; }
      if (subjectId !== null && !reading && now - readAt >= every) {
        readAt = now; reading = true;
        const asking = subjectId;
        readLastSaid(readPage, asking, { pages }).then((found) => {
          if (subject !== asking || JSON.stringify(found) === JSON.stringify(known)) return;
          known = found;
          onRead();
        }, () => {}).finally(() => { reading = false; });
      }
      return known;
    },
  };
}

/**
 * Who decides for a character now, for the small print: `decider` as the page's view names it (T7: 'person' while a
 * person plays them, 'external' for an outside program under a door grant, else null), then their model, else their
 * routine.
 */
export function deciderOf({ decider = null, model = null }) {
  if (decider === 'person' || decider === 'external' || decider === 'agent') return decider;
  return plain(model) ? 'model' : 'routine';
}

/**
 * What the group says (J30), top to bottom: the name, what they are doing, the last line said and under it
 * to whom and when, the key rows that work now, and who decides as small print. `state`:
 * - `who` (called()'s), `doing` (the society's activity words, or null);
 * - `said` (lastSaid's answer, or null), `toWho` (called()'s for its listener, or null), `startMinute` (the
 *   society clock's first minute, null where it keeps none);
 * - `decider` (deciderOf's: 'person', 'external', 'agent', 'model' or 'routine'), `model` (the model's served name, or null), `connected` (a model can be asked
 *   here), `assignable` (this page may choose their model), `running` (a run is on), `left` (its time left), `spent` (what
 *   their model has spent in it, runSpentWords's, or null);
 * - `following` (V follows them now); `reading` while their record is still read, when the group holds their
 *   name and that it is reading, and no keys yet;
 * - `declared` (an outside AI agent's own words about itself, its door entry's), drawn under the print (AG1d 2).
 * Each row: { action, key, word, shortcut }. Run only where their model can be asked here (J2); while a run
 * is on, Stop; without a model, Choose only where this page may choose one.
 */
export function groupContent({ who, doing = null, said = null, toWho = null, startMinute = null, decider = 'routine', model = null,
  connected = true, assignable = false, running = false, left = null, spent = null, following = false, reading = false, declared = null }) {
  if (reading) return Object.freeze({ name: who.title, doing: readingRecord(who), said: null, note: null, rows: Object.freeze([]), print: null, refused: false, declared: null });
  const hhmm = said && said.tick !== null && Number.isSafeInteger(startMinute) ? worldTime(said.tick, startMinute)?.hhmm ?? null : null;
  const spoken = said ? Object.freeze({ line: quoted(said.line), under: saidUnder({ to: said.to ? toWho : null, hhmm }) }) : null;
  const rows = [{ action: 'details', key: 'Enter', word: dayWord(who), shortcut: 'Enter' }];
  const decided = decider === 'model' && plain(model);
  if (running && decided) rows.push({ action: 'stop', key: 'R', word: GROUP_WORDS.stop(who), shortcut: 'R' });
  else if (decided && connected) rows.push({ action: 'run', key: 'R', word: GROUP_WORDS.decide(who), shortcut: 'R' });
  else if (decider === 'routine' && assignable) rows.push({ action: 'model', key: 'M', word: GROUP_WORDS.choose(who), shortcut: 'M' });
  rows.push({ action: 'follow', key: 'V', word: following ? GROUP_WORDS.stopFollowing() : GROUP_WORDS.follow(who), shortcut: 'V' });
  return Object.freeze({
    name: who.title,
    doing: plain(doing),
    said: spoken,
    note: null,
    rows: Object.freeze(rows.map(row => Object.freeze(row))),
    print: decidesPrint(who, { decider, model, left: running && decided ? left : null, spent: running && decided ? spent : null }),
    refused: false,
    declared: decider === 'agent' ? declaredParts(declared) : null,
  });
}

/**
 * The Run question (r08, R-RUN-BUILD-SHEET section 1): R turns the same group, in place, into the question. Top to
 * bottom: the name, "Run for 10 minutes", whose models the run asks, each person with their own (J28, F9: `askers`,
 * called()'s with the chosen character first, `models` their models' names in the same order), the rows "[Enter] Run"
 * and, where another model is offered and this page may choose one, "[M] Choose another model", then the cap as small
 * print. A refusal (`refusal`, the server's code) takes the small print's place in its own
 * sentence and dims Run, which still answers its key; `busy` while the start is asked, when Run does nothing.
 */
export function questionGroup({ who, askers = [who], models = [], limits, refusal = null, busy = false, anotherModel = false, free = false }) {
  const rows = [{ action: 'run', key: 'Enter', word: RUN_WORDS.run, shortcut: 'Enter', disabled: busy }];
  if (anotherModel) rows.push({ action: 'model', key: 'M', word: ANOTHER_MODEL, shortcut: 'M' });
  return Object.freeze({
    name: who.title,
    doing: runFor(limits),
    said: null,
    note: modelsDecide(askers.length ? askers : [who], { models }),
    rows: Object.freeze(rows.map(row => Object.freeze(row))),
    // A run whose every model is on this computer costs nothing: it says so in place of its cap (A2).
    print: refusal ? runRefusalWords(refusal, modelsNamed(models)) : free ? CHARACTER_WORDS.freeHere : atMost(limits, true),
    refused: Boolean(refusal),
  });
}

/**
 * Where the group stands (J30): beside the person, its words `gap` past their on-screen edge, its middle level
 * with their head, kept inside the screen and clear of the top and bottom bands; on the left where the right has no room (the leader mirrors),
 * or on `prefer`'s side where it fits there (the talking scene keeps a pair's groups apart).
 * `head` is the top of their head on screen, `bounds` their on-screen box ({ left, right }), `size` the
 * group's ({ width, height }), `viewport` the screen's, `scale` the page's --ui-scale. Returns the group's
 * top left, its side, and the leader: from the head, up or down to an elbow at the name line, then across
 * to just short of the words.
 */
export function groupPlace({ head, bounds, size, viewport, scale = 1, layout = GROUP_LAYOUT, prefer = null }) {
  const gap = layout.gap * scale, inset = layout.inset * scale;
  const fitsRight = bounds.right + gap + size.width <= viewport.width - inset;
  const fitsLeft = bounds.left - gap - size.width >= inset;
  const side = prefer === 'left' && fitsLeft ? 'left' : prefer === 'right' && fitsRight ? 'right' : fitsRight || !fitsLeft ? 'right' : 'left';
  const wanted = side === 'right' ? bounds.right + gap : bounds.left - gap - size.width;
  const x = Math.max(inset, Math.min(viewport.width - inset - size.width, wanted));
  const top = layout.top * scale, bottom = layout.bottom * scale;
  const banded = Math.max(top, Math.min(viewport.height - bottom - size.height, head.y - size.height / 2));
  const y = withinHeight(banded, size, viewport, scale, layout);
  const towards = side === 'right' ? 1 : -1;
  const edge = side === 'right' ? x : x + size.width;
  const nameY = y + layout.nameMiddle * scale;
  const leader = Object.freeze({
    from: Object.freeze({ x: head.x, y: head.y }),
    elbow: Object.freeze({ x: edge - towards * layout.elbow * scale, y: nameY }),
    to: Object.freeze({ x: edge - towards * layout.end * scale, y: nameY }),
  });
  return Object.freeze({ x, y, side, leader });
}

/**
 * Where a group that holds its model list or Run question stands while its person is out of view (P7): where it last
 * stood (`last`, a groupPlace answer, with the group's `size`), its leader from `edge`, the point at the view's edge
 * the person left by, to the side of the group that faces it, at the name line, as groupPlace draws it. Given the
 * `viewport` as it is now, a window made smaller since keeps the group whole inside it.
 */
export function groupHeld({ last, edge, size, viewport = null, scale = 1, layout = GROUP_LAYOUT }) {
  const inset = layout.inset * scale;
  const at = viewport === null ? last : {
    x: Math.max(inset, Math.min(viewport.width - inset - size.width, last.x)),
    y: withinHeight(last.y, size, viewport, scale, layout),
  };
  const side = edge.x <= at.x + size.width / 2 ? 'right' : 'left';
  const towards = side === 'right' ? 1 : -1;
  const facing = side === 'right' ? at.x : at.x + size.width;
  const nameY = at.y + layout.nameMiddle * scale;
  const leader = Object.freeze({
    from: Object.freeze({ x: edge.x, y: edge.y }),
    elbow: Object.freeze({ x: facing - towards * layout.elbow * scale, y: nameY }),
    to: Object.freeze({ x: facing - towards * layout.end * scale, y: nameY }),
  });
  return Object.freeze({ x: at.x, y: at.y, side, leader });
}

/** A group's top `y` moved up as far as shows its whole height `least` above the window's bottom, never above its top. */
function withinHeight(y, size, viewport, scale, layout) {
  return Math.max(0, Math.min(viewport.height - layout.least * scale - size.height, y));
}

/** Whether `model` is the one `current` names (both null: their routine). */
const sameModel = (model, current) => model === null || current === null ? model === current
  : model.provider === current.provider && (model.modelId ?? model.model_id) === (current.modelId ?? current.model_id);

/** What the price of a model a key pays for is ordered by (A3): a million tokens in, then out. */
const PRICE_ORDER = [model => Number(model?.price?.input ?? Infinity), model => Number(model?.price?.output ?? Infinity)];

/**
 * The models a person may choose here (F5), from the models read: the ones it says this install can ask, so a
 * model refused here (a server on this computer the install does not reach, a provider it holds no key for)
 * is never offered, "On this computer · Free" least of all. Both choosers, their number keys too, take this list,
 * in the gallery's order (A3): what this computer runs first, then the rest by price, lowest first, the served
 * order breaking a tie. On a guest's page a model asking which once can cost more than they have left is not
 * among them: it stands faint (overRows, U2).
 */
export function choosableModels(read) {
  return offeredHere(read).filter(model => !overBudget(model, read));
}

/** Every model the read offers here in the gallery's order, a guest's faint ones among them (U2). */
function offeredHere(read) {
  const offered = (read?.models ?? []).filter(model => !model.refusal).map((model, at) => ({ model, at }));
  const order = (one, other) => Number(one.model.local !== true) - Number(other.model.local !== true)
    || PRICE_ORDER.reduce((found, price) => found || price(one.model) - price(other.model), 0) || one.at - other.at;
  return offered.sort(order).map(({ model }) => model);
}

/**
 * Where the page is a guest's, whose read says what they have left for AI models here by provider (U2): whether one
 * attempt of a decision with `model` can cost more than that (ROOT 12:20, the nearest knowable to an ask that would be
 * refused). On a person's own install the read says nothing, and no model is.
 */
export function overBudget(model, read) {
  const left = read?.spendHereUsd?.[model.provider];
  return left !== undefined && model.attemptMostUsd !== undefined && Number(model.attemptMostUsd) > Number(left);
}

/**
 * A guest's faint rows (U2, DESIGN 11:29 and 12:20): each model asking which once can cost more than they have
 * left here, in the gallery's order, by its name and maker with why in a line; no number and no focus.
 */
export function overRows(read, current = null) {
  return offeredHere(read).filter(model => overBudget(model, read)).map(model => Object.freeze({
    word: model.name, sub: makerLine(model), line: overLine(model.attemptMostUsd, read.spendHereUsd[model.provider]),
    // The person's own model keeps "Current" while it stands faint (DESIGN 15:58).
    current: current !== null && sameModel(model, current),
  }));
}

/** Whether every model a run asks runs on this computer: `chosen` the models chosen, as the models read names them. */
export function freeHere(read, chosen) {
  const local = new Set((read?.models ?? []).filter(model => model.local).map(model => `${model.provider}/${model.modelId}`));
  return chosen.length > 0 && chosen.every(model => model && local.has(`${model.provider}/${model.modelId}`));
}

/** Whether [M] is offered (F5): the models read takes choices and offers a model this install can ask, a guest's
 * faint ones too (U2), so the list shows why they cannot be chosen. */
export function offersModels(read) {
  return Boolean(read?.takesModelChoices) && offeredHere(read).length > 0;
}
