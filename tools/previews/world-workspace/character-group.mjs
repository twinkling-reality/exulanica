// A chosen character's group beside them in the world (DESIGN's J30, the r05 picture;
// BUILD-SHEETS-CHARACTER-TALKING-BUILDING.md section 1): what it says, from the reads the page holds, and where
// it stands. Pure: the reads come in as data and the words from character-words.mjs; character-group.ts draws
// the answer. verify-character-group.mjs holds it.
import { ANOTHER_MODEL, CHARACTER_WORDS, GROUP_WORDS, cardWords, checkingLine, decidesPrint, keyGroup, makerLine, modelsDecide, modelsNamed, noModelRunning, notAbleFold, notAbleLine, overLine, providerName, quoted, readingRecord, reasonsOn, routineRow, rowPrice, runnerCalls, runnerOpen, saidUnder, stopsAfter } from './character-words.mjs';
import { RUN_WORDS, atMost, runFor, runRefusalWords } from './run-words.mjs';
import { dayWord } from './talk-words.mjs';
import { worldTime } from './world-clock.mjs';

/**
 * The group's figures, in reference pixels at 1920 by 1080 (scaled by the page's --ui-scale): the gap from
 * the person's on-screen edge to the group's words, the leader's elbow and end before the words, the name
 * line's middle below the group's top, the inset the group keeps from the screen's sides, and the bands it
 * keeps clear of at the top and bottom, where the world screen's pills and keys sit (32 in, 40 tall, then
 * the shade's own 24 and a gap of 16).
 */
export const GROUP_LAYOUT = Object.freeze({ gap: 100, elbow: 56, end: 36, nameMiddle: 24, inset: 32, top: 112, bottom: 112 });

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
  if (decider === 'person' || decider === 'external') return decider;
  return plain(model) ? 'model' : 'routine';
}

/**
 * What the group says (J30), top to bottom: the name, what they are doing, the last line said and under it
 * to whom and when, the key rows that work now, and who decides as small print. `state`:
 * - `who` (called()'s), `doing` (the society's activity words, or null);
 * - `said` (lastSaid's answer, or null), `toWho` (called()'s for its listener, or null), `startMinute` (the
 *   society clock's first minute, null where it keeps none);
 * - `decider` (deciderOf's: 'person', 'external', 'model' or 'routine'), `model` (the model's served name, or null), `connected` (a model can be asked
 *   here), `assignable` (this page may choose their model), `running` (a run is on), `left` (its time left);
 * - `following` (V follows them now); `reading` while their record is still read, when the group holds their
 *   name and that it is reading, and no keys yet.
 * Each row: { action, key, word, shortcut }. Run only where their model can be asked here (J2); while a run
 * is on, Stop; without a model, Choose only where this page may choose one.
 */
export function groupContent({ who, doing = null, said = null, toWho = null, startMinute = null, decider = 'routine', model = null,
  connected = true, assignable = false, running = false, left = null, following = false, reading = false, noModel = null }) {
  if (reading) return Object.freeze({ name: who.title, doing: readingRecord(who), said: null, note: null, rows: Object.freeze([]), list: null, print: null, after: null, refused: false });
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
    list: null,
    print: decidesPrint(who, { decider, model, left: running && decided ? left : null }),
    // Where [M] is not offered because no model is running on this computer, how to have one, under the small print (A2).
    after: decider === 'routine' && !assignable && noModel ? noModel : null,
    refused: false,
  });
}

/**
 * The Run question (r08, R-RUN-BUILD-SHEET section 1): R turns the same group, in place, into the question. Top to
 * bottom: the name, "Run for 10 minutes", whose models the run asks (J28: `askers`, called()'s with the chosen
 * character first; `others` whether anybody else lives here), the rows "[Enter] Run" and, where another model is
 * offered and this page may choose one, "[M] Choose another model", then the models it asks (`models`, their names with
 * the chosen character's first) and the cap as small print with when it stops under it. A refusal (`refusal`, the server's code) takes the small print's place in its own
 * sentence and dims Run, which still answers its key; `busy` while the start is asked, when Run does nothing.
 */
