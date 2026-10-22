import assert from 'node:assert/strict';
import { CREATE_WORDS } from './create-words.mjs';
import {
  MADE_HANDOFF_KEY, afterRead, canCreate, createKey, draftSteps, madeColumns, moveChoice, offerState, pollDelay, readMade, spentOf,
  startCards, writeMade,
} from './create-steps.mjs';

// The offer to the page's state (N7, N9, N12).
assert.deepEqual(offerState(null), { page: 'loading' });
assert.deepEqual(offerState({ offered: true, code: null, running_draft_id: null }), { page: 'offered' });
assert.deepEqual(offerState({ offered: false, code: 'kind_draft_busy', running_draft_id: 'd-1' }), { page: 'following', draftId: 'd-1' });
for (const code of ['provider_credential_absent', 'kinds_from_people_not_offered']) assert.deepEqual(offerState({ offered: false, code }), { page: 'no-model' }, code);
// N25: not offered here for another reason than a missing model.
for (const code of ['not_authorised', 'world_draft_spending_not_durable', 'world_draft_worker_not_running']) {
  assert.deepEqual(offerState({ offered: false, code }), { page: 'not-offered' }, code);
}
for (const code of ['budget_exceeded', 'process_budget_spent', 'process_share_spent']) assert.deepEqual(offerState({ offered: false, code }), { page: 'budget' }, code);
// N34: spending held closed until an operator acts is paused, not spent, by its served code.
assert.deepEqual(offerState({ offered: false, code: 'spending_suspended' }), { page: 'paused' });
// N31: a budget with something left, less than making could cost, by its code and both served figures.
assert.deepEqual(offerState({ offered: false, code: 'world_draft_bound_exceeds_left', operation: { maximum_usd: '1.4227' }, left_usd: '0.5' }),
  { page: 'short', maximumUsd: '1.4227', leftUsd: '0.5' });
assert.deepEqual(offerState({ offered: false, code: 'world_draft_bound_exceeds_left', operation: null, left_usd: null }), { page: 'budget' });
assert.deepEqual(offerState({ offered: false, code: 'kind_draft_limit' }), { page: 'refused', code: 'kind_draft_limit' });
assert.equal(canCreate({ offered: true, code: null }, 'a harbour'), true);
assert.equal(canCreate({ offered: true, code: null }, '   '), false);
assert.equal(canCreate(null, 'a harbour'), false);
assert.equal(canCreate({ offered: false, code: 'provider_credential_absent' }, 'a harbour'), false);

// Steps: only states the server served, each timed by the served elapsed time at the read that ended it.
const reads = [
  { state: 'choosing', elapsed_seconds: 0 }, { state: 'choosing', elapsed_seconds: 1 },
  { state: 'drafting', elapsed_seconds: 1 }, { state: 'drafting', elapsed_seconds: 4 },
  { state: 'making', elapsed_seconds: 6 }, { state: 'making', elapsed_seconds: 12 },
];
assert.deepEqual(draftSteps(reads), [
  { key: 'choosing', words: 'Worked out what to make', state: 'done', time: '1 s' },
  { key: 'drafting', words: 'Planning the place', state: 'done', time: '6 s' },
  { key: 'making', words: 'Building it', state: 'now', time: '12 s' },
]);
// A state never served (queued here, and no land stage) is not shown; nothing comes from a clock.
assert.ok(!draftSteps(reads).some(step => step.key === 'queued' || step.words === 'Drawing its land'));
// Queued, when served, is a step: "Waiting to start".
assert.deepEqual(draftSteps([{ state: 'queued', elapsed_seconds: 0 }]), [{ key: 'queued', words: 'Waiting to start', state: 'now', time: '0 s' }]);
// Ready ends the last step at its read; a refused draft leaves its last step where it stopped.
assert.deepEqual(draftSteps([...reads, { state: 'ready', elapsed_seconds: 64 }]).map(step => [step.state, step.time]), [['done', '1 s'], ['done', '6 s'], ['done', '1 min 4 s']]);
assert.deepEqual(draftSteps([...reads, { state: 'refused', elapsed_seconds: 13 }]).at(-1), { key: 'making', words: 'Building it', state: 'now', time: '13 s' });
// A state served again out of order moves nothing back; an unreadable elapsed time is skipped.
assert.equal(draftSteps([...reads, { state: 'choosing', elapsed_seconds: 14 }]).at(-1).time, '12 s');
assert.equal(draftSteps([{ state: 'making', elapsed_seconds: 'x' }]).length, 0);
// A recipe or kind start with one served state shows that single step with its time (N4, N11).
assert.deepEqual(draftSteps([{ state: 'making', elapsed_seconds: 3 }, { state: 'ready', elapsed_seconds: 5 }]), [{ key: 'making', words: 'Building it', state: 'done', time: '5 s' }]);

// Reads: at the served interval; none once ended. One failed read is quiet; three say offline.
assert.equal(pollDelay({ state: 'making', poll_after_seconds: 3 }), 3000);
assert.equal(pollDelay({ state: 'ready', poll_after_seconds: 3 }), null);
assert.equal(pollDelay({ state: 'making', poll_after_seconds: null }), null);
let read = afterRead(0, false, 3000);
assert.deepEqual(read, { failed: 1, offline: false, retryMs: 3000 });
read = afterRead(read.failed, false, 3000);
assert.equal(read.offline, false);
read = afterRead(read.failed, false, 3000);
assert.deepEqual(read, { failed: 3, offline: true, retryMs: 4000 });
assert.deepEqual(afterRead(read.failed, true, 3000), { failed: 0, offline: false, retryMs: 3000 });
assert.equal(afterRead(9, false, 3000).retryMs, 30000);

