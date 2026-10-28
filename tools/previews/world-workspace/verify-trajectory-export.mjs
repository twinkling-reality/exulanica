import assert from 'node:assert/strict';
import { DECISION_WORDS, decisionTrajectoryRecord as fromDecisionWords } from './decision-words.mjs';
import { PATH_WORDS, historyRunTrajectories as fromHistoryWords } from './history-words.mjs';
import {
  TRAJECTORY_PROFILE,
  TRAJECTORY_WORDS,
  assertNoFloats,
  canonicalJson,
  decisionTrajectoryRecord,
  historyRunTrajectories,
  roundHalfDown,
  serializeTrajectoryJsonl,
  trajectorySummaryWords,
} from './trajectory-export.mjs';

// 1. UI labels are present, human-understandable, and integrated in history-words.mjs and decision-words.mjs.
assert.equal(TRAJECTORY_PROFILE, 'exulanica.world-trajectory/v1');
assert.equal(TRAJECTORY_WORDS.trainingData, 'Training Data');
assert.equal(TRAJECTORY_WORDS.exportTrajectories, 'Export Trajectories');
assert.equal(TRAJECTORY_WORDS.counterfactualPairs, 'Counterfactual Pairs');
assert.equal(TRAJECTORY_WORDS.verifiedDecisions, 'Verified Decisions');

assert.equal(PATH_WORDS.trainingData, 'Training Data');
assert.equal(PATH_WORDS.exportTrajectories, 'Export Trajectories');
assert.equal(PATH_WORDS.counterfactualPairs, 'Counterfactual Pairs');
assert.equal(PATH_WORDS.verifiedDecisions, 'Verified Decisions');

assert.equal(DECISION_WORDS.trainingData, 'Training Data');
assert.equal(DECISION_WORDS.exportTrajectories, 'Export Trajectories');
assert.equal(DECISION_WORDS.counterfactualPairs, 'Counterfactual Pairs');
assert.equal(DECISION_WORDS.verifiedDecisions, 'Verified Decisions');

assert.equal(fromDecisionWords, decisionTrajectoryRecord);
assert.equal(fromHistoryWords, historyRunTrajectories);

// 2. Exact integer rounding (`roundHalfDown`) and strict zero-float enforcement.
assert.equal(roundHalfDown(2000, 3), 667);
assert.equal(roundHalfDown(15, 10), 1);
assert.equal(roundHalfDown(16, 10), 2);
assert.throws(() => assertNoFloats({ score: 0.95 }), /Float or non-safe integer/u);
assert.throws(() => canonicalJson({ cost_usd: 0.0003 }), /Float or non-safe integer/u);

// 3. Single decision export (SFT + DPO counterfactual pair).
const singleDecision = {
  world_id: 'world:terraces-bay',
  version_id: '3c4d5e6f-0000-4000-8000-000000000002',
  request_id: 'req-412',
  tick: 412,
  subject_id: 'teo',
  model: 'Nemotron 3 Nano 30B',
  told: [
    { label: 'Where and when', lines: ['The lower pools · 06:52 · Day 1'], apart: false },
  ],
  choices: [
    { number: 1, words: 'Say something to Ines', chosen: true },
    { number: 2, words: 'Walk to the market', chosen: false },
    { number: 3, words: 'Wait a minute', chosen: false },
  ],
  said: 'Morning, Ines. The boats are out early.',
  answered: { latencyMs: 640, costUsd: '0.0003', costKnown: true },
  branches: [
    { ask_id: 'a1', model: { name: 'Qwen3 235B' }, same_choice: false, kind: 'went', outcome: 'Walk to the market' },
    { ask_id: 'a2', model: { name: 'Llama 4' }, same_choice: true, kind: 'spoke' },
  ],
};

const single = decisionTrajectoryRecord(singleDecision);
assert.ok(single.sft);
assert.equal(single.sft.profile, 'exulanica.world-trajectory/v1');
assert.equal(single.sft.record_kind, 'sft');
assert.equal(single.sft.chosen_action.label, 'Say something to Ines');
assert.equal(single.sft.chosen_action.line, 'Morning, Ines. The boats are out early.');
assert.equal(single.sft.latency_ms, 640);
assert.equal(single.sft.cost_usd, '0.0003');
assert.equal(single.dpoPairs.length, 1);
assert.equal(single.dpoPairs[0].record_kind, 'dpo');
assert.equal(single.dpoPairs[0].pair_kind, 'counterfactual_branch');
assert.equal(single.dpoPairs[0].chosen_valid_action.label, 'Say something to Ines');
assert.equal(single.dpoPairs[0].rejected_or_alternative_action.model_id, 'Qwen3 235B');

// 4. History run export and distillation metrics.
const moments = [
  singleDecision,
  {
    world_id: 'world:terraces-bay',
    version_id: '3c4d5e6f-0000-4000-8000-000000000002',
    request_id: 'req-415',
    tick: 415,
    subject_id: 'ines',
    model: 'Nemotron 3 Super 120B',
    choices: [
      { number: 1, words: 'Walk to the market', chosen: true },
      { number: 2, words: 'Wait a minute', chosen: false },
    ],
    answered: { latencyMs: 360, costUsd: '0.0002', costKnown: true },
    branches: [
      { ask_id: 'a3', model: { name: 'Qwen3 235B' }, same_choice: true, kind: 'went' },
    ],
  },
  {
    world_id: 'world:terraces-bay',
    version_id: '3c4d5e6f-0000-4000-8000-000000000002',
    request_id: 'req-420',
    tick: 420,
    subject_id: 'marco',
    model: 'Nemotron 3 Nano 30B',
    choices: [
      { number: 1, words: 'Say something to Teo', chosen: false },
      { number: 2, words: 'Wait a minute', chosen: false },
    ],
    unanswered: { asks: 1, latencyMs: 500, costUsd: '0.0001', costKnown: true, reason: 'answer_not_offered' },
  },
];

const bundle = historyRunTrajectories(moments, {
  worldId: 'world:terraces-bay',
  versionId: '3c4d5e6f-0000-4000-8000-000000000002',
});

assert.equal(bundle.profile, 'exulanica.world-trajectory/v1');
assert.equal(bundle.sft_records.length, 2);
assert.equal(bundle.dpo_pairs.length, 2);
assert.deepEqual(bundle.metrics, {
  total_decisions: 3,
  applied_count: 2,
  refused_count: 1,
  counterfactual_pairs: 2,
  evaluated_branches: 3,
  agreed_branches: 2,
  agreement_rate_permille: 667,
  mean_latency_ms: 500,
});

assert.equal(
  trajectorySummaryWords(bundle),
  'Verified Decisions: 2 · Counterfactual Pairs: 2 · Agreement Rate: 67%',
);

const jsonl = serializeTrajectoryJsonl(bundle);
const lines = jsonl.split('\n');
assert.equal(lines.length, 4);
for (const line of lines) {
  const parsed = JSON.parse(line);
  assert.equal(parsed.profile, 'exulanica.world-trajectory/v1');
  assertNoFloats(parsed);
}

console.log('trajectory export: ok');