export function questionGroup({ who, askers = [who], others = true, models = [], limits, refusal = null, busy = false, anotherModel = false, free = false }) {
  const rows = [{ action: 'run', key: 'Enter', word: RUN_WORDS.run, shortcut: 'Enter', disabled: busy }];
  if (anotherModel) rows.push({ action: 'model', key: 'M', word: ANOTHER_MODEL, shortcut: 'M' });
  return Object.freeze({
    name: who.title,
    doing: runFor(limits),
    said: null,
    note: modelsDecide(askers.length ? askers : [who], { others }),
    rows: Object.freeze(rows.map(row => Object.freeze(row))),
    list: null,
    // A run whose every model is on this computer costs nothing: it says so in place of its cap (A2).
    print: refusal ? runRefusalWords(refusal, modelsNamed(models)) : `${modelsNamed(models) ?? ''} \u00b7 ${free ? CHARACTER_WORDS.freeHere : atMost(limits)}`.replace(/^ \u00b7 /u, ''),
    after: refusal ? null : stopsAfter(Math.round(limits.wallSeconds / 60)),
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
  const y = Math.max(top, Math.min(viewport.height - bottom - size.height, head.y - size.height / 2));
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
 * the person left by, to the side of the group that faces it, at the name line, as groupPlace draws it.
 */
export function groupHeld({ last, edge, size, scale = 1, layout = GROUP_LAYOUT }) {
  const side = edge.x <= last.x + size.width / 2 ? 'right' : 'left';
  const towards = side === 'right' ? 1 : -1;
  const facing = side === 'right' ? last.x : last.x + size.width;
  const nameY = last.y + layout.nameMiddle * scale;
  const leader = Object.freeze({
    from: Object.freeze({ x: edge.x, y: edge.y }),
    elbow: Object.freeze({ x: facing - towards * layout.elbow * scale, y: nameY }),
    to: Object.freeze({ x: facing - towards * layout.end * scale, y: nameY }),
  });
  return Object.freeze({ x: last.x, y: last.y, side, leader });
}

/** How many model rows show at once, each on its number key (1 to 9); the arrows move past nine (r07). */
export const MODEL_ROWS = 9;

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
export function overRows(read) {
  return offeredHere(read).filter(model => overBudget(model, read)).map(model => Object.freeze({
    word: model.name, sub: makerLine(model), line: overLine(model.attemptMostUsd, read.spendHereUsd[model.provider]),
  }));
}

/** The code a model on this computer is refused by while no server runs there (PROJECT's A2 liveness read). */
export const NOT_RUNNING = 'provider_not_running';

/**
 * Whether the chooser's group for this computer stands with no model in it (A3 item 2, amended 17:22): this install
 * lets a model on this computer in, and none runs yet. Where it does not let one in, the group is left out.
 */
export function noneRunningHere(read) {
  const models = read?.models ?? [];
  return models.some(model => model.local === true && model.refusal === NOT_RUNNING) && !models.some(model => model.local === true && !model.refusal);
}

/**
 * The chooser's rows as a gallery that teaches (A3, WORDS.md): the models in choosableModels' order, then Routine, each
 * with the label of the group it stands in (this computer, free; a provider's key, or this server's budget on a
 * guest's page, per million tokens; Routine under none), its maker and size, its price, and its maker's own words
 * (shown on the focused row). `fromServer` where the page is a guest's, whose models a host pays for.
 */
export function galleryItems(models, fromServer = false, runner = []) {
  const shared = sharedNames(models, runner);
  return [...models.map(model => ({
    model, word: model.name, price: rowPrice(model),
    sub: model.runner ? (shared.has(model.name) ? runnerCalls(model.runner) : null) : makerLine(model),
    open: model.runner ? runnerOpen(model) : cardWords(model),
    group: model.local === true ? CHARACTER_WORDS.hereFree : fromServer ? CHARACTER_WORDS.serverBudget : keyGroup(providerName(model)),
  })), { model: null, word: CHARACTER_WORDS.routine, sub: null, price: routineRow(), open: null, group: null }];
}

/** The names more than one of the chooser's rows or a runner's faint rows would read by (L1 rule 5). */
function sharedNames(models, runner) {
  const seen = new Map();
  for (const name of [...models.map(model => model.name), ...runner.filter(model => model.state !== 'able').map(model => model.name)]) {
    seen.set(name, (seen.get(name) ?? 0) + 1);
  }
  return new Set([...seen].filter(([, n]) => n > 1).map(([name]) => name));
}

/**
 * The faint rows under this computer's choosable rows (L1, DESIGN's words): each runner's model being checked, then,
 * under their own faint label, each one a check found not able with its reason in one line. No number and no focus:
 * none is offered. `runner` is the models read's runnerModels; `models` the chooser's, to tell same names apart.
 */
export function runnerRows(runner = [], models = [], foldFor = null) {
  const shared = sharedNames(models, runner);
  const sub = model => (shared.has(model.name) ? runnerCalls(model) : null);
  const checking = runner.filter(model => model.state === 'checking').map(model => Object.freeze({ word: checkingLine(model), sub: sub(model) }));
  const notAble = runner.filter(model => model.state === 'not_able').map(model => Object.freeze({ word: model.name, sub: sub(model), line: notAbleLine(model) }));
  if (!checking.length && !notAble.length) return null;
  // The world's list (`foldFor`, whose day page it is) folds the not-able rows into one line (DESIGN 11:58), so Routine
  // and the keys stay in view; the day page's chooser lists each with its reason.
  if (foldFor && notAble.length) {
    return Object.freeze({ checking: Object.freeze(checking), label: null, notAble: Object.freeze([]),
      fold: Object.freeze({ line: notAbleFold(notAble.length), sub: reasonsOn(foldFor) }) });
  }
  return Object.freeze({ checking: Object.freeze(checking), label: notAble.length ? CHARACTER_WORDS.notAbleHere : null, notAble: Object.freeze(notAble), fold: null });
}

/** The refusals of a model this install would never offer: a hosted one where it holds no key. */
const NEVER_OFFERED = new Set(['provider_credential_absent']);

/**
 * How to have a model, said of `who`, where the card offers none because none is running on this computer (A2): the
 * models read takes choices, and every model this install would offer is refused as not running here. Null otherwise:
 * a model to choose, one left out by setting (provider_not_admitted), or any other cause.
 */
export function noModelLine(read, who) {
  const refusals = (read?.models ?? []).map(model => model.refusal ?? null).filter(code => !NEVER_OFFERED.has(code));
  if (!read?.takesModelChoices || !refusals.length || !refusals.every(code => code === 'provider_not_running')) return null;
  return noModelRunning(who);
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

/** An open chooser while the models read offers a model to choose or a guest's faint one (F5, U2): with none, it closes. */
export function openWhileOffered(choosing, read) {
  return offeredHere(read).length ? choosing : null;
}

/**
 * Choose a model (r07, R-RUN-BUILD-SHEET section 3; a gallery that teaches, A3): M turns the same group, in place,
 * into the list of the models the server offers, in choosableModels' order, with Routine last. Top to bottom: the
 * name, "Choose a model", what the models are and that picking spends nothing, then the rows in groups by where they
 * run, each group under its label: a row per model (its number key, its name with "Current" after the character's
 * own, under it its maker and size, its price), the focused one opened beneath with its maker's own words, at most
 * MODEL_ROWS at once around `focus` (an index into the models, `models.length` for Routine), then the small keys.
 * `waiting` stands this computer's group with its one line and no key where none runs yet (noneRunningHere);
 * `fromServer` labels the key group as this server's budget (a guest's page). `refusal` is the write's refusal in
 * its own words (modelRefusalWords); `busy` while the choice is written. `runner` is the models read's runnerModels:
 * those not offered stand faint after this computer's last choosable row (runnerRows), or under its label at the top
 * where it has none. Each list row: { action: 'use', index, key, word, sub, price, current, on, label, open, runner },
 * `label` the group's where the row starts one in the window, `open` the maker's words on the focused row, `runner`
 * the faint rows after this computer's last row.
 */
export function modelGroup({ who, models = [], current = null, focus = 0, refusal = null, busy = false, waiting = false, fromServer = false, runner = [], over = [] }) {
  const items = galleryItems(models, fromServer, runner);
  // A runner's models not offered (L1) stand faint after this computer's last choosable row, or, with none, under the
  // group's label at the top; those not able fold into one line here.
  const faint = runnerRows(runner, models, who);
  const lastHere = items.reduce((found, item, index) => (item.group === CHARACTER_WORDS.hereFree ? index : found), -1);
  // A guest's models asking which once can cost more than they have left (U2, overRows) stand faint after the
  // last model offered, under the server's budget label where that model is not in it, or, with none, first.
  const lastModel = items.length - 2;
  const dearLabel = lastModel >= 0 && items[lastModel].group === CHARACTER_WORDS.serverBudget ? null : CHARACTER_WORDS.serverBudget;
  const dear = over.length ? Object.freeze({ checking: Object.freeze([]), label: dearLabel, notAble: Object.freeze([...over]) }) : null;
  const at = Math.max(0, Math.min(items.length - 1, Number.isSafeInteger(focus) ? focus : 0));
  // Routine stands below the models whatever the window (DESIGN 11:58): the window moves over the models alone.
  const routine = items.length - 1, room = MODEL_ROWS - 1;
  const first = Math.max(0, Math.min(routine - room, Math.min(at, routine - 1) - room + 1));
  const shown = [...items.slice(first, Math.min(first + room, routine)).map((item, offset) => ({ item, index: first + offset })), { item: items[routine], index: routine }];
  const rows = shown.map(({ item, index }, offset) => Object.freeze({
    action: 'use', index, key: String(offset + 1), word: item.word, sub: item.sub, price: item.price,
    current: sameModel(item.model, current), on: index === at,
    label: item.group !== null && (offset === 0 || shown[offset - 1].item.group !== item.group) ? item.group : null,
    open: index === at ? item.open : null,
    runner: index === lastHere ? faint : null,
    over: index === lastModel ? dear : null,
  }));
  return Object.freeze({
    name: who.title,
    doing: CHARACTER_WORDS.chooseModel,
    said: null,
    note: CHARACTER_WORDS.chooserIntro,
    rows: Object.freeze([]),
    list: Object.freeze({
      waiting: waiting && first === 0 ? Object.freeze({ label: CHARACTER_WORDS.hereFree, line: CHARACTER_WORDS.noneRunning }) : null,
      runner: faint && lastHere < 0 && first === 0 ? Object.freeze({ ...faint, group: CHARACTER_WORDS.hereFree }) : null,
      over: dear && lastModel < 0 && first === 0 ? dear : null,
      first, rows: Object.freeze(rows), busy,
      // More models past the window's foot: its foot fades, as the told column's does.
      more: first + room < routine,
      keys: Object.freeze([{ keys: ['\u2191', '\u2193'], word: CHARACTER_WORDS.choose }, { keys: ['Enter'], word: CHARACTER_WORDS.useThisModel }]),
    }),
    print: refusal,
    after: null,
    refused: Boolean(refusal),
  });
}

/** The index a number key names in modelGroup's window from `first`: a model in it, or Routine just under it. */
function windowIndex(first, number, count) {
  const shown = Math.min(MODEL_ROWS - 1, count - first);
  return number <= shown ? first + number - 1 : number === shown + 1 ? count : -1;
}

/** The keys that still move the person while the model list shows (r07). */
const MOVING_KEYS = Object.freeze(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight', 'Tab']);

/**
 * Choosing a model in the group (r07): the list's state for the chosen character and its keys. M opens it on their
 * current model, or where Routine is theirs on the first model, opened with its maker's words (focus never chooses);
 * the arrows move; a number (on the window
 * modelGroup shows) or Enter gives that model; Esc closes it unchanged, and it closes when `offered()` says none is
 * left (by default when none is left to choose; a guest's page keeps it while faint ones show, U2).
 * `models()` is the models a person may choose here (choosableModels), `currentOf(row)` the character's model; `write(row, selected, key)` makes the page's own write (selected null for
 * Routine) and answers the models read it verified, or throws the refusal; `refusal(error, row)` words a refusal;
 * `onUsed(verified)` runs after a write. A write keeps its idempotency key until it is refused.
 */
export function modelPicker({ models, currentOf, write, refusal, onUsed = (verified) => verified, newKey = () => crypto.randomUUID(), offered = () => models().length > 0 }) {
  let picking = null;
  const picker = {
    of(row) {
      if (!offered()) picking = null;
      return picking !== null && picking.row === row ? picking : null;
    },
    open(row) {
      const list = models(), current = currentOf(row) ?? null;
      const at = list.findIndex(model => sameModel(model, current));
      picking = { row, focus: Math.max(at, 0), refusal: null, busy: false, key: newKey() };
    },
    /** Esc: back to where M was pressed, unless a write is on its way. */
    close() { if (!picking?.busy) picking = null; },
    /** The character let go of: the list goes with them. */
    drop() { picking = null; },
    move(delta) {
      if (!picking || picking.busy) return;
      picking.focus = Math.max(0, Math.min(models().length, picking.focus + delta));
      picking.refusal = null;
    },
    async use(index) {
      const showing = picking, list = models();
      if (!showing || showing.busy || !Number.isSafeInteger(index) || index < 0 || index > list.length) return;
      showing.focus = index; showing.busy = true; showing.refusal = null;
      try {
        const verified = await write(showing.row, index < list.length ? list[index] : null, showing.key);
        if (picking === showing) picking = null;
        onUsed(verified);
      } catch (error) {
        showing.refusal = refusal(error, showing.row);
        showing.key = newKey();
      } finally { showing.busy = false; }
    },
    /**
     * The model list's keys while it shows: 'pass' for a key that still moves the person, true for a key the list took
     * (its default prevented), false where no list shows. `first` is the window's first index (modelGroup's list.first);
     * `onButton` whether Enter fell on a button, which presses itself.
     */
    key(event, first = 0, onButton = false) {
      if (!picking) return false;
      const digit = /^Digit([1-9])$/u.exec(event.code);
      if (MOVING_KEYS.includes(event.code)) return 'pass';
      if (event.code === 'Enter' && onButton) return 'pass';
      event.preventDefault();
      if (event.repeat) return true;
      if (event.code === 'ArrowUp' || event.code === 'ArrowDown') picker.move(event.code === 'ArrowUp' ? -1 : 1);
      else if (digit) void picker.use(windowIndex(first, Number(digit[1]), models().length));
      else if (event.code === 'Enter') void picker.use(picking.focus);
      else if (event.code === 'Escape') picker.close();
      return true;
    },
  };
  return picker;
}
