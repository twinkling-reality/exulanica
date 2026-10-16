// What the world shows beside a character or thing (DESIGN's frames 04 and 05): its name tag while
// it is looked at, and the ring and card once it is chosen. Pure: the reads come in as data and the
// words from character-words.mjs; character-presence.ts draws the answer. verify-character-view.mjs
// holds it.
import { CHARACTER_WORDS, called, chosenLine, deciderWords, readingRecord, rowSub } from './character-words.mjs';
import { PAUSE_FIRST, RUN_WORDS, atMost, runFor, runRefusalWords, whoDecides } from './run-words.mjs';
import { heardRow, saidRow } from './talk-words.mjs';
import { worldTime } from './world-clock.mjs';

const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;

/**
 * What a subject is called, from its offer (`exulanica.subject-offer/v1`) and inventory row. A
 * body's own label is not an individual name, so a being named only by its body is called by its kind,
 * or by the role its society gives it (`role`, "resident") where its kind has no label.
 */
export function subjectWho(row, offer, role = null) {
  const being = row?.scene?.type === 'being';
  const kind = offer?.subject?.kind;
  const body = plain(kind?.body?.name)?.toLowerCase() ?? null;
  const own = value => plain(value) && plain(value).toLowerCase() !== body ? plain(value) : null;
  const name = own(offer?.subject?.name);
  const sort = plain(kind?.label) || (being ? plain(role) : plain(offer?.properties?.find(item => item.key === 'look')?.value?.label) || own(row?.label));
  return called({ name, kind: sort, being });
}

