// A recorded decision explained from its records alone: what was told, offered and chosen, what the
// engine and the minute did with it, what the being's events record after it, and what the call
// cost. Records here are written by hand in the decision route's and the events route's shapes.
import { describe, expect, it } from 'vitest';
import accountWordsText from '../../../../assets/catalogs/roles/choice-account-words.v2.json?raw';
import {
  ACCOUNT_WORDS, VERDICT_ORDER, choiceAccount, choiceTimeline, decisionChange, explainDecisionRecord,
  knownDecisions, parseDecisionEvents, rewind, type DecisionEvent,
} from '../src/decision-record.js';
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
    expect(view.answer).toBe('The engine accepted the answer: their model chose one of the things they could do.');
    expect(view.applied).toBe('Done in minute 4.');
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
    expect(view).toMatchObject({ servedModel: MODEL, responseTime: '2.40 s', tokens: '400 in, 120 out.', cost: '$0.00005000, computed from the reported tokens at the listed price.' });
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
    expect(view.answer).toBe('There was no usable answer: their model did not answer in time. This is not a decision by the model or by the routine.');
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
    expect(view.applied).toBe('Done in minute 4.');
    expect(view.changed).toEqual(['No movement was recorded for it from minute 4 in the minutes read since: it stayed where it was.']);
    expect(view.limits).toContain('Waiting is a valid answer: it chose to stay where it was for the minute.');
  });

  it('says why a minute did not apply an accepted answer, and that the routine decided that minute', () => {
    const events = page([event(4, 'decision_applied', { request_id: 'go', disposition: 'rejected', reason: 'place_taken_this_minute' })]);
    const view = explainDecisionRecord(answered('go', 'resting, 60 m away (1)'), null, events);
    expect(view.applied).toBe('Not applied in minute 4, because someone else took that place first, so the routine decided that minute.');
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

/** A record as the route serves it: request and receipt digests, and the receipt's decision order. */
const stored = (id: string, label: string | null, seq: number, extra: { status?: string; reason?: string; line?: string } = {}): SocietyDecisionDetail => {
  const base = answered(id, label, extra.status, extra.reason);
  const decision = base.decision!;
  const proposal = decision['proposal'] as Record<string, unknown> | null;
  return {
    ...base,
    request: { ...base.request, document_sha256: `request-${id}` },
    decision: {
      ...decision, decision_seq: seq, document_sha256: `receipt-${id}`,
      proposal: proposal === null || extra.line === undefined ? proposal : { ...proposal, line: extra.line },
    },
  };
};
const closed = (tick: number, id: string, seq: number, disposition = 'applied', reason = 'validated_choice', chose: string | null = null): unknown => ({
  event_id: `event-${id}`, tick, event_kind: 'decision_applied', subject_id: BEING,
  document: { order: 5, request_id: id, decision_seq: seq, disposition, reason, chose, motion_path_mm: [[0, 0]] },
});

describe('a choice told in four parts with one verdict', () => {
  it('labels what was observed and what was reported, and points each part at its stored record', () => {
    const events = page([...[closed(4, 'go', 1, 'applied', 'validated_choice', 'resting, 60 m away (1)')],
      event(4, 'route_progressed', { motion_path_mm: [[0, 0], [30000, 0]] }, 1)]);
    const account = choiceAccount(stored('go', 'resting, 60 m away (1)', 1, { line: 'Off to rest.' }), null, events);
    expect(account.parts.map((part) => [part.part, part.provenance])).toEqual([
      ['saw', 'observed'], ['answered', 'reported'], ['checked', 'observed'], ['did', 'observed'],
    ]);
    expect(account.parts[0].records).toEqual([{ kind: 'request', id: 'go', sha256: 'request-go' }]);
    expect(account.parts[1].lines).toEqual(['It answered “resting, 60 m away (1)”.', 'It proposed to say: “Off to rest.”']);
    expect(account.parts[2].records).toEqual([{ kind: 'receipt', id: 'go', sha256: 'receipt-go' }]);
    expect(account.parts[3].records[0]).toEqual({ kind: 'event', id: 'event-go', sha256: null });
    expect(account.verdict).toEqual({ kind: 'applied', reason: 'validated_choice', words: 'Done in minute 4.' });
    expect(account.decisionSeq).toBe(1);
    expect(account.inferred).toEqual([]);
  });

  it('gives the first verdict that holds, in a fixed order, naming the reason', () => {
    expect(VERDICT_ORDER).toEqual(['awaiting_answer', 'refused', 'no_answer', 'stale', 'not_applied', 'pending', 'applied']);
    const verdict = (detail: SocietyDecisionDetail, events: readonly DecisionEvent[] = []) => choiceAccount(detail, null, events).verdict;
    expect(verdict({ ...stored('a', null, 1), status: 'in_progress', decision: null }).kind).toBe('awaiting_answer');
    expect(verdict(stored('a', null, 1, { status: 'rejected', reason: 'answer_not_offered' }))).toEqual({
      kind: 'refused', reason: 'answer_not_offered', words: 'Refused: their model did not answer with one of the things they could do.',
    });
    // A timeout is nobody's decision; the routine is named only once a minute has run without it.
    expect(verdict(stored('a', null, 1, { status: 'unavailable', reason: 'model_timed_out' })).words)
      .toBe('No usable answer: their model did not answer in time. No minute has taken it up yet.');
    expect(verdict(stored('a', null, 1, { status: 'unavailable', reason: 'model_timed_out' }), page([closed(4, 'a', 1, 'unavailable', 'model_timed_out')])).words)
      .toBe('No usable answer: their model did not answer in time. The routine acted in minute 4.');
    expect(verdict(stored('a', 'wait here a minute', 1), page([closed(4, 'a', 1, 'stale', 'decision_context_changed')])).kind).toBe('stale');
    expect(verdict(stored('a', 'wait here a minute', 1), page([closed(4, 'a', 1, 'rejected', 'place_taken_this_minute')]))).toEqual({
      kind: 'not_applied', reason: 'place_taken_this_minute', words: 'Chosen but not done in minute 4: someone else took that place first.',
    });
    expect(verdict(stored('a', 'wait here a minute', 1)).kind).toBe('pending');
    // A missing answer is observed, never reported.
    expect(choiceAccount(stored('a', null, 1, { status: 'unavailable', reason: 'model_timed_out' }), null, []).parts[1].provenance).toBe('observed');
  });

  it('infers repetition and a walk with no movement only by named rules, against the previous record', () => {
    const events = page([
      closed(4, 'one', 1, 'applied', 'validated_choice', 'stand a while nearby'),
      closed(8, 'two', 2, 'applied', 'validated_choice', 'stand a while nearby'),
    ]);
    const one = stored('one', 'stand a while nearby', 1, { line: 'Hello.' });
    const two = stored('two', 'stand a while nearby', 2, { line: 'Hello.' });
    const account = choiceAccount(two, null, events, one);
    expect(account.inferred.map((item) => [item.rule, item.provenance])).toEqual([
      ['repeat-choice.v1', 'inferred'], ['repeat-line.v1', 'inferred'],
    ]);
    expect(account.inferred[0]!.records).toEqual([
      { kind: 'receipt', id: 'one', sha256: 'receipt-one' }, { kind: 'receipt', id: 'two', sha256: 'receipt-two' },
    ]);
    // A line proposed but never applied was never said, so it is not a repeat.
    const notSaid = page([closed(4, 'one', 1, 'rejected', 'no_room_to_stand'), closed(8, 'two', 2)]);
    expect(choiceAccount(two, null, notSaid, one).inferred.map((item) => item.rule)).toEqual(['repeat-choice.v1']);
    // An applied walk with no recorded movement before the next applied decision.
    const still = page([closed(4, 'go', 1), closed(9, 'next', 2)]);
    expect(choiceAccount(stored('go', 'resting, 60 m away (1)', 1), null, still).inferred.map((item) => item.rule))
      .toEqual(['applied-go-without-movement.v1']);
    const parts = choiceAccount(two, null, events, one);
    const said = [parts.verdict.words, ...parts.parts.flatMap((part) => part.lines), ...parts.inferred.map((item) => item.words)].join(' ');
    expect(said).not.toMatch(INNER_LIFE);
  });
});

describe('what a choice\'s Did part points at', () => {
  it('stops at the next applied decision, as its sentences do', () => {
    const move = (tick: number, id: string): unknown => ({ ...event(tick, 'route_progressed', { motion_path_mm: [[0, 0], [5000, 0]] }, 1) as object, event_id: id });
    const events = page([
      closed(4, 'first', 1, 'applied', 'validated_choice', 'resting, 60 m away (1)'), move(4, 'walk-4'), move(5, 'walk-5'),
      closed(13, 'second', 2, 'applied', 'validated_choice', 'wait here a minute'), move(18, 'walk-18'),
    ]);
    const did = choiceAccount(stored('first', 'resting, 60 m away (1)', 1), null, events).parts[3];
    expect(did.lines).toContain('Its next applied decision was in minute 13.');
    // Its own closing event and the walks before minute 13; never a later choice's events.
    expect(did.records.map((record) => record.id)).toEqual(['event-first', 'walk-4', 'walk-5']);
  });
});

describe('rewinding a being\'s choices', () => {
  it('steps through them oldest first by decision order, ending with one no minute has taken up', () => {
    const events = page([
      closed(9, 'second', 2, 'applied', 'validated_choice', 'stand a while nearby'),
      closed(4, 'first', 1, 'applied', 'validated_choice', 'resting, 60 m away (1)'),
      { ...closed(6, 'elsewhere', 3) as object, subject_id: 'someone-else' },
    ]);
    const timeline = choiceTimeline(BEING, latest({ requestId: 'third', decisionSeq: 4, baseTick: 12 }), events);
    expect(timeline.map((entry) => [entry.requestId, entry.decisionSeq, entry.minute, entry.takenUp])).toEqual([
      ['first', 1, 4, true], ['second', 2, 9, true], ['third', 4, 12, false],
    ]);
    expect(rewind(timeline, 'second')).toEqual({ index: 1, total: 3, previous: timeline[0], next: timeline[2] });
    expect(rewind(timeline, 'first')!.previous).toBeNull();
    expect(rewind(timeline, 'missing')).toBeNull();
  });
});

describe('the shared choice account words', () => {
  it('are the catalog the server reads too, in the account\'s verdict order', () => {
    const catalog = JSON.parse(accountWordsText) as {
      verdict_order: string[]; entries: { kind: string; code: string; words: string }[];
    };
    const table = (kind: string) => Object.fromEntries(
      catalog.entries.filter((entry) => entry.kind === kind).map((entry) => [entry.code, entry.words]));
    expect(ACCOUNT_WORDS.verdicts).toEqual(table('verdict'));
    expect(ACCOUNT_WORDS.continuations).toEqual(table('continuation'));
    expect(ACCOUNT_WORDS.reasons).toEqual(table('reason_phrase'));
    expect(Object.keys(ACCOUNT_WORDS.verdicts).sort()).toEqual([...VERDICT_ORDER].sort());
    expect([...VERDICT_ORDER]).toEqual(catalog.verdict_order);
  });
});
