// A recorded decision explained from its records alone: what was told, offered and chosen, what the
// engine and the minute did with it, what the being's events record after it, and what the call
// cost. Records here are written by hand in the decision route's and the events route's shapes.
import { describe, expect, it } from 'vitest';
import {
  decisionChange, explainDecisionRecord, knownDecisions, parseDecisionEvents, type DecisionEvent,
} from '../src/composition/decision-record.js';
import type { PersonDecision, SocietyDecisionDetail } from '../src/society-models-api.js';

const BEING = 'being-1';
const MODEL = 'open/model-small';
const options = [
  { kind: 'wait', label: 'wait here a minute', action: 'wait', walk_mm: null, activity: null, target_id: null },
  { kind: 'target', label: 'resting, 60 m away (1)', action: 'go', walk_mm: 60000, activity: 'rest', target_id: 'place:rest' },
  { kind: 'stand', label: 'stand a while nearby', action: 'stand', walk_mm: null, activity: 'stand', target_id: null },
];

function request(id: string, baseTick: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    request_id: id, subject_id: BEING, base_tick: baseTick,
    provider_config: { provider: 'open-provider', model_id: MODEL, prompt_version: 'person-choice/v1' },
    context: {
      tick: baseTick, being: { kind: 'four legged creature', summary: 'a creature about 1 m long' },
      doing: { kind: 'idle' }, need_milli: 800, rest_at_need_milli: 700, holding: [], options,
      surroundings: { at: null, beings: [{ who: 'a walker', metres: 9, doing: 'resting', hears_you: false }], things: [], more_beings: 0, more_things: 0 },
      heard: [], ...extra,
    },
  };
}

const provider = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  provider: 'open-provider', model_id: MODEL, served_model_id: MODEL, latency_ms: 2400,
  prompt_tokens: 400, completion_tokens: 120, cost_usd: '0.00005000', cost_known: true,
  calls: [{ served_model: MODEL, prompt_tokens: 400, completion_tokens: 120, reasoning_tokens: null }], ...extra,
});

const answered = (id: string, label: string | null, status = 'accepted', reason = 'validated_choice', extra: Record<string, unknown> = {}): SocietyDecisionDetail => ({
  status: 'completed',
  request: request(id, 3),
  decision: {
    request_id: id, status, reason,
    proposal: label === null ? null : { label, option: options.find((option) => option.label === label) },
    provider: provider(extra),
  },
});

const event = (tick: number, kind: string, document: Record<string, unknown>, order = 0): unknown => ({
  tick, event_kind: kind, subject_id: BEING, document: { order, motion_path_mm: [[0, 0]], ...document },
});

const page = (events: readonly unknown[], next: string | null = null): readonly DecisionEvent[] =>
  parseDecisionEvents({ events, next }).events;

// Walked 40 m in minute 4 and 20 m in minute 5, arrived, rested, finished in minute 9.
const walk = page([
  event(4, 'route_progressed', { outcome: 'moved', reason: 'following_reachable_route', motion_path_mm: [[0, 0], [30000, 0], [30000, 10000]] }, 1),
  event(4, 'decision_applied', { outcome: 'decision_applied', reason: 'validated_choice', request_id: 'go', disposition: 'applied', chose: 'resting, 60 m away (1)' }, 2),
  event(5, 'route_progressed', { outcome: 'action_started', reason: 'arrived_at_access_node', motion_path_mm: [[30000, 10000], [30000, 30000]] }),
  event(9, 'action_completed', { outcome: 'rest_completed', reason: 'reviewed_duration_elapsed' }),
  event(10, 'decision_applied', { outcome: 'decision_applied', reason: 'validated_choice', request_id: 'later', disposition: 'applied', chose: 'wait here a minute' }),
]);

const latest = (extra: Partial<PersonDecision>): PersonDecision => ({
  provider: 'open-provider', modelId: MODEL, name: 'Small Open Model', subjectId: BEING, requestId: 'timeout',
  decisionSeq: 9, baseTick: 3, consumedTick: null, status: 'unavailable', reason: 'model_timed_out',
  disposition: null, dispositionReason: null, chose: null, ...extra,
});

/** Words no explanation may use: a record keeps inputs and answers, never a decider's inner life. */
const INNER_LIFE = /\b(thinks?|thought|feels?|felt|wants?|wanted|decided to|believes?|learn(s|ed|t)?)\b/iu;
const allWords = (view: ReturnType<typeof explainDecisionRecord>): string =>
  [...view.told, view.answer, view.applied, ...view.changed, ...view.limits, view.cost, view.tokens].join(' ');

