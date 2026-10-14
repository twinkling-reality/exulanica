import assert from 'node:assert/strict';
import { MAX_YAW, keyAction, moveWords, movedNote, refusalWords, removeQuestion, removedNote, snapped, thingName, titled, turned, undoRefusalWords, undoneNote } from './build-words.mjs';

// A placed thing is called by its kind, never by its id or digest.
assert.equal(thingName({ kind: { kind: 'lamp_post', version: 1, sha256: 'a'.repeat(64) } }), 'lamp post');
assert.equal(titled(thingName({ kind: { kind: 'well', version: 2 } })), 'Well');
assert.equal(thingName({ kind: { source: 'workspace', sha256: 'b'.repeat(64) } }), 'creature you made');
assert.equal(thingName(null), 'thing');

// Where a thing may not stand, the server's own sentence; codes become sentences, never shown as codes.
assert.equal(refusalWords('thing_landing_blocked', 'That spot is in the water basin.'), 'Not here: that spot is in the water basin.');
assert.equal(refusalWords('stale_object_base', 'base state 0000 is stale'), 'Someone changed this world a moment ago. Look again and try once more.');
assert.equal(refusalWords('something_new', 'it_was_refused'), 'That could not be done. Nothing changed.');
assert.equal(refusalWords('http_404', 'Not Found'), 'That could not be done. Nothing changed.');
for (const words of [refusalWords('http_403', ''), refusalWords(null, ''), removeQuestion('well'), removedNote('well')]) assert.doesNotMatch(words, /_|[0-9a-f]{12}/);

// What an undo did, from its preview.
const well = { kind: { kind: 'well', version: 2 } };
assert.equal(undoneNote({ undoes: { kind: 'remove_thing' }, before: { ...well, removed: true }, after: well }), 'Brought back the well.');
assert.equal(undoneNote({ undoes: { kind: 'move_thing' }, before: well, after: well }), 'Put the well back where it was.');
assert.equal(undoneNote({ undoes: { kind: 'add_thing' }, before: well, after: null }), 'Took away the well that was placed.');
assert.equal(undoneNote({ undoes: { kind: 'add_object' } }), 'Undid the last change.');
assert.equal(undoRefusalWords('invalid_object_state', 'nothing to undo'), 'Nothing left to undo.');

// A move in words: east and south as the region's frame names them, a turn in whole degrees.
assert.equal(moveWords({ x: 0, z: 0, yaw: 0 }, { x: 6500, z: -2000, yaw: 785_398 }), '6.5 m east, 2 m north, turned 45°');
assert.equal(moveWords({ x: 1000, z: 1000, yaw: 100 }, { x: 1000, z: 4000, yaw: 100 }), '3 m south');
assert.equal(moveWords({ x: 0, z: 0, yaw: 0 }, { x: -500, z: 0, yaw: 0 }), '0.5 m west');
assert.equal(moveWords({ x: 0, z: 0, yaw: 0 }, { x: 0, z: 0, yaw: 3_141_593 }), 'turned round');
assert.equal(moveWords({ x: 0, z: 0, yaw: 0 }, { x: 20, z: 0, yaw: 0 }), 'where it was');
assert.equal(movedNote('bench', '6.5 m east'), 'Moved the bench 6.5 m east.');
// Snapping: half metres and 15 degree steps unless free; a yaw stays within one revolution.
assert.equal(snapped(1249, false), 1000);
assert.equal(snapped(1251, false), 1500);
assert.equal(snapped(1251.4, true), 1251);
assert.equal(turned(0, 15, false), 261_799);
assert.equal(turned(0, -15, false), 6_021_386);
assert.equal(turned(6_100_000, 15, false), 0);
assert.equal(turned(100_000, 1, true), 117_453);
for (const yaw of [0, 1, 3_000_000, MAX_YAW]) for (const step of [15, -15, 1, -1]) {
  const next = turned(yaw, step, step === 1 || step === -1);
  assert.ok(Number.isSafeInteger(next) && next >= 0 && next <= MAX_YAW, `${yaw} ${step} ${next}`);
}

