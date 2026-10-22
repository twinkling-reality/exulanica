import assert from 'node:assert/strict';
import { BUSY, HISTORY, MAX_YAW, TRAY, TURN_DEGREES, buildKeys, createKindLabels, changeParts, changeWords, clockWords, dayWords, facingYaw, heldRows, keyAction, namesTogether, nothingInView, placedLine, previewParts, redoRefusalWords, refusalWords, removeLine, removeTitle, snapped, thingName, titled, turned, turnedInPlace, undoRefusalWords } from './build-words.mjs';
import { youChangeWords } from './history-words.mjs';

// What build mode's note says: History's sentence for a change build mode made, or for an undo's or a redo's preview.
const did = (edit, name, partName = () => null) => youChangeWords(changeParts(edit, [], () => name, partName));
const undone = (change, ...names) => youChangeWords(previewParts(change, false, ...names));
const redone = (change, ...names) => youChangeWords(previewParts(change, true, ...names));

// A placed thing is called by its kind, never by its id or digest.
assert.equal(thingName({ kind: { kind: 'lamp_post', version: 1, sha256: 'a'.repeat(64) } }), 'lamp post');
assert.equal(titled(thingName({ kind: { kind: 'well', version: 2 } })), 'Well');
assert.equal(thingName(null), 'thing');
// A creature its workspace made is called by its own label, its maker's words, in a title and in a
// sentence; until the label is read, or where its kind is gone, "creature" (rulings J20, J23).
const made = { kind: { source: 'workspace', sha256: 'b'.repeat(64) } };
const label = (kind) => (kind.sha256 === 'b'.repeat(64) ? 'Two legged two armed creature' : null);
assert.equal(titled(thingName(made, label)), 'Two legged two armed creature');
assert.equal(thingName(made, label), 'two legged two armed creature');
assert.equal(thingName(made), 'creature');
assert.equal(titled(thingName(made, () => null)), 'Creature');
assert.equal(thingName(made, () => '   '), 'creature');
assert.equal(thingName(made, () => 'NASA rover'), 'NASA rover');
for (const name of [thingName(made), thingName(made, label)]) assert.doesNotMatch(name, /you made/);
// A thing whose kind its workspace no longer holds is "creature", and its label is never asked for.
assert.equal(thingName({ ...made, gone: true }, () => { throw Error('asked'); }), 'creature');
// The labels are read once by digest; a failed read is asked again only after the page's quiet-read
// pause, so a passing failure never leaves "creature" for good; each label that lands is told.
{
  let clock = 0, answers = [Promise.reject(Error('blip')), Promise.resolve({ label: 'Two legged two armed creature' })];
  const asked = [];
  const labels = createKindLabels((path) => { asked.push(path); return answers.shift(); }, (document) => document?.label ?? null, { now: () => clock });
  const told = [];
  labels.listen((digest) => told.push(digest));
  const kind = made.kind;
  const settle = () => new Promise((done) => setTimeout(done, 0));
  assert.equal(labels.label(kind), null);
  await settle(); await settle();
  assert.deepEqual(asked, ['/things/kinds/' + 'b'.repeat(64)]);
  assert.equal(labels.label(kind), null, 'a failed read says nothing yet');
  await settle();
  assert.equal(asked.length, 1, 'asked again before the pause');
  clock += 1000;
  assert.equal(labels.label(kind), null);
  await settle(); await settle();
  assert.equal(asked.length, 2, 'asked again after the pause');
  assert.equal(labels.label(kind), 'Two legged two armed creature');
  assert.deepEqual(told, ['b'.repeat(64)]);
  assert.equal(titled(thingName(made, labels.label)), 'Two legged two armed creature');
  assert.equal(labels.label({ source: 'workspace', sha256: 'not a digest' }), null);
  assert.equal(asked.length, 2, 'a label in memory, or no digest, is not read');
}
// The same name in an undo's note and a redo's, as the card says it.
const placedMade = { ...made, removed: false, transform: { x_mm: 0, z_mm: 0, yaw_microradians: 0 } };
assert.equal(undone({ undoes: { kind: 'move_thing' }, before: placedMade, after: placedMade }, () => null, label), 'You put the two legged two armed creature back where it was');
assert.equal(undone({ undoes: { kind: 'add_thing' }, before: placedMade, after: null }), 'You took away the creature you had placed');
assert.equal(redone({ before: placedMade, after: { ...placedMade, removed: true } }, () => null, label), 'You took out the two legged two armed creature again');

