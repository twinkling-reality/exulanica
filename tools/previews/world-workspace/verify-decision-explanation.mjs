import assert from 'node:assert/strict';
import { explainDecision, decisionSummaryWords } from './decision-explanation.mjs';

const request = { request_id: 'one', context: { tick: 3, options: [
  { label: 'wait here a minute', kind: 'wait' }, { label: 'stand a while nearby', kind: 'stand' },
] } };
const accepted = { request, status: 'completed', decision: { status: 'accepted', proposal: { label: 'wait here a minute', option: request.context.options[0] }, provider: { model_id: 'requested', served_model_id: null } } };
const summary = { requestId: 'one', disposition: null };
const waiting = explainDecision(accepted, summary);
assert.match(waiting.result, /application has not been recorded/);
assert.equal(waiting.servedModel, null); // A requested identity never substitutes for served identity.
assert.equal(waiting.calls, null);
assert.equal(explainDecision({ ...accepted, decision: { ...accepted.decision, provider: { calls: [{}] } } }, summary).calls, 1);
assert.equal(waiting.options.length, 2);
assert.match(waiting.limitations.join(' '), /No destination was offered/);
assert.match(waiting.limitations.join(' '), /does not explain.*private reasoning/);
assert.equal(explainDecision(accepted, { ...summary, disposition: 'applied' }).result, 'Applied by the world.');
assert.equal(explainDecision(accepted, { ...summary, disposition: 'rejected', dispositionReason: 'place_taken_this_minute' }, { reasonWords: { place_taken_this_minute: 'Another character took that place.' } }).result, 'Not applied. Another character took that place.');
assert.match(explainDecision({ request, decision: null }, summary).result, /Awaiting/);
assert.match(explainDecision({ ...accepted, decision: { status: 'unavailable', reason: 'no_answer_in_time' } }, summary).result, /^Not accepted/);
assert.throws(() => explainDecision(accepted, { requestId: 'different' }), /summary changed/);
assert.equal(explainDecision({ request: { request_id: 'one' }, decision: null }, summary).options.length, 0);
// One memory entry is an entry; more are entries.
const remembering = beings => explainDecision({ ...accepted, request: { ...request, context: { ...request.context, remembers: { beings, places: [], handed: [] } } } }, summary).inputs;
assert(remembering([{}]).includes('1 memory entry was also included; inspect the recorded inputs for its complete contents.'));
assert(remembering([{}, {}]).includes('2 memory entries were also included; inspect the recorded inputs for their complete contents.'));
assert(remembering([]).includes('No memory entries were included.'));
const timeout = decisionSummaryWords({ baseTick:28, consumedTick:null, status:'unavailable', reason:'model_timed_out', disposition:null }, {model_timed_out:'The model did not answer in time.'});
assert.match(timeout, /Based on minute 28/);
assert.match(timeout, /No world action was applied/);
assert.doesNotMatch(timeout, /29|routine decided/);
console.log('Decision explanation checks passed: pending, accepted, applied, refused, missing identity, waiting limits, request binding and memory counts.');