// Keys: B switches build mode on and off from anywhere it is offered; other keys act only in it.
const key = (code, more = {}) => ({ code, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, ...more });
const off = { on: false, selected: false, confirming: false, busy: false };
const on = { ...off, on: true }, chosen = { ...on, selected: true }, asking = { ...chosen, confirming: true };
assert.equal(keyAction(off, key('KeyB')), 'toggle');
assert.equal(keyAction(on, key('KeyB')), 'toggle');
assert.equal(keyAction(on, key('KeyB', { repeat: true })), 'held');
for (const code of ['Escape', 'Backspace', 'Enter', 'KeyE', 'KeyW']) assert.equal(keyAction(off, key(code)), null, code);
assert.equal(keyAction(off, key('KeyZ', { metaKey: true })), null);
// Esc puts the question away, then lets go of the selection, then leaves build mode.
assert.equal(keyAction(asking, key('Escape')), 'cancel');
assert.equal(keyAction(chosen, key('Escape')), 'deselect');
assert.equal(keyAction(on, key('Escape')), 'leave');
// Backspace asks first; Enter answers yes only to a question.
assert.equal(keyAction(chosen, key('Backspace')), 'remove');
assert.equal(keyAction(chosen, key('Delete')), 'remove');
assert.equal(keyAction(on, key('Backspace')), 'held');
assert.equal(keyAction(asking, key('Backspace')), 'held');
assert.equal(keyAction(asking, key('Enter')), 'confirm');
assert.equal(keyAction(chosen, key('Enter')), null);
// Cmd+Z or Ctrl+Z undoes; Shift with it, Alt with it or a held key does not.
assert.equal(keyAction(on, key('KeyZ', { metaKey: true })), 'undo');
assert.equal(keyAction(on, key('KeyZ', { ctrlKey: true })), 'undo');
assert.equal(keyAction(on, key('KeyZ', { metaKey: true, shiftKey: true })), null);
assert.equal(keyAction(on, key('KeyZ', { metaKey: true, repeat: true })), null);
assert.equal(keyAction(on, key('KeyB', { altKey: true })), null);
// Walking and inspecting stay the page's.
for (const code of ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'KeyE', 'Tab']) assert.equal(keyAction(chosen, key(code)), null, code);
// Moving: [ and ] turn what is selected, with Alt for a free turn; Enter keeps only a move the
// server said may be kept; Esc puts it back; Backspace does nothing while moving.
const moving = { ...chosen, moving: true, ready: false }, keepable = { ...moving, ready: true };
assert.equal(keyAction(chosen, key('BracketLeft')), 'turn-left');
assert.equal(keyAction(chosen, key('BracketRight', { altKey: true })), 'turn-right');
assert.equal(keyAction(on, key('BracketRight')), 'held');
assert.equal(keyAction(asking, key('BracketRight')), 'held');
assert.equal(keyAction(moving, key('Enter')), 'held');
assert.equal(keyAction(keepable, key('Enter')), 'keep');
assert.equal(keyAction(keepable, key('Escape')), 'put-back');
assert.equal(keyAction(keepable, key('Backspace')), 'held');
assert.equal(keyAction(off, key('BracketLeft')), null);
assert.equal(keyAction(chosen, key('', { key: ']' })), 'turn-right');
assert.equal(keyAction(chosen, key('KeyQ', { key: ']' })), null);
// While a request is on its way nothing is sent twice, and Esc does not seem to call it back: only B acts.
const busy = { ...asking, busy: true };
assert.equal(keyAction(busy, key('Enter')), 'held');
assert.equal(keyAction(busy, key('Backspace')), 'held');
assert.equal(keyAction(busy, key('KeyZ', { metaKey: true })), null);
assert.equal(keyAction(busy, key('Escape')), 'held');
assert.equal(keyAction(busy, key('KeyB')), 'toggle');
console.log('Build words checks passed: names by kind, refusals as sentences, undo notes, move words, snapping, keys per state.');
