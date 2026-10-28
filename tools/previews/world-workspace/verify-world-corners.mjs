import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { clockLine, worldTime } from './world-clock.mjs';
import { wakesHints, worldKey } from './world-keys.mjs';
import { CORNER_WORDS, NOTE_WORDS, PEOPLE_WORDS, availableHints, bringInRefused, nowhereLine, peopleLine, withoutCornerKeys } from './world-words.mjs';
import { PEOPLE_TIMING, mountPeople } from './world-people.mjs';

// The clock: a tick is a minute after the society's first; the first day reads as Day 1.
assert.deepEqual(worldTime(0, 360), { minuteOfDay: 360, day: 1, hhmm: '06:00' });
assert.deepEqual(worldTime(75, 360), { minuteOfDay: 435, day: 1, hhmm: '07:15' });
assert.deepEqual(worldTime(1080, 360), { minuteOfDay: 0, day: 2, hhmm: '00:00' });
assert.deepEqual(worldTime(1439, 0), { minuteOfDay: 1439, day: 1, hhmm: '23:59' });
for (const [tick, start] of [[null, 360], [3, null], [-1, 360], [3, 1440], [1.5, 360], [3, NaN]]) assert.equal(worldTime(tick, start), null);
assert.equal(clockLine(1, 'paused'), 'Day 1 · Paused');
assert.equal(clockLine(2, 'playing'), 'Day 2 · Playing');
assert.equal(clockLine(1, null), 'Day 1 · Paused');

// Hints draw only what works here (DESIGN's K2 and K6): no arrows, Build only where build mode is
// mounted, History only where H opens it; flying has its own keys.
const words = (list) => list.map((hint) => hint.word);
assert.deepEqual(words(availableHints({ flying: false, build: true, history: false })), ['Move', 'Sprint', 'Look', 'Fly', 'Inspect', 'Build']);
assert.deepEqual(words(availableHints({ flying: false, build: false, history: false })), ['Move', 'Sprint', 'Look', 'Fly', 'Inspect']);
assert.deepEqual(words(availableHints({ flying: false, build: true, history: true })), ['Move', 'Sprint', 'Look', 'Fly', 'Inspect', 'Build', 'History']);
assert.deepEqual(words(availableHints({ flying: true, build: true, history: true })), ['Move', 'Up', 'Down', 'Sprint', 'Speed']);
assert.equal(availableHints({ flying: true }).at(-1).gauge, true);
const walking = availableHints({ flying: false, build: true, history: false });
assert.deepEqual(walking[0].keys, ['W', 'A', 'S', 'D']);
assert.equal(walking.findIndex((hint) => hint.gapBefore), 3);
assert.ok(walking.every((hint) => hint.keys === 'mouse-click' || hint.keys.every((key) => !key.startsWith('Arrow'))));

