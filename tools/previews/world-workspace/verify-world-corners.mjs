import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { clockLine, worldTime } from './world-clock.mjs';
import { wakesHints, worldKey } from './world-keys.mjs';
import { CORNER_WORDS, NOTE_WORDS, availableHints } from './world-words.mjs';

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
assert.equal(worldKey(key('Escape'), ground), 'leave');
assert.equal(worldKey(key('KeyP'), ground), 'play');
assert.equal(worldKey(key('KeyP'), empty), 'silence', 'no clock, no P (K5)');
assert.equal(worldKey(key('KeyP', { repeat: true }), ground), 'silence');
assert.equal(worldKey(key('Tab'), ground), 'pass');
assert.equal(worldKey(key('Enter'), ground, true), 'pass');
assert.equal(worldKey(key('Enter'), ground), 'silence');
// H opens History where it opens, once a press (MOTION's 1); elsewhere it stays silent (K8).
const remembered = { ...ground, history: true };
assert.equal(worldKey(key('KeyH'), remembered), 'history');
assert.equal(worldKey(key('KeyH', { repeat: true }), remembered), 'silence');
assert.equal(worldKey(key('KeyH', { metaKey: true }), remembered), 'quiet');
assert.equal(worldKey(key('KeyH'), { ...ground, history: false }), 'silence');
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

// The words are WORDS.md's: sentence case, no banned word, no em dash.
for (const line of [...Object.values(CORNER_WORDS), ...Object.values(NOTE_WORDS)]) {
  assert.match(line, /^[A-Z]/u, line);
  assert.doesNotMatch(line, /\b(entity|session|provider|payload|context)\b/iu, line);
}
for (const file of ['world-clock.mjs', 'world-keys.mjs', 'world-words.mjs', 'world-corners.ts', 'contextual-world.ts', 'contextual-world.css']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

export default true;