// Where a thing may not stand, the server's own sentence; codes become sentences, never shown as codes.
assert.equal(refusalWords('thing_landing_blocked', 'That spot is in the water basin.'), 'Not here: that spot is in the water basin.');
assert.equal(refusalWords('stale_object_base', 'base state 0000 is stale'), 'Someone changed this world a moment ago. Look again and try once more.');
assert.equal(refusalWords('something_new', 'it_was_refused'), 'That could not be done. Nothing changed.');
assert.equal(refusalWords('http_404', 'Not Found'), 'That could not be done. Nothing changed.');
for (const words of [refusalWords('http_403', ''), refusalWords(null, ''), removeTitle('well'), removeLine(true), did({ kind: 'remove_thing', thing_id: 'well:1' }, 'well')]) assert.doesNotMatch(words, /_|[0-9a-f]{12}/);
// The remove question as the card draws it: the question, then what it does.
assert.equal(removeTitle('bench'), 'Remove the bench?');
assert.equal(removeLine(true), 'Nobody can use it from the next minute.');
// Where nobody lives yet the question stands alone (ruling W13 T4).
assert.equal(removeLine(false), null);

// What an undo did, from its preview, as History says it (sheet section 7: the "You" forms, no full stop).
const well = { kind: { kind: 'well', version: 2 } };
assert.equal(undone({ undoes: { kind: 'remove_thing' }, before: { ...well, removed: true }, after: well }), 'You brought back the well');
assert.equal(undone({ undoes: { kind: 'move_thing' }, before: well, after: well }), 'You put the well back where it was');
assert.equal(undone({ undoes: { kind: 'add_thing' }, before: well, after: null }), 'You took away the well you had placed');
assert.equal(undone({ undoes: { kind: 'add_object' } }), 'You undid a change');
assert.equal(undoRefusalWords('invalid_object_state', 'nothing to undo'), 'Nothing left to undo.');

