import assert from 'node:assert/strict';
import { HISTORY, MAX_YAW, buildHints, cardPrompts, changeWords, clockWords, dayWords, keyAction, madeLine, moveWords, movedNote, nothingInView, placedLine, redoRefusalWords, redoneNote, refusalWords, removeLine, removeTitle, removedNote, snapped, thingName, titled, turned, undoRefusalWords, undoneNote } from './build-words.mjs';

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
for (const words of [refusalWords('http_403', ''), refusalWords(null, ''), removeTitle('well'), removeLine(), removedNote('well')]) assert.doesNotMatch(words, /_|[0-9a-f]{12}/);
// The remove question as the card draws it: the question, then what it does.
assert.equal(removeTitle('bench'), 'Remove the bench?');
assert.equal(removeLine(), 'Nobody can use it from the next minute.');

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
// A turn alone is said as a turn; a move with a turn as a move (History and pull requests read the same).
assert.equal(movedNote('bench', moveWords({ x: 0, z: 0, yaw: 0 }, { x: 0, z: 0, yaw: 1_570_796 })), 'Turned the bench 90°.');
assert.equal(movedNote('bench', moveWords({ x: 0, z: 0, yaw: 0 }, { x: 0, z: 0, yaw: 3_141_593 })), 'Turned the bench round.');
assert.equal(movedNote('bench', moveWords({ x: 0, z: 0, yaw: 0 }, { x: -3500, z: 0, yaw: 261_799 })), 'Moved the bench 3.5 m west, turned 15°.');
// The card's line for a placed thing, which the chosen card outside build mode reads too.
assert.equal(placedLine(), 'Placed in this world');
// A part made with the world says so, with the area it stands in (frame 13).
assert.equal(madeLine('lower pools'), 'Made with this world · Lower pools');
assert.equal(madeLine(''), 'Made with this world');
// A made part's refusals, and the land's under it, are the server's own sentences.
assert.equal(refusalWords('part_blocked', 'Not here: it would stand on the farmhouse.'), 'Not here: it would stand on the farmhouse.');
assert.equal(refusalWords('part_houses_people', 'Not removed: Ada Lane 1 lives there. The farmhouse can be moved instead.'), 'Not removed: Ada Lane 1 lives there. The farmhouse can be moved instead.');
assert.equal(refusalWords('landform_water_spills', 'Not here: water would spill out there.'), 'Not here: water would spill out there.');
assert.equal(refusalWords('part_blocked', ''), 'That could not be done. Nothing changed.');
// History names a made part's change by the part, from the parts read.
const partLog = [
  { edit_id: 'p1', kind: 'transform_element', element_id: 'part:barn-id', thing_id: null },
  { edit_id: 'p2', kind: 'suppress_element', element_id: 'part:pond-id', thing_id: null },
  { edit_id: 'p3', kind: 'undo', undone_edit_id: 'p2', element_id: null, thing_id: null },
];
const partName = (id) => ({ 'barn-id': 'barn', 'pond-id': 'pond' })[id] ?? null;
assert.deepEqual(partLog.map(edit => changeWords(edit, partLog, () => null, partName)), ['Moved the barn', 'Removed the pond', 'Took back: removed the pond']);
assert.equal(changeWords({ edit_id: 'p4', kind: 'transform_element', element_id: 'part:gone', thing_id: null }, [], () => null), 'Moved a part of the world');
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
// Cmd+Z or Ctrl+Z undoes, with Shift redoes; Alt with it or a held key does neither.
assert.equal(keyAction(on, key('KeyZ', { metaKey: true })), 'undo');
assert.equal(keyAction(on, key('KeyZ', { ctrlKey: true })), 'undo');
assert.equal(keyAction(on, key('KeyZ', { metaKey: true, shiftKey: true })), 'redo');
assert.equal(keyAction(on, key('KeyZ', { metaKey: true, altKey: true })), null);
assert.equal(keyAction(on, key('KeyZ', { metaKey: true, repeat: true })), null);
assert.equal(keyAction(on, key('KeyB', { altKey: true })), null);
// Walking and inspecting stay the page's.
for (const code of ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'KeyE']) assert.equal(keyAction(chosen, key(code)), null, code);
// Tab chooses the next placed thing in view, Shift+Tab the one before; a focused control of build
// mode, a question or a move keeps Tab the page's.
assert.equal(keyAction(on, key('Tab')), 'next');
assert.equal(keyAction(chosen, key('Tab', { shiftKey: true })), 'previous');
assert.equal(keyAction({ ...chosen, focused: true }, key('Tab')), null);
assert.equal(keyAction(asking, key('Tab')), null);
assert.equal(keyAction(off, key('Tab')), null);
// H shows the changes; Esc closes them before anything else.
assert.equal(keyAction(on, key('KeyH')), 'changes');
assert.equal(keyAction({ ...asking, changes: true }, key('Escape')), 'close-changes');
assert.equal(keyAction(off, key('KeyH')), null);
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
// A redo is said by what it did again, read from the documents.
const at = (x, removed = false) => ({ kind: { kind: 'well', version: 2 }, removed, transform: { x_mm: x, z_mm: 0, yaw_microradians: 0 } });
assert.equal(redoneNote({ before: at(0), after: at(0, true) }), 'Removed the well again.');
assert.equal(redoneNote({ before: null, after: at(0) }), 'Placed the well again.');
assert.equal(redoneNote({ before: at(0), after: at(2000) }), 'Moved the well again.');
assert.equal(redoneNote({}), 'Did the change again.');
assert.equal(redoRefusalWords('invalid_object_state', ''), 'Nothing left to do again.');
// The changes list: each edit in words, an undo by what it took back, a redo by what it did again.
const log = [
  { edit_id: 'a', kind: 'add_thing', thing_id: 'well:1', undone_edit_id: null },
  { edit_id: 'b', kind: 'move_thing', thing_id: 'well:1', undone_edit_id: null },
  { edit_id: 'c', kind: 'undo', thing_id: 'well:1', undone_edit_id: 'b' },
  { edit_id: 'd', kind: 'undo', thing_id: 'well:1', undone_edit_id: 'c' },
  { edit_id: 'e', kind: 'remove_thing', thing_id: 'gone:1', undone_edit_id: null },
  { edit_id: 'f', kind: 'move_object', thing_id: null, undone_edit_id: null },
  { edit_id: 'g', kind: 'set_look', thing_id: null, undone_edit_id: null },
];
const name = (id) => (id === 'well:1' ? 'well' : null);
assert.deepEqual(log.map(edit => changeWords(edit, log, name)), [
  'Placed the well', 'Moved the well', 'Took back: moved the well', 'Moved the well again',
  'Removed a thing', 'Moved an object', 'Changed the world',
]);
for (const edit of log) assert.doesNotMatch(changeWords(edit, log, name), /_|well:1|gone:1/u);
// When, in plain words.
// History's time column: the clock time in this browser's zone, as the page's mono column holds it.
const recorded = new Date(2026, 9, 14, 7, 5);
assert.equal(clockWords(recorded.toISOString()), '07:05');
assert.equal(clockWords('not a time'), '');
// History's day headings: today's changes under "Today", earlier ones under their date.
assert.equal(dayWords(new Date(2026, 9, 14, 7, 5).toISOString(), new Date(2026, 9, 14, 23, 0).getTime()), 'Today');
assert.equal(dayWords(new Date(2026, 9, 13, 22, 40).toISOString(), new Date(2026, 9, 14, 0, 10).getTime()), '13 Oct');
assert.equal(dayWords('not a time', Date.now()), '');
// The keys build mode offers, in the design's words and order (WORDS.md, frames 13 and 14).
const said = (list) => list.map(({ keys, word }) => [Array.isArray(keys) ? keys.join(' ') : keys, word]);
assert.deepEqual(said(buildHints({ moving: false })), [['mouse-click', 'Select'], ['Tab', 'Next'], ['⌘Z', 'Undo'], ['H', 'History']]);
assert.deepEqual(said(buildHints({ moving: true })), [['mouse', 'Drag to move'], ['[ ]', 'Turn'], ['Alt', 'Free']]);
// The card's prompts in each state (frames 13 to 16), each pressing what its key does.
assert.deepEqual(said(cardPrompts({})), [['mouse', 'Drag to move'], ['[ ]', 'Turn'], ['Del', 'Remove']]);
assert.deepEqual(said(cardPrompts({ moving: true, ready: true })), [['Enter', 'Keep'], ['Esc', 'Put it back']]);
assert.equal(cardPrompts({ moving: true, ready: false })[0].disabled, true);
assert.deepEqual(said(cardPrompts({ moving: true, refused: true })), [['Esc', 'Put it back']]);
assert.deepEqual(said(cardPrompts({ confirming: true })), [['Enter', 'Remove'], ['Esc', 'Keep it']]);
// After a removal was refused (people live or work there), the card offers moving it, not removing it again.
assert.deepEqual(said(cardPrompts({ removeRefused: true })), [['mouse', 'Drag to move'], ['[ ]', 'Turn']]);
const keyOf = { Enter: 'Enter', Esc: 'Escape', Del: 'Delete', '[ ]': 'BracketRight' };
const flagsOf = (state) => ({ on: true, selected: true, confirming: false, moving: false, ready: false, busy: false, changes: false, focused: false, ...state });
for (const state of [{}, { moving: true, ready: true }, { moving: true, refused: true }, { confirming: true }]) {
  for (const prompt of cardPrompts(state)) {
    if (!prompt.action || prompt.disabled) continue;
    const code = keyOf[Array.isArray(prompt.keys) ? prompt.keys.join(' ') : prompt.keys];
    assert.equal(keyAction(flagsOf(state), { code, key: '', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false }), prompt.action, `${prompt.word} presses what its key does`);
  }
}
assert.equal(nothingInView(), 'No placed things in view. Walk closer to one.');
assert.deepEqual({ ...HISTORY }, { title: 'History', today: 'Today', empty: 'Nothing has been changed yet.' });
console.log('Build words checks passed: names by kind, refusals as sentences, undo notes, move words, snapping, redo, the changes list, keys per state.');
