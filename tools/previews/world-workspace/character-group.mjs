// A chosen character's group beside them in the world (DESIGN's J30, the r05 picture;
// BUILD-SHEETS-CHARACTER-TALKING-BUILDING.md section 1): what it says, from the reads the page holds, and where
// it stands. Pure: the reads come in as data and the words from character-words.mjs; character-group.ts draws
// the answer. verify-character-group.mjs holds it.
import { ANOTHER_MODEL, CHARACTER_WORDS, GROUP_WORDS, decidesPrint, modelsDecide, modelsNamed, priceWords, quoted, readingRecord, routineRow, saidUnder, stopsAfter } from './character-words.mjs';
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
  connected = true, assignable = false, running = false, left = null, following = false, reading = false }) {
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
    after: null,
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
export function questionGroup({ who, askers = [who], others = true, models = [], limits, refusal = null, busy = false, anotherModel = false }) {
  const rows = [{ action: 'run', key: 'Enter', word: RUN_WORDS.run, shortcut: 'Enter', disabled: busy }];
  if (anotherModel) rows.push({ action: 'model', key: 'M', word: ANOTHER_MODEL, shortcut: 'M' });
  return Object.freeze({
    name: who.title,
    doing: runFor(limits),
    said: null,
    note: modelsDecide(askers.length ? askers : [who], { others }),
    rows: Object.freeze(rows.map(row => Object.freeze(row))),
    list: null,
    print: refusal ? runRefusalWords(refusal) : `${modelsNamed(models) ?? ''} \u00b7 ${atMost(limits)}`.replace(/^ \u00b7 /u, ''),
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

/** How many model rows show at once, each on its number key (1 to 9); the arrows move past nine (r07). */
export const MODEL_ROWS = 9;

/** Whether `model` is the one `current` names (both null: their routine). */
const sameModel = (model, current) => model === null || current === null ? model === current
  : model.provider === current.provider && (model.modelId ?? model.model_id) === (current.modelId ?? current.model_id);

/**
 * Choose a model (r07, R-RUN-BUILD-SHEET section 3): M turns the same group, in place, into the list of the models the
 * server offers, in its order, with Routine last. Top to bottom: the name, "Choose a model", that picking spends nothing,
 * "Per million tokens" over the price column, one row per model (its number key, its name with "Current" after the
 * character's own, its price), at most MODEL_ROWS at once around `focus` (an index into the models, `models.length` for
 * Routine), then the small keys. `refusal` is the write's refusal in its own words (modelRefusalWords); `busy` while
 * the choice is written. Each list row: { action: 'use', index, key, word, price, current, on }.
 */
export function modelGroup({ who, models = [], current = null, focus = 0, refusal = null, busy = false }) {
  const items = [...models.map(model => ({ model, word: model.name, price: priceWords(model) ?? '' })),
    { model: null, word: CHARACTER_WORDS.routine, price: routineRow() }];
  const at = Math.max(0, Math.min(items.length - 1, Number.isSafeInteger(focus) ? focus : 0));
  const first = Math.max(0, Math.min(items.length - MODEL_ROWS, at - MODEL_ROWS + 1));
  const rows = items.slice(first, first + MODEL_ROWS).map((item, offset) => Object.freeze({
    action: 'use', index: first + offset, key: String(offset + 1), word: item.word, price: item.price,
    current: sameModel(item.model, current), on: first + offset === at,
  }));
  return Object.freeze({
    name: who.title,
    doing: CHARACTER_WORDS.chooseModel,
    said: null,
    note: CHARACTER_WORDS.pickingSpendsNothing,
    rows: Object.freeze([]),
    list: Object.freeze({
      head: CHARACTER_WORDS.perMillion, first, rows: Object.freeze(rows), busy,
      keys: Object.freeze([{ keys: ['\u2191', '\u2193'], word: CHARACTER_WORDS.choose }, { keys: ['Enter'], word: CHARACTER_WORDS.useThisModel }]),
    }),
    print: refusal,
    after: null,
    refused: Boolean(refusal),
  });
}

/** The keys that still move the person while the model list shows (r07). */
const MOVING_KEYS = Object.freeze(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight', 'Tab']);

/**
 * Choosing a model in the group (r07): the list's state for the chosen character and its keys. M opens it on their
 * current model (Routine, after the served models, where they have none); the arrows move; a number (on the window
 * modelGroup shows) or Enter gives that model; Esc closes it unchanged. `models()` is the models read's served list,
 * `currentOf(row)` the character's model; `write(row, selected, key)` makes the page's own write (selected null for
 * Routine) and answers the models read it verified, or throws the refusal; `refusal(error, row)` words a refusal;
 * `onUsed(verified)` runs after a write. A write keeps its idempotency key until it is refused.
 */
export function modelPicker({ models, currentOf, write, refusal, onUsed = (verified) => verified, newKey = () => crypto.randomUUID() }) {
  let picking = null;
  const picker = {
    of: (row) => picking !== null && picking.row === row ? picking : null,
    open(row) {
      const list = models(), current = currentOf(row) ?? null;
      const at = list.findIndex(model => sameModel(model, current));
      picking = { row, focus: at < 0 ? list.length : at, refusal: null, busy: false, key: newKey() };
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
      else if (digit) void picker.use(first + Number(digit[1]) - 1);
      else if (event.code === 'Enter') void picker.use(picking.focus);
      else if (event.code === 'Escape') picker.close();
      return true;
    },
  };
  return picker;
}