// Every key's fate in the world (section 9, K1 and K8).
const key = (code, extra = {}) => ({ code, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, ...extra });
const ground = { flying: false, clock: true }, air = { flying: true, clock: true }, empty = { flying: false, clock: false };
for (const code of ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowLeft', 'ShiftLeft', 'KeyF']) assert.equal(worldKey(key(code), ground), 'move', code);
assert.equal(worldKey(key('Space'), ground), 'silence', 'Space is silent on the ground (K1)');
assert.equal(worldKey(key('KeyC'), ground), 'silence');
assert.equal(worldKey(key('Space'), air), 'move');
assert.equal(worldKey(key('KeyC'), air), 'move');
assert.equal(worldKey(key('KeyE'), ground), 'inspect');
assert.equal(worldKey(key('KeyE', { repeat: true }), ground), 'silence');
// Under the talking scene the reticle and the look tag are hidden, so E chooses nobody there.
assert.equal(worldKey(key('KeyE'), { ...ground, scene: true }), 'silence', 'E chooses nobody under the scene');
assert.equal(worldKey(key('KeyE'), { ...ground, scene: false }), 'inspect');
assert.equal(worldKey(key('Escape'), ground), 'leave');
assert.equal(worldKey(key('KeyP'), ground), 'play');
assert.equal(worldKey(key('KeyP'), empty), 'silence', 'no clock, no P (K5)');
assert.equal(worldKey(key('KeyP', { repeat: true }), ground), 'silence');
// Where nobody lives yet and the clock's corner offers it, P brings people in (K13); once they live
// here the clock takes P; while they come in, or with nowhere to go, the corner offers nothing and P is silent.
const welcoming = { ...empty, bringIn: true };
assert.equal(worldKey(key('KeyP'), welcoming), 'bring-in');
assert.equal(worldKey(key('KeyP', { repeat: true }), welcoming), 'silence');
assert.equal(worldKey(key('KeyP', { metaKey: true }), welcoming), 'quiet');
assert.equal(worldKey(key('KeyP'), { ...ground, bringIn: true }), 'play');
assert.equal(worldKey(key('KeyP'), { ...empty, bringIn: false }), 'silence');
assert.equal(worldKey(key('Tab'), ground), 'pass');
assert.equal(worldKey(key('Enter'), ground, true), 'pass');
assert.equal(worldKey(key('Enter'), ground), 'silence');
// H opens History where it opens, once a press (MOTION's 1); elsewhere it stays silent (K8).
const remembered = { ...ground, history: true };
assert.equal(worldKey(key('KeyH'), remembered), 'history');
assert.equal(worldKey(key('KeyH', { repeat: true }), remembered), 'silence');
assert.equal(worldKey(key('KeyH', { metaKey: true }), remembered), 'quiet');
assert.equal(worldKey(key('KeyH'), { ...ground, history: false }), 'silence');
// X opens and closes the data view where it works (a made town), and is silent elsewhere.
assert.equal(worldKey(key('KeyX'), { ...ground, data: true }), 'data');
assert.equal(worldKey(key('KeyX', { repeat: true }), { ...ground, data: true }), 'silence');
assert.equal(worldKey(key('KeyX', { metaKey: true }), { ...ground, data: true }), 'quiet');
assert.equal(worldKey(key('KeyX'), ground), 'silence', 'no data view here, no X');
// The old shell's keys never reach it: silenced, or for a combination stopped with the browser's own
// shortcut kept (K8).
for (const code of ['KeyH', 'KeyK', 'KeyI', 'KeyM', 'KeyO', 'KeyR', 'KeyG', 'Backspace', 'Slash']) assert.equal(worldKey(key(code), ground), 'silence', code);
assert.equal(worldKey(key('Slash', { shiftKey: true }), ground), 'silence', '?');
assert.equal(worldKey(key('KeyK', { metaKey: true }), ground), 'quiet');
assert.equal(worldKey(key('KeyK', { ctrlKey: true }), ground), 'quiet');
assert.equal(worldKey(key('KeyW', { altKey: true }), ground), 'quiet');
assert.equal(wakesHints(key('KeyF')), true);
assert.equal(wakesHints(key('KeyB')), true);
assert.equal(wakesHints(key('KeyH')), true);
assert.equal(wakesHints(key('KeyK')), false);
assert.equal(wakesHints(key('KeyW', { metaKey: true })), false);

// Bringing people in (K13): the corner's words as WORDS.md has them, the pill's line after, and what a refusal shows.
assert.deepEqual({ ...PEOPLE_WORDS }, {
  nobodyYet: 'Nobody lives here yet', bringIn: 'Bring People In', bringing: 'Bringing people in\u2026',
  nowhere: 'People need somewhere', nowhereSecond: 'to rest or visit nearby', build: 'Build',
  invented: 'invented for this world',
});
assert.deepEqual(bringInRefused({ status: 409, code: 'no_reachable_targets' }), { corner: 'nowhere', note: null });
assert.deepEqual(bringInRefused({ status: 409, code: 'society_engine_differs' }), { corner: 'offer', note: 'The world changed a moment ago, so nobody came in. Try again.' });
assert.deepEqual(bringInRefused({ status: 424, code: 'unavailable_society_input' }), { corner: 'offer', note: 'People cannot come in right now. Try again in a moment.' });
assert.deepEqual(bringInRefused({ status: 403, code: 'forbidden' }), { corner: 'offer', note: 'People could not be brought in. Try again.' });
assert.deepEqual(bringInRefused(new Error('offline')), { corner: 'offer', note: 'People could not be brought in. Try again.' });
assert.deepEqual(bringInRefused(undefined), { corner: 'offer', note: 'People could not be brought in. Try again.' });
// While the corner draws Build, the hint row leaves out its own B and nothing else; a corner key the row lacks changes nothing.
assert.deepEqual(words(withoutCornerKeys(availableHints({ flying: false, build: true, history: true }), ['B'])), ['Move', 'Sprint', 'Look', 'Fly', 'Inspect', 'History']);
assert.deepEqual(words(withoutCornerKeys(availableHints({ flying: false, build: false, history: true }), ['B'])), ['Move', 'Sprint', 'Look', 'Fly', 'Inspect', 'History']);
assert.deepEqual(withoutCornerKeys(availableHints({ flying: true }), ['B']), availableHints({ flying: true }));
for (const line of [PEOPLE_WORDS.nobodyYet, PEOPLE_WORDS.bringIn, PEOPLE_WORDS.bringing, PEOPLE_WORDS.nowhere, PEOPLE_WORDS.build]) assert.match(line, /^[A-Z]/u, line);

// The top pill's people line (R-WORLD-BUILD-SHEET section 2): the count, "now" for a minute after arrival.
assert.equal(peopleLine(24), '24 people live here');
assert.equal(peopleLine(1), '1 person lives here');
assert.equal(peopleLine(24, { arrived: true }), '24 people now live here, invented for this world');
assert.equal(peopleLine(1, { arrived: true }), '1 person now lives here, invented for this world');
for (const count of [0, -1, 1.5, null, undefined, NaN]) { assert.equal(peopleLine(count), null); assert.equal(peopleLine(count, { arrived: true }), null); }
assert.equal(nowhereLine(), 'People need somewhere to rest or visit nearby');
assert.equal(PEOPLE_TIMING.arrivedMs, 60_000);

// The people state the pill and the clock read (world-people.mjs), driven by a stand-in for the
// corners' people read: its society, its population, and a bring-in that answers when told.
function standIn(society = 'absent', { plays = true } = {}) {
  const read = { society, population: null, mode: null };
  const asked = [], played = [];
  return {
    read, asked, played,
    people: {
      clock: () => ({ ...read, minute: null, busy: false }),
      bringIn: () => new Promise((resolve, reject) => asked.push({ resolve, reject })),
      play: async () => { played.push(read.mode); if (plays) read.mode = 'playing'; },
    },
  };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const offer = { state: 'offer', keys: ['P'], word: 'Bring People In' };
{
  // Where nobody lives yet and this page may bring people in: the pill says so, the clock offers P.
  const world = standIn(), notes = [];
  let at = 1000, changes = 0;
  const people = mountPeople({ people: world.people, canBringIn: true, canBuild: true, note: (words) => notes.push(words), now: () => at });
  people.onChange(() => { changes++; });
  assert.equal(people.line(), 'Nobody lives here yet');
  assert.deepEqual(people.clockOffer(), offer);
  assert.equal(people.offersBringIn(), true);
  // P: the clock waits while they come in, P is silent and a second press asks nothing more.
  people.bringIn(); people.bringIn();
  assert.equal(world.asked.length, 1);
  assert.deepEqual(people.clockOffer(), { state: 'bringing', keys: null, word: 'Bringing people in…' });
  assert.equal(people.offersBringIn(), false);
  assert.equal(people.line(), 'Nobody lives here yet');
  assert.equal(changes, 1);
  // They arrive: the clock takes its place, one note, and the pill says "now" for a minute; they arrive
  // walking (F2): the world is played once, as P would.
  Object.assign(world.read, { society: 'present', population: 24, mode: 'paused' });
  world.asked[0].resolve(); await settle(); await settle();
  assert.equal(people.clockOffer(), null);
  assert.deepEqual(notes, [], 'the pill says it; no note repeats it');
  assert.deepEqual(world.played, ['paused']);
  assert.equal(world.read.mode, 'playing');
  assert.equal(people.line(), '24 people now live here, invented for this world');
  at += PEOPLE_TIMING.arrivedMs - 1;
  assert.equal(people.line(), '24 people now live here, invented for this world');
  at += 1;
  assert.equal(people.line(), '24 people live here');
  assert.equal(changes, 2);
}
{
  // Nowhere for them to go: the pill says so, the clock offers Build, no note; build mode offers again.
  const world = standIn(), notes = [];
  const people = mountPeople({ people: world.people, canBringIn: true, canBuild: true, note: (words) => notes.push(words) });
  people.bringIn();
  world.asked[0].reject({ status: 409, code: 'no_reachable_targets' }); await settle();
  assert.deepEqual(people.clockOffer(), { state: 'nowhere', keys: ['B'], word: 'Build' });
  assert.equal(people.line(), 'People need somewhere to rest or visit nearby');
  assert.equal(people.offersBringIn(), false);
  people.bringIn();
  assert.equal(world.asked.length, 1, 'with nowhere to go, P asks nothing');
  assert.deepEqual(notes, []);
  people.building();
  assert.deepEqual(people.clockOffer(), offer);
  assert.equal(people.line(), 'Nobody lives here yet');
  // A page that cannot build offers nothing where people have nowhere to go.
  const unbuilt = standIn();
  const without = mountPeople({ people: unbuilt.people, canBringIn: true, canBuild: false, note: () => {} });
  without.bringIn();
  unbuilt.asked[0].reject({ status: 409, code: 'no_reachable_targets' }); await settle();
  assert.equal(without.clockOffer(), null);
}
{
  // A world already playing when they arrive is left as it is; one that will not start playing says so as P does.
  const playing = standIn();
  const already = mountPeople({ people: playing.people, canBringIn: true, canBuild: true, note: () => {} });
  already.bringIn();
  Object.assign(playing.read, { society: 'present', population: 3, mode: 'playing' });
  playing.asked[0].resolve(); await settle(); await settle();
  assert.deepEqual(playing.played, []);
  const stuck = standIn('absent', { plays: false }), notes = [];
  const refusing = mountPeople({ people: stuck.people, canBringIn: true, canBuild: true, note: (words) => notes.push(words) });
  refusing.bringIn();
  Object.assign(stuck.read, { society: 'present', population: 3, mode: 'paused' });
  stuck.asked[0].resolve(); await settle(); await settle();
  assert.deepEqual([stuck.played, notes], [['paused'], [NOTE_WORDS.playRefused]]);
}
for (const [refusal, words] of [
  [{ status: 409, code: 'society_engine_differs' }, NOTE_WORDS.peopleChanged],
  [{ status: 424, code: 'unavailable_society_input' }, NOTE_WORDS.peopleNotNow],
  [new Error('offline'), NOTE_WORDS.peopleRefused],
]) {
  // Any other refusal: one note, and the clock offers again.
  const world = standIn(), notes = [];
  const people = mountPeople({ people: world.people, canBringIn: true, canBuild: true, note: (said) => notes.push(said) });
  people.bringIn();
  world.asked[0].reject(refusal); await settle();
  assert.deepEqual(notes, [words]);
  assert.deepEqual(people.clockOffer(), offer);
}
{
  // An answer that leaves nobody living here is a refusal; a bring-in that throws at once is one too.
  const world = standIn(), notes = [];
  const people = mountPeople({ people: world.people, canBringIn: true, canBuild: true, note: (said) => notes.push(said) });
  people.bringIn();
  world.asked[0].resolve(); await settle();
  assert.deepEqual(notes, [NOTE_WORDS.peopleRefused]);
  assert.deepEqual(people.clockOffer(), offer);
  const thrown = standIn();
  thrown.people.bringIn = () => { throw Object.assign(new Error('refused'), { status: 424 }); };
  const throwing = mountPeople({ people: thrown.people, canBringIn: true, canBuild: true, note: (said) => notes.push(said) });
  throwing.bringIn(); await settle();
  assert.equal(notes.at(-1), NOTE_WORDS.peopleNotNow);
}
{
  // The read-only observer, or a page that may not change the world: the pill says nobody lives here, the clock offers nothing.
  const world = standIn();
  const people = mountPeople({ people: world.people, canBringIn: false, canBuild: true, note: () => {} });
  assert.equal(people.line(), 'Nobody lives here yet');
  assert.equal(people.clockOffer(), null);
  people.bringIn();
  assert.equal(world.asked.length, 0);
  // People not read yet, or no read at all: no line and nothing offered.
  for (const society of ['unconnected', 'loading', 'unavailable']) {
    const unread = mountPeople({ people: standIn(society).people, canBringIn: true, canBuild: true, note: () => {} });
    assert.equal(unread.line(), null, society);
    assert.equal(unread.clockOffer(), null, society);
  }
  const none = mountPeople({ people: null, canBringIn: true, canBuild: true, note: () => {} });
  assert.equal(none.line(), null);
  assert.equal(none.clockOffer(), null);
  // People living here already: the count, never "now", and the clock in its own place.
  const lived = standIn('present');
  lived.read.population = 1;
  const living = mountPeople({ people: lived.people, canBringIn: true, canBuild: true, note: () => {} });
  assert.equal(living.line(), '1 person lives here');
  assert.equal(living.clockOffer(), null);
}

// The words are WORDS.md's: sentence case, no banned word, no em dash.
for (const line of [...Object.values(CORNER_WORDS), ...Object.values(NOTE_WORDS)]) {
  assert.match(line, /^[A-Z]/u, line);
  assert.doesNotMatch(line, /\b(entity|session|provider|payload|context)\b/iu, line);
}
for (const file of ['world-clock.mjs', 'world-keys.mjs', 'world-words.mjs', 'world-people.mjs', 'world-corners.ts', 'contextual-world.ts', 'contextual-world.css']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

export default true;