// Accounting: reported and reconciled are spent; held and dispatched not known yet.
assert.deepEqual(spentOf({ reported_usd: '0.1', reconciled_usd: '0.02', held_usd: '0.01', unknown_liability_usd: '0.02' }), { spentUsd: 0.12, unknownUsd: 0.03 });
assert.equal(spentOf(null), null);

// Cards: served recipes, then kinds, Blank last; no name comes from code but Blank's.
const cards = startCards([{ key: 'r1', name: 'Small town', picture: 'data:image/png;base64,x', priceUsd: null }], [{ key: 'k1', name: 'Wall city', priceUsd: '0.4' }, { key: 'k2', name: ' ' }]);
assert.deepEqual(cards.map(card => [card.name, card.sub]), [['Small town', 'No AI model · Free'], ['Wall city', 'At most $0.40'], ['Blank', 'Build it yourself']]);
// N27: where the workspace's blank world exists, Blank says it opens it again.
assert.equal(startCards([], [], { blankExists: true }).at(-1).sub, 'Opens My world again');
assert.equal(cards.at(-1).blank, true);
assert.deepEqual(startCards().map(card => card.name), [CREATE_WORDS.blank]);
assert.equal(moveChoice(0, 3, -1), 0);
assert.equal(moveChoice(1, 3, 1), 2);
assert.equal(moveChoice(2, 3, 1), 2);

// Keys. In the field only Enter, Shift+Enter and Esc act; Cmd and Ctrl pass to the browser; the old
// shell's keys type into the field and do nothing else.
const key = (code, more = {}) => ({ code, key: code, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, ...more });
const field = { page: 'create', focus: 'field', canCreate: true };
assert.equal(createKey(key('Enter'), field), 'create');
assert.equal(createKey(key('Enter'), { ...field, canCreate: false }), 'silence');
assert.equal(createKey(key('Enter', { repeat: true }), field), 'silence');
assert.equal(createKey(key('Enter', { shiftKey: true }), field), 'type');
assert.equal(createKey(key('Escape'), field), 'leave');
assert.equal(createKey(key('Escape', { repeat: true }), field), 'silence');
assert.equal(createKey(key('KeyZ', { metaKey: true }), field), 'quiet');
assert.equal(createKey(key('KeyK', { metaKey: true }), field), 'quiet');
assert.equal(createKey(key('KeyK', { ctrlKey: true }), { page: 'create', focus: 'page' }), 'quiet');
for (const code of ['KeyN', 'KeyH', 'KeyK', 'KeyI', 'KeyM', 'KeyO', 'KeyR', 'KeyG', 'KeyP', 'Backspace', 'Slash']) {
  assert.equal(createKey(key(code), field), 'type', code);
  assert.equal(createKey(key(code), { page: 'create', focus: 'page' }), 'silence', code);
  assert.equal(createKey(key(code), { page: 'create', focus: 'card' }), 'silence', code);
}
// On a card: arrows move the choice, Enter starts from it (K2, K7).
const card = { page: 'create', focus: 'card' };
assert.equal(createKey(key('ArrowLeft'), card), 'previous');
assert.equal(createKey(key('ArrowRight'), card), 'next');
assert.equal(createKey(key('Enter'), card), 'start');
assert.equal(createKey(key('Space'), card), 'start');
assert.equal(createKey(key('Escape'), card), 'leave');
assert.equal(createKey(key('Tab'), card), 'pass');
assert.equal(createKey(key('Enter'), { page: 'create', focus: 'button' }), 'pass');
// Frame 21: Esc leaves while the making carries on; no other key.
assert.equal(createKey(key('Escape'), { page: 'creating', focus: 'page' }), 'leave');
for (const code of ['Enter', 'KeyW', 'ArrowLeft', 'Space']) assert.equal(createKey(key(code), { page: 'creating', focus: 'page' }), 'silence', code);

// The made note's columns, in order, an empty one left out (N13), and the handoff round trip.
assert.deepEqual(madeColumns({ inIt: 'Four pools, a hotel', set: 'on gentle hills, with mountains far off', notInItYet: '', spent: '$0.31 of the $1.43 set aside' }).map(one => one.label), ['In it', 'Set', 'Spent']);
const columns = madeColumns({ inIt: 'Four pools', notInItYet: 'a lighthouse', spent: '$0.31 of the $1.43 set aside' });
assert.equal(MADE_HANDOFF_KEY, 'exulanica.made.v1');
assert.deepEqual(readMade(writeMade('w-1', columns), 'w-1'), { entryId: 'w-1', columns, build: false });
// Blank's handoff opens build mode, with no note; a handoff that says nothing of it opens none.
assert.deepEqual(readMade(writeMade('w-1', [], { build: true }), 'w-1'), { entryId: 'w-1', columns: [], build: true });
assert.equal(readMade(JSON.stringify({ entryId: 'w-1', columns: [], build: 'yes' }), 'w-1').build, false);
assert.equal(readMade(writeMade('w-1', columns), 'w-2'), null);
assert.equal(readMade('{', 'w-1'), null);
assert.equal(readMade(null, 'w-1'), null);
assert.deepEqual(readMade(JSON.stringify({ entryId: 'w-1', columns: [{ label: 'Code', value: 'x' }, { label: 'Spent', value: '$0' }] }), 'w-1').columns, [{ label: 'Spent', value: '$0' }]);

export default true;