describe('a recorded decision, explained', () => {
  it('follows an applied walk through the minutes its events record, and names the served model and cost', () => {
    const view = explainDecisionRecord(answered('go', 'resting, 60 m away (1)'), null, walk);
    expect(view.chosen).toBe('resting, 60 m away (1)');
    expect(view.options.filter((option) => option.chosen).map((option) => option.label)).toEqual(['resting, 60 m away (1)']);
    expect(view.answer).toBe('The engine accepted the answer: it chose one of the things they could do.');
    expect(view.applied).toBe('Applied in minute 4.');
    expect(view.appliedAt).toBe(4);
    expect(view.changed).toEqual([
      'Walked about 60 m along its recorded path (40 m in minute 4, 20 m in minute 5), ending about 42 m in a straight line from where it started.',
      'Arrived in minute 5.',
      'In minute 5 it began the chosen activity (resting).',
      'In minute 9 it finished resting.',
      'Its next applied decision was in minute 10.',
    ]);
    expect(view.told).toContain('Tiredness 800 of 1000; its routine rests from 700.');
    expect(view.told).toContain('A walker; 9 m away; resting; cannot hear it.');
    expect(view).toMatchObject({ servedModel: MODEL, responseTime: '2.40 s', tokens: '400 in, 120 out.', cost: '$0.00005000, as reported for the call.' });
    expect(allWords(view)).not.toMatch(INNER_LIFE);
  });

  it('says a timed-out request no minute has taken up applied nothing, and names neither a routine decision nor a served model', () => {
    const detail: SocietyDecisionDetail = {
      status: 'completed',
      request: request('timeout', 3),
      decision: {
        request_id: 'timeout', status: 'unavailable', reason: 'model_timed_out', proposal: null,
        provider: provider({ served_model_id: null, prompt_tokens: 0, completion_tokens: 0, cost_usd: '0.00050000', cost_known: false,
          calls: [{ served_model: null, prompt_tokens: null, completion_tokens: null, cost_basis: 'unknown' }] }),
      },
    };
    const view = explainDecisionRecord(detail, latest({}), []);
    expect(view.chosen).toBeNull();
    expect(view.answer).toBe('There was no usable answer: it did not answer in time. This is not a decision by the model or by the routine.');
    expect(view.applied).toBe('Nothing was applied from it. No minute has taken it up yet.');
    expect(view.changed).toEqual(['Nothing changed in the world from this answer.']);
    // The requested model never stands in for the served one, and unreported tokens are not zero.
    expect(view.asked).toBe('Small Open Model');
    expect(view.servedModel).toBe('Not reported.');
    expect(view.tokens).toBe('Not reported.');
    expect(view.cost).toBe('Not known. The ledger charged its reservation of $0.00050000, the most the call can have cost.');
    expect(allWords(view)).not.toMatch(/minute 4|routine decided/u);
  });

  it('records a wait as staying put, with waiting a valid answer', () => {
    const events = page([event(4, 'decision_applied', { request_id: 'wait', disposition: 'applied', reason: 'validated_choice' })]);
    const view = explainDecisionRecord(answered('wait', 'wait here a minute'), null, events);
    expect(view.applied).toBe('Applied in minute 4.');
    expect(view.changed).toEqual(['No movement was recorded for it from minute 4 in the minutes read since: it stayed where it was.']);
    expect(view.limits).toContain('Waiting is a valid answer: it chose to stay where it was for the minute.');
  });

  it('says why a minute did not apply an accepted answer, and that the routine decided that minute', () => {
    const events = page([event(4, 'decision_applied', { request_id: 'go', disposition: 'rejected', reason: 'place_taken_this_minute' })]);
    const view = explainDecisionRecord(answered('go', 'resting, 60 m away (1)'), null, events);
    expect(view.applied).toBe('Not applied in minute 4, because someone else took that place first, so its routine decided that minute.');
    expect(view.appliedAt).toBeNull();
    expect(view.changed).toEqual(['Nothing changed in the world from this answer.']);
  });

  it('keeps an accepted answer no minute has acted on apart from an applied one', () => {
    const view = explainDecisionRecord(answered('go', 'resting, 60 m away (1)'), latest({ requestId: 'go', status: 'accepted', reason: 'validated_choice', chose: 'resting, 60 m away (1)' }), []);
    expect(view.applied).toBe('Not applied yet: no minute has acted on it.');
    expect(view.changed).toEqual(['Nothing has changed from it yet.']);
  });

  it('says what changed is unknown where the read does not reach back to the minute that applied it', () => {
    const later = page([event(12, 'decision_applied', { request_id: 'other', disposition: 'applied' })]);
    const latestGo = latest({ requestId: 'go', status: 'accepted', reason: 'validated_choice', consumedTick: 4, disposition: 'applied' });
    expect(explainDecisionRecord(answered('go', 'resting, 60 m away (1)'), latestGo, later).changed)
      .toEqual(['The events of minute 4 are older than this read, so what changed is not shown.']);
  });
});

describe('the events a record reads', () => {
  it('leaves out an event it cannot read, and refuses what is not an events page', () => {
    const events = page([event(4, 'blocked', { reason: 'validated_model_wait' }), { tick: 'x' }, null]);
    expect(events.map((one) => one.kind)).toEqual(['blocked']);
    expect(() => parseDecisionEvents({ rows: [] })).toThrow('Invalid society events');
  });

  it('measures only the being\'s own path from the applied minute', () => {
    const other = page([event(4, 'route_progressed', { motion_path_mm: [[0, 0], [5000, 0]] })]).map((one) => ({ ...one, subjectId: 'someone-else' }));
    expect(decisionChange([...other, ...walk], BEING, 'go', 4).walked).toEqual([{ minute: 4, metres: 40 }, { minute: 5, metres: 20 }]);
  });

  it('lists the being\'s decisions the read knows of, newest first', () => {
    expect(knownDecisions(BEING, latest({ baseTick: 11 }), walk)).toEqual([
      { requestId: 'timeout', minute: 11, words: 'Asked at minute 11: no option chosen' },
      { requestId: 'later', minute: 10, words: 'Minute 10, applied: “wait here a minute”' },
      { requestId: 'go', minute: 4, words: 'Minute 4, applied: “resting, 60 m away (1)”' },
    ]);
  });
});