// What build mode did, said as History says it, by the edit it made.
assert.equal(did({ kind: 'add_thing', thing_id: 'bench:1' }, 'bench'), 'You placed the bench');
assert.equal(did({ kind: 'move_thing', thing_id: 'bench:1' }, 'bench'), 'You moved the bench');
assert.equal(did({ kind: 'remove_thing', thing_id: 'bench:1' }, 'bench'), 'You took out the bench');
// A thing turned where it stood (ruling W12.7) is turned, its undo turned back, in the note (build mode's pose before
// and after; an undo's or a redo's documents) as in History's row (the version read's turned_in_place); a move, with
// or without a turn, stays moved. The place is on the ground: the height follows the ground under the turned footprint.
const pose = (x_mm, z_mm, yaw_microradians, y_mm = 0) => ({ x_mm, y_mm, z_mm, yaw_microradians });
assert.deepEqual([
  turnedInPlace(pose(0, 0, 0), pose(0, 0, 261_799)), turnedInPlace(pose(0, 0, 0), pose(0, 0, 261_799, 40)),
  turnedInPlace(pose(0, 0, 0), pose(500, 0, 261_799)), turnedInPlace(pose(0, 0, 0), pose(0, 500, 261_799)),
  turnedInPlace(pose(0, 0, 0), pose(500, 0, 0)), turnedInPlace(pose(0, 0, 0), pose(0, 0, 0, 40)), turnedInPlace(undefined, pose(0, 0, 0)),
], [true, true, false, false, false, false, false]);
assert.equal(did({ kind: 'move_thing', thing_id: 'bench:1', turned_in_place: true }, 'bench'), 'You turned the bench');
assert.equal(did({ kind: 'move_thing', thing_id: 'bench:1', turned_in_place: false }, 'bench'), 'You moved the bench');
const wellAt = (...at) => ({ ...well, removed: false, transform: pose(...at) });
assert.equal(undone({ undoes: { kind: 'move_thing' }, before: wellAt(0, 0, 261_799), after: wellAt(0, 0, 0) }), 'You turned the well back');
assert.equal(undone({ undoes: { kind: 'move_thing' }, before: wellAt(500, 0, 261_799), after: wellAt(0, 0, 0) }), 'You put the well back where it was');
assert.equal(redone({ subject_id: 'well:1', before: wellAt(0, 0, 0), after: wellAt(0, 0, 261_799) }), 'You turned the well again');
assert.equal(redone({ subject_id: 'well:1', before: wellAt(0, 0, 0), after: wellAt(0, 500, 261_799) }), 'You moved the well again');
const turnLog = [{ edit_id: 'n1', kind: 'move_thing', thing_id: 'bench:1', turned_in_place: true }, { edit_id: 'n2', kind: 'undo', undone_edit_id: 'n1' }, { edit_id: 'n3', kind: 'undo', undone_edit_id: 'n2' }];
assert.deepEqual(turnLog.map(edit => changeWords(edit, turnLog, () => 'bench')), ['Turned the bench', 'Turned the bench back', 'Turned the bench again']);
// The card's line for a placed thing, which the chosen card outside build mode reads too.
assert.equal(placedLine(), 'Placed in this world');
// A change the server could not take up yet says so, in DESIGN's words (W11), whichever wait it is.
for (const code of ['kind_work_overran', 'kind_work_busy', 'kind_work_unavailable']) assert.equal(refusalWords(code, 'Ask again shortly.'), BUSY);
assert.equal(BUSY, 'The world is busy with another change. Try again in a moment.');
// People standing together near what is held, named as one (frame r13, ruling W11).
assert.equal(namesTogether(['Teo']), 'Teo');
assert.equal(namesTogether(['Teo', 'Ines']), 'Teo and Ines');
assert.equal(namesTogether(['Teo', 'Ines', 'Marco']), 'Teo, Ines and Marco');
assert.equal(namesTogether(['Teo', 'Ines', 'Marco', 'Ari']), 'Teo and 3 more');
assert.equal(namesTogether([null, 'Teo']), 'Teo and the resident');
assert.equal(namesTogether(['Teo', null, 'Ines']), 'Teo, Ines and the resident');
assert.equal(namesTogether(['Teo', null, null]), 'Teo and 2 more');
assert.equal(namesTogether([null, null]), '');
assert.equal(namesTogether([]), '');
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
  { edit_id: 'p4', kind: 'undo', undone_edit_id: 'p1', element_id: null, thing_id: null },
];
const partName = (id) => ({ 'barn-id': 'barn', 'pond-id': 'pond' })[id] ?? null;
assert.deepEqual(partLog.map(edit => changeWords(edit, partLog, () => null, partName)), ['Moved the barn', 'Removed the pond', 'Brought back the pond', 'Put the barn back where it was']);
// A made part's change, and an undone one, read the same in the note and in History's row (ruling W2).
assert.equal(did({ kind: 'transform_element', element_id: 'part:barn-id' }, 'part', partName), 'You moved the barn');
assert.equal(did({ kind: 'suppress_element', element_id: 'part:pond-id' }, 'part', partName), 'You took out the pond');
// A made part turned where it stood (W12.7 item 3), as its edit states it (0225): turned in the note and History's row,
// its undo turned back and a redo turned again, read from the version's edits by id since a part's first change has no
// pose before; a change the edits do not state is moved, never a guessed turn.
assert.equal(did({ kind: 'transform_element', element_id: 'part:barn-id', turned_in_place: true }, 'part', partName), 'You turned the barn');
const barnTurn = [
  { edit_id: 'b1', kind: 'transform_element', element_id: 'part:barn-id', turned_in_place: true },
  { edit_id: 'b2', kind: 'undo', undone_edit_id: 'b1' },
  { edit_id: 'b3', kind: 'undo', undone_edit_id: 'b2' },
];
assert.deepEqual(barnTurn.map(edit => changeWords(edit, barnTurn, () => null, partName)), ['Turned the barn', 'Turned the barn back', 'Turned the barn again']);
const barnAt = (turns) => ({ element_id: 'part:barn-id', suppressed: false, transform: turns === null ? null : { x_mm: 5000, y_mm: 0, z_mm: -7000, yaw_microradians: [0, 1_570_796, 3_141_593, 4_712_389][turns] } });
assert.equal(undone({ subject_id: 'part:barn-id', before: barnAt(2), after: null, undoes: { edit_id: 'b1', kind: 'transform_element' } }, partName, () => null, barnTurn.slice(0, 1)), 'You turned the barn back');
assert.equal(redone({ subject_id: 'part:barn-id', before: null, after: barnAt(2), undoes: { edit_id: 'b2', kind: 'undo' } }, partName, () => null, barnTurn.slice(0, 2)), 'You turned the barn again');
assert.equal(undone({ subject_id: 'part:barn-id', before: barnAt(2), after: null, undoes: { edit_id: 'b9', kind: 'transform_element' } }, partName, () => null, barnTurn), 'You put the barn back where it was');
assert.equal(redone({ subject_id: 'part:barn-id', before: null, after: barnAt(2), undoes: { edit_id: 'b9', kind: 'undo' } }, partName, () => null, barnTurn), 'You moved the barn again');
assert.equal(undone({ subject_id: 'part:pond-id', undoes: { kind: 'suppress_element' } }, partName), 'You brought back the pond');
assert.equal(undone({ subject_id: 'part:barn-id', undoes: { kind: 'transform_element' } }, partName), 'You put the barn back where it was');
assert.equal(undone({ subject_id: 'part:gone', undoes: { kind: 'suppress_element' } }), 'You brought back a part of the world');
const thingLog = (kind) => [{ edit_id: 't1', kind, thing_id: 'well:1' }, { edit_id: 't2', kind: 'undo', undone_edit_id: 't1', thing_id: 'well:1' }];
for (const kind of ['add_thing', 'move_thing', 'remove_thing']) {
  const row = youChangeWords(changeParts(thingLog(kind)[1], thingLog(kind), () => 'well'));
  assert.equal(row, undone({ undoes: { kind }, before: well, after: well }), kind);
}
assert.equal(changeWords({ edit_id: 'u', kind: 'undo', undone_edit_id: 'missing' }, [], () => null), 'Undid the last change');
// A building's storeys change is told from a move by its storeys, in the notes and in History's rows,
// which read the same (ruling W6): what was done, "1 storey" singular, and "made with" where the
// building stood as the world made it.
const tea = (id) => (id === 'tea' ? 'tea house' : null);
const teaAt = (storeys, transform = null) => ({ element_id: 'part:tea', suppressed: false, transform, ...(storeys === null ? {} : { storeys }) });
const teaUndo = (before, after) => ({ subject_id: 'part:tea', undoes: { kind: 'transform_element' }, before, after });
assert.equal(undone(teaUndo(teaAt(4), teaAt(2)), tea), 'You put the tea house back to 2 storeys');
assert.equal(undone(teaUndo(teaAt(4), null), tea), 'You put the tea house back to the storeys it was made with');
assert.equal(undone(teaUndo(teaAt(4, { x_mm: 1000 }), teaAt(4, { x_mm: 0 })), tea), 'You put the tea house back where it was');
assert.equal(redone({ subject_id: 'part:tea', before: teaAt(2), after: teaAt(4) }, tea), 'You raised the tea house to 4 storeys again');
assert.equal(redone({ subject_id: 'part:tea', before: teaAt(2), after: teaAt(1) }, tea), 'You lowered the tea house to 1 storey again');
assert.equal(redone({ subject_id: 'part:tea', before: null, after: teaAt(4) }, tea), 'You set the tea house to 4 storeys again');
assert.equal(redone({ subject_id: 'part:tea', before: teaAt(null, { x_mm: 0 }), after: teaAt(null, { x_mm: 2000 }) }, tea), 'You moved the tea house again');
assert.equal(redone({ subject_id: 'part:tea', before: null, after: { ...teaAt(null), suppressed: true } }, tea), 'You took out the tea house again');
const storeysLog = [
  { edit_id: 's1', kind: 'transform_element', element_id: 'part:tea', storeys: { before: null, after: 4 } },
  { edit_id: 's2', kind: 'transform_element', element_id: 'part:tea', storeys: { before: 4, after: 1 } },
  { edit_id: 's3', kind: 'undo', undone_edit_id: 's2', element_id: null },
  { edit_id: 's4', kind: 'undo', undone_edit_id: 's3', element_id: null },
  { edit_id: 's5', kind: 'undo', undone_edit_id: 's1', element_id: null },
  { edit_id: 's6', kind: 'transform_element', element_id: 'part:tea' },
];
assert.deepEqual(storeysLog.map(edit => changeWords(edit, storeysLog, () => null, tea)), [
  'Set the tea house to 4 storeys',
  'Lowered the tea house to 1 storey',
  'Put the tea house back to 4 storeys',
  'Lowered the tea house to 1 storey again',
  'Put the tea house back to the storeys it was made with',
  'Moved the tea house',
]);
// Each note is History's row for the same change.
assert.equal(youChangeWords(changeParts(storeysLog[2], storeysLog, () => null, tea)), undone(teaUndo(teaAt(1), teaAt(4)), tea));
assert.equal(youChangeWords(changeParts(storeysLog[3], storeysLog, () => null, tea)), redone({ subject_id: 'part:tea', before: teaAt(4), after: teaAt(1) }, tea));
assert.equal(changeWords({ edit_id: 'p4', kind: 'transform_element', element_id: 'part:gone', thing_id: null }, [], () => null), 'Moved a part of the world');
// Snapping: half metres and 15 degree steps unless free; a yaw stays within one revolution.
assert.equal(snapped(1249, false), 1000);
assert.equal(snapped(1251, false), 1500);
assert.equal(snapped(1251.4, true), 1251);
assert.equal(turned(0, 15, false), 261_799);
assert.equal(turned(0, -15, false), 6_021_386);
assert.equal(turned(6_100_000, 15, false), 0);
assert.equal(turned(100_000, 1, true), 117_453);
// A new thing faces the person placing it on the turn's own step (ruling W13 T5): a kind's front is its +y (where a
// bench seats its people), held to the north (-z) unturned, so the eye due north is yaw 0, due west a quarter turn,
// due south a half turn; nowhere to face, 0.
assert.equal(TURN_DEGREES, 15);
assert.equal(facingYaw(0, -5_000), 0);
assert.equal(facingYaw(-5_000, 0), turned(0, 90, false));
assert.equal(facingYaw(0, 5_000), turned(0, 180, false));
assert.equal(facingYaw(5_000, 0), turned(0, -90, false));
assert.equal(facingYaw(-1_000, -3_800), turned(0, TURN_DEGREES, false));
assert.equal(facingYaw(0, 0), 0);
assert.equal(facingYaw(Number.NaN, 1), 0);
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
// A row or a tile with the focus takes Enter and Space itself; Esc gives the focus back to the world.
assert.equal(keyAction({ ...on, focused: true }, key('Enter')), null);
assert.equal(keyAction({ ...on, focused: true }, key('Space')), null);
assert.equal(keyAction({ ...chosen, focused: true }, key('Escape')), 'unfocus');
assert.equal(keyAction({ ...asking, focused: true }, key('Escape')), 'cancel');
assert.equal(keyAction(asking, key('Tab')), null);
assert.equal(keyAction(off, key('Tab')), null);
// H is the page's in build mode too: it opens History from anywhere.
assert.equal(keyAction(on, key('KeyH')), null);
assert.equal(keyAction(chosen, key('KeyH')), null);
assert.equal(keyAction(off, key('KeyH')), null);
// After the server refused removing what is chosen, Backspace and Delete do nothing; moving it still works.
const refusedRemoval = { ...chosen, removeRefused: true };
assert.equal(keyAction(refusedRemoval, key('Delete')), 'held');
assert.equal(keyAction(refusedRemoval, key('Backspace')), 'held');
assert.equal(keyAction(refusedRemoval, key('BracketRight')), 'turn-right');
// Moving: [ and ] turn what is selected, with Alt for a free turn; Enter places it only where the
// server said it may stand; Esc puts it back; Delete puts it back and asks to remove it, but not
// once the server refused the spot (the rows then offer Put back alone).
const moving = { ...chosen, moving: true, ready: false }, keepable = { ...moving, ready: true };
assert.equal(keyAction(chosen, key('BracketLeft')), 'turn-left');
assert.equal(keyAction(chosen, key('BracketRight', { altKey: true })), 'turn-right');
assert.equal(keyAction(on, key('BracketRight')), 'held');
assert.equal(keyAction(asking, key('BracketRight')), 'held');
assert.equal(keyAction(moving, key('Enter')), 'held');
assert.equal(keyAction(keepable, key('Enter')), 'place');
assert.equal(keyAction(keepable, key('Escape')), 'put-back');
assert.equal(keyAction(keepable, key('Delete')), 'remove');
assert.equal(keyAction(moving, key('Backspace')), 'remove');
assert.equal(keyAction({ ...moving, refused: true }, key('Delete')), 'held');
// Placing a new thing from the tray: nothing is chosen yet; it turns, Enter places it where the
// server said it may stand, Esc puts it back in the tray, and Delete has nothing to remove.
const placing = { ...on, placing: true, ready: false }, placeable = { ...placing, ready: true };
assert.equal(keyAction(placing, key('BracketLeft')), 'turn-left');
assert.equal(keyAction(placing, key('Enter')), 'held');
assert.equal(keyAction(placeable, key('Enter')), 'place');
assert.equal(keyAction(placing, key('Escape')), 'put-back');
assert.equal(keyAction(placeable, key('Delete')), 'held');
assert.equal(keyAction(placing, key('Tab')), null);
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
assert.equal(redone({ before: at(0), after: at(0, true) }), 'You took out the well again');
assert.equal(redone({ before: null, after: at(0) }), 'You placed the well again');
assert.equal(redone({ before: at(0), after: at(2000) }), 'You moved the well again');
assert.equal(redone({}), 'You did a change again');
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
  'Placed the well', 'Moved the well', 'Put the well back where it was', 'Moved the well again',
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
// Build mode's keys and rows, in the design's words and order (WORDS.md, ruling W10).
const said = (list) => list.map(({ keys, word }) => [Array.isArray(keys) ? keys.join(' ') : keys, word]);
// The keys card lists every key build mode has (ruling W10), Redo under Undo with one cap for its chord (W12.3).
assert.deepEqual(said(buildKeys()), [
  ['mouse', 'Move'], ['[ ]', 'Turn'], ['Alt', 'Free'], ['Del', 'Remove'], ['Tab', 'Next'], ['⌘Z', 'Undo'], ['⇧⌘Z', 'Redo'],
  ['B', 'Done'], ['H', 'History'], ['Esc', 'Back'],
]);
assert.equal(buildKeys().find(({ word }) => word === 'Redo').shortcut, 'Shift+Meta+Z');
// The held group's rows in each state (ruling W10), each pressing what its key does.
const rows = (state) => heldRows(state).map(({ key, word }) => [key, word]);
assert.deepEqual(rows({}), [['mouse-click', 'Move'], ['[ ]', 'Turn'], ['Del', 'Remove']]);
assert.deepEqual(rows({ moving: true, ready: true }), [['mouse-click', 'Place'], ['[ ]', 'Turn'], ['Del', 'Remove'], ['Esc', 'Put back']]);
assert.equal(heldRows({ moving: true, ready: false })[0].disabled, true);
assert.equal(heldRows({ moving: true, ready: true })[0].disabled, false);
assert.deepEqual(rows({ placing: true, ready: true }), [['mouse-click', 'Place'], ['[ ]', 'Turn'], ['Esc', 'Put back']]);
assert.deepEqual(rows({ moving: true, refused: true }), [['Esc', 'Put back']]);
assert.deepEqual(rows({ placing: true, refused: true }), [['Esc', 'Put back']]);
assert.deepEqual(rows({ confirming: true }), [['Enter', 'Remove'], ['Esc', 'Keep']]);
// After a removal was refused (people live or work there), the rows offer moving it, not removing it again.
assert.deepEqual(rows({ removeRefused: true }), [['mouse-click', 'Move'], ['[ ]', 'Turn']]);
const keyOf = { Enter: 'Enter', Esc: 'Escape', Del: 'Delete', '[ ]': 'BracketRight', 'mouse-click': 'Enter' };
const flagsOf = (state) => ({ on: true, selected: !state.placing, placing: false, confirming: false, moving: false, ready: false, refused: false, busy: false, removeRefused: false, focused: false, ...state });
for (const state of [{}, { moving: true, ready: true }, { placing: true, ready: true }, { moving: true, refused: true }, { confirming: true }, { removeRefused: true }]) {
  for (const row of heldRows(state)) {
    if (!row.action || row.disabled) continue;
    assert.equal(keyAction(flagsOf(state), { code: keyOf[row.key], key: '', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false }), row.action, `${row.word} presses what its key does`);
  }
}
for (const words of [...Object.values(TRAY), did({ kind: 'add_thing', thing_id: 'bench:1' }, 'bench')]) assert.doesNotMatch(words, /\u2014|_/u);
assert.equal(nothingInView(), 'No placed things in view. Walk closer to one.');
assert.deepEqual({ ...HISTORY }, { title: 'History', today: 'Today', empty: 'Nothing has been changed yet.' });
console.log('Build words checks passed: names by kind, refusals as sentences, each change as History says it, snapping, the changes list, keys per state.');