/** A catalog sentence ("Resting at the bench.", "eating at home") as a tag's or card's line. */
export function doingLine(sentence) {
  const words = plain(sentence);
  if (!words) return null;
  const trimmed = words.replace(/\.$/u, '');
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

/**
 * The model decision that set a character's current action, as the chosen card says it, or null
 * when the routine set it. A purposeful society records the model's choice in the goal's reason
 * (`chosen_by_their_model`); a living one records it only in its events, so there the latest
 * applied decision is taken as the source. `latest` is the models read's newest decision for the
 * character; `startMinute` the society clock's start (null where it keeps none); `options` the
 * number of choices the decision offered, once read.
 */
export function chosenDecision({ person, latest, living = false, startMinute = null, options = null }) {
  if (!latest || latest.disposition !== 'applied' || latest.consumedTick === null) return null;
  if (!living && person?.goal?.reason !== 'chosen_by_their_model') return null;
  const hhmm = worldTime(latest.consumedTick, startMinute)?.hhmm ?? null;
  return Object.freeze({ hhmm, options, requestId: latest.requestId ?? null, model: latest.name });
}

/**
 * The chosen card's words and prompts (spec 8.5, DESIGN's J1 and J2). `state` holds what is known:
 * `who`, `being`, `doing`, `decision` (from chosenDecision), `model` (the assigned model's name or
 * null), `decider` (`person` or `external` where a person playing or an outside program decides, T7:
 * the chip says so, and the line where `deciderChose` its current action), `running` (a run is
 * open), `connected` (a model can be asked here), `following`, `reading` (the record is still being
 * read) and `thingLine` (a thing's one line, build mode's words).
 */
export function chosenCard({ who, being, doing = null, decision = null, model = null, decider = null, deciderChose = false, running = false, connected = true, following = false, reading = false, thingLine = null }) {
  if (!being) return Object.freeze({ title: who.title, lines: [thingLine].filter(Boolean), chip: null, prompts: [] });
  if (reading) return Object.freeze({ title: who.title, lines: [readingRecord(who)], chip: null, prompts: [] });
  const lines = [doing, deciderChose && deciderWords(decider) ? chosenLine(who, null, decider)
    : decision ? chosenLine(who, decision.hhmm ? decision : { ...decision, hhmm: null }) : chosenLine(who, null)].filter(Boolean);
  const prompts = [{ action: 'details', keys: ['Enter'], word: CHARACTER_WORDS.details, shortcut: 'Enter' }];
  // Run only where the character has a model that can be asked here (DESIGN's J2); Stop while one is on.
  if (running) prompts.push({ action: 'stop', keys: ['R'], word: CHARACTER_WORDS.stop, shortcut: 'R' });
  else if (model && connected) prompts.push({ action: 'run', keys: ['R'], word: CHARACTER_WORDS.run, shortcut: 'R' });
  prompts.push({ action: 'follow', keys: ['V'], word: following ? CHARACTER_WORDS.stopFollowing : CHARACTER_WORDS.follow, shortcut: 'V' });
  return Object.freeze({ title: who.title, lines, chip: deciderWords(decider) ?? model, live: Boolean(running && model), prompts });
}

/** The name tag's words (spec 5.3): a thing shows its name only; a pop hides the doing line. */
export function tagWords({ who, being, doing = null, model = null, live = false, popping = false }) {
  if (!being) return Object.freeze({ name: who.title, doing: null, model: null, live: false });
  return Object.freeze({ name: who.title, doing: popping ? null : doing, model, live: Boolean(model && live) });
}

/** The ring's radius on the ground under a person, in metres: rx 104 px at 4 m in the frame. */
export const PERSON_RING_METRES = 0.44;

/**
 * The ring's screen radii from the projected ground point and two points `radius` metres from it,
 * one along the camera's right and one along its forward direction on the ground. A ring never
 * shrinks below a readable size.
 */
export function ringRadii(ground, right, forward, least = { rx: 18, ry: 5 }) {
  const rx = Math.hypot(right.x - ground.x, right.y - ground.y);
  const ry = Math.abs(forward.y - ground.y);
  return { rx: Math.max(least.rx, rx), ry: Math.max(least.ry, Math.min(ry, rx)) };
}

/**
 * Where the [E] Inspect prompt sits: 52 reference px right of the head point at head height, or as
 * far left of it when the right would leave the screen (spec 5.3).
 */
export function promptPlace(head, size, viewport, scale = 1, inset = 40) {
  const gap = 52 * scale;
  const right = head.x + gap;
  const x = right + size.width <= viewport.width - inset * scale ? right : head.x - gap - size.width;
  return { x, y: head.y - size.height / 2 + 14 * scale };
}

/**
 * Where the camera stands for a character's page (spec 5.7): about 2.6 m from the character at eye
 * height, turned so the character stands at 30 % of the width, looking a little down. Figures are
 * defaults a caller may replace.
 */
export const PAGE_FRAMING = Object.freeze({ distance: 2.6, share: 0.30, eyeHeight: 1.62, aim: 0.9, tilt: 0.5, easeMs: 600 });

/**
 * The page's camera pose for a character standing at `ground` ({x, y, z}, metres), seen from the
 * camera at `eye` ({x, z}), with the camera's vertical field of view `fovDeg` and `aspect`. Yaw 0
 * looks along -Z and a larger yaw turns left (the workspace controls' convention).
 */
export function pageFraming({ ground, eye, fovDeg, aspect, framing = PAGE_FRAMING }) {
  let dx = ground.x - eye.x, dz = ground.z - eye.z;
  const length = Math.hypot(dx, dz);
  if (length < 1e-6) { dx = 0; dz = -1; } else { dx /= length; dz /= length; }
  const facing = Math.atan2(-dx, -dz);
  const halfWidth = Math.atan(Math.tan((fovDeg * Math.PI / 180) / 2) * aspect);
  const offset = Math.atan((0.5 - framing.share) * 2 * Math.tan(halfWidth));
  const pitch = -Math.atan((framing.eyeHeight - framing.aim) / framing.distance) * framing.tilt;
  return Object.freeze({ x: ground.x - dx * framing.distance, y: ground.y + framing.eyeHeight, z: ground.z - dz * framing.distance, yaw: facing - offset, pitch });
}

/**
 * Following a character who talks with another (T5): the pose that frames both heads, from the
 * following pose `from` ({x, y, z, yaw, pitch}): turned to face the middle of the two, at the same
 * height and pitch, as far back as puts both heads within `safe` of the half width from the middle of
 * the view (room for their pops and the card), and never nearer than `least` to the nearer of the two
 * along the line of sight (one standing beyond the other never puts the nearer behind the camera).
 */
export function pairFraming({ from, a, b, fovDeg, aspect, safe, least = 0 }) {
  const mid = { x: (a.x + b.x) / 2, z: (a.z + b.z) / 2 };
  let dx = mid.x - from.x, dz = mid.z - from.z;
  const length = Math.hypot(dx, dz);
  if (length < 1e-6) { dx = -Math.sin(from.yaw); dz = -Math.cos(from.yaw); } else { dx /= length; dz /= length; }
  const yaw = Math.atan2(-dx, -dz);
  const across = Math.abs((b.x - a.x) * Math.cos(yaw) - (b.z - a.z) * Math.sin(yaw));
  const along = Math.abs((b.x - a.x) * dx + (b.z - a.z) * dz);
  const halfWidth = Math.atan(Math.tan((fovDeg * Math.PI / 180) / 2) * aspect);
  const distance = Math.max(least + along / 2, across / 2 / (safe * Math.tan(halfWidth)));
  return Object.freeze({ x: mid.x - dx * distance, y: from.y, z: mid.z - dz * distance, yaw, pitch: from.pitch });
}

/** A pose between two, `t` from 0 to 1, eased in and out; yaw turns the short way round. */
export function easePose(from, to, t) {
  const k = t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
  const turn = Math.atan2(Math.sin(to.yaw - from.yaw), Math.cos(to.yaw - from.yaw));
  const mix = key => from[key] + (to[key] - from[key]) * k;
  return Object.freeze({ x: mix('x'), y: mix('y'), z: mix('z'), yaw: from.yaw + turn * k, pitch: mix('pitch') });
}

/**
 * The question before a run (frame 08): the character's name over "Run for 10 minutes", what a run
 * does, its model, the orb with the most it can spend, and [Enter] Run, [Esc] Back; a refusal in
 * the card where it happened, with [P] Pause when the world is playing.
 */
export function runQuestion({ who, model, limits, refusal = null, busy = false }) {
  const answers = [{ action: 'run', keys: ['Enter'], word: RUN_WORDS.run, shortcut: 'Enter' }];
  if (refusal === PAUSE_FIRST) answers.push({ action: 'pause', keys: ['P'], word: RUN_WORDS.pause, shortcut: 'P' });
  answers.push({ action: 'back', keys: ['Esc'], word: RUN_WORDS.back, shortcut: 'Escape' });
  return Object.freeze({ label: who.title, title: runFor(limits), lines: [whoDecides(who)], chip: model, orbWord: RUN_WORDS.run,
    big: atMost(limits, true), small: RUN_WORDS.stopsByItself, refusal: refusal ? runRefusalWords(refusal) : null, answers, busy });
}

/**
 * The rows of What Teo did (frame 06), newest first, at most `limit`: from the society's events for
 * the character, newest first as the events read serves them. A line said is one row ("Said to Ines:
 * “…”", T6); a model's applied choice is one row; a goal the routine set is one row. A goal a model's
 * choice set is the choice's row already. A line said to the character, or to everyone near while the
 * character heard it, is a `heard` row ("Heard Ines: “…”") with no sub-line and no decision; a line
 * overheard, said to someone else, is none. `wordGoal(document)` says a goal in the catalog's words;
 * `modelName` names a model by its provider and id; `options(requestId)` is a decision's number of
 * choices once read; `who(id)` calls a person as the tag and card do (J20).
 */
export function didRows({ events, subjectId, startMinute = null, wordGoal, modelName, options = () => null, who = () => called({ name: null, kind: null }), limit = 7 }) {
  const heard = event => event.subject_id !== subjectId && event.event_kind === 'said' && typeof event.document?.thing?.line === 'string'
    && Array.isArray(event.document.thing.heard_by) && event.document.thing.heard_by.includes(subjectId) && (event.document.thing.to === subjectId || !event.document.thing.to);
  const mine = events.map((event, index) => ({ event, index })).filter(({ event }) => event.subject_id === subjectId || heard(event))
    .sort((a, b) => b.event.tick - a.event.tick || b.index - a.index).map(({ event }) => event);
  // A said event keeps its request under `thing` (society_things.py); a decision_applied event at the top.
  const said = new Set(mine.filter(event => event.event_kind === 'said').map(event => event.document?.thing?.request_id).filter(Boolean));
  const rows = [];
  for (const event of mine) {
    if (rows.length >= limit) break;
    const document = event.document || {};
    const time = worldTime(event.tick, startMinute)?.hhmm ?? '';
    if (event.subject_id !== subjectId) {
      rows.push({ time, what: heardRow(who(event.subject_id), document.thing.line), sub: '', requestId: null, model: null, heard: true });
    } else if (event.event_kind === 'said' && typeof document.thing?.line === 'string') {
      const model = document.thing.model ? modelName(document.thing.model) : null;
      const to = typeof document.thing.to === 'string' ? who(document.thing.to) : null;
      rows.push({ time, what: saidRow(to, document.thing.line), sub: rowSub(model ? { model, options: options(document.thing.request_id) } : { decider: document.thing.decider }), requestId: document.thing.request_id ?? null, model });
    } else if (event.event_kind === 'decision_applied' && !said.has(document.request_id)) {
      const what = typeof document.chose === 'string' && document.chose ? document.chose.charAt(0).toUpperCase() + document.chose.slice(1) : wordGoal(document);
      if (!what) continue;
      const model = document.model ? modelName(document.model) : null;
      rows.push({ time, what, sub: rowSub(model ? { model, options: options(document.request_id) } : { decider: document.origin }), requestId: document.request_id ?? null, model });
    } else if (event.event_kind === 'goal_selected' && document.reason !== 'chosen_by_their_model') {
      const what = wordGoal(document);
      if (what) rows.push({ time, what, sub: rowSub(null), requestId: null, model: null });
    }
  }
  return rows;
}
