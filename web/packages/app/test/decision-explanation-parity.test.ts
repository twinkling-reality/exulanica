// One recorded decision is explained in two places: the app's choice account (decision-record.ts)
// and the world workspace's explanation (tools/previews/world-workspace/decision-explanation.mjs).
// Their words differ; what they say happened may not. For the same request, receipt and models
// read, both name the same state: an answer awaited, an answer not accepted, an accepted answer no
// minute has taken up, one a minute did not apply, or one a minute applied.
import { describe, expect, it } from 'vitest';
import { VERDICT_ORDER, choiceAccount, type ChoiceVerdict } from '../src/decision-record.js';
import type { PersonDecision, SocietyDecisionDetail } from '../src/society-models-api.js';

const REPOSITORY = new URL('../../../../', import.meta.url);
const WORKSPACE = new URL('tools/previews/world-workspace/', REPOSITORY);

interface Explanation { readonly result: string }
type Explain = (data: SocietyDecisionDetail, summary: PersonDecision | null) => Explanation;
const workspace = async (): Promise<Explain> =>
  ((await import(/* @vite-ignore */ new URL('decision-explanation.mjs', WORKSPACE).href)) as { explainDecision: Explain }).explainDecision;

const ID = 'asked';
const option = { kind: 'wait', label: 'wait here a minute', action: 'wait', walk_mm: null, activity: null, target_id: null };
const request = {
  request_id: ID, subject_id: 'being-1', base_tick: 3,
  provider_config: { provider: 'open-provider', model_id: 'open/model-small', prompt_version: 'person-choice/v1' },
  context: { tick: 3, options: [option] },
};

const detail = (status: string | null, reason = 'validated_choice'): SocietyDecisionDetail => ({
  status: status === null ? 'in_progress' : 'completed',
  request,
  decision: status === null ? null : {
    request_id: ID, status, reason,
    proposal: status === 'accepted' ? { label: option.label, option } : null,
    provider: { provider: 'open-provider', model_id: 'open/model-small', served_model_id: 'open/model-small' },
  },
});

const read = (status: PersonDecision['status'], disposition: string | null, reason: string | null = null): PersonDecision => ({
  provider: 'open-provider', modelId: 'open/model-small', name: 'Small Open Model', subjectId: 'being-1', requestId: ID,
  decisionSeq: 1, baseTick: 3, consumedTick: disposition === null ? null : 4, status, reason: 'validated_choice',
  disposition, dispositionReason: reason, chose: status === 'accepted' ? option.label : null,
});

/** Each recorded state, the verdict the choice account gives it and how the workspace's result begins. */
const STATES: readonly { readonly name: string; readonly detail: SocietyDecisionDetail; readonly read: PersonDecision | null; readonly verdict: ChoiceVerdict; readonly result: RegExp }[] = [
  { name: 'no answer recorded yet', detail: detail(null), read: null, verdict: 'awaiting_answer', result: /^Awaiting a recorded answer\./ },
  { name: 'an answer the engine refused', detail: detail('rejected', 'not_an_offered_option'), read: read('rejected', null), verdict: 'refused', result: /^Not accepted\./ },
  { name: 'no answer in time', detail: detail('unavailable', 'model_timed_out'), read: read('unavailable', null), verdict: 'no_answer', result: /^Not accepted\./ },
  { name: 'accepted, no minute yet', detail: detail('accepted'), read: read('accepted', null), verdict: 'pending', result: /^Accepted; application has not been recorded/ },
  { name: 'accepted, applied', detail: detail('accepted'), read: read('accepted', 'applied'), verdict: 'applied', result: /^Applied by the world\./ },
  { name: 'accepted, refused by its minute', detail: detail('accepted'), read: read('accepted', 'rejected', 'place_taken_this_minute'), verdict: 'not_applied', result: /^Not applied\./ },
  { name: 'accepted, superseded', detail: detail('accepted'), read: read('accepted', 'superseded', 'superseded_by_newer'), verdict: 'not_applied', result: /^Not applied\./ },
  { name: 'accepted, stale', detail: detail('accepted'), read: read('accepted', 'stale', 'answer_after_its_minute'), verdict: 'stale', result: /^Not applied\./ },
];

describe('the two explanations of one recorded decision', () => {
  it.each(STATES)('agree on what happened: $name', async ({ detail: recorded, read: summary, verdict, result }) => {
    expect(choiceAccount(recorded, summary, null).verdict.kind).toBe(verdict);
    expect((await workspace())(recorded, summary).result).toMatch(result);
  });

  it('cover every verdict the choice account can give', () => {
    expect(new Set(STATES.map((state) => state.verdict))).toEqual(new Set(VERDICT_ORDER));
  });
});
