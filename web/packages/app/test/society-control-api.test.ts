import { describe, expect, it, vi } from 'vitest';
import { SocietyControlClient, parseLivingSession, parseSocietyControl } from '../src/society-control-api.js';

const version = 'version';
const control = {
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: version,
  persisted: true, revision: 2, mode: 'paused', speed: 2,
  base_tick_interval_ms: 1000, tick_interval_ms: 500,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 1, current_tick: 4, state_sha256: 'a'.repeat(64),
  play_ineligible_reason: null, play_eligible: true,
};

describe('society playback client', () => {
  it('parses exact persisted timing semantics', () => {
    expect(parseSocietyControl(control, version)).toMatchObject({
      mode: 'paused', speed: 2, tickIntervalMs: 500, currentTick: 4,
    });
    expect(() => parseSocietyControl({ ...control, speed: 3 }, version)).toThrow('playback response');
    expect(() => parseSocietyControl({ ...control, branch_id: 'other' }, version)).toThrow('playback response');
  });

  it('writes the current revision and requested mode through PUT', async () => {
    const fetcher = vi.fn(async (_url, _init) => new Response(JSON.stringify({
      ...control, revision: 3, mode: 'playing', speed: 4,
    }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const client = new SocietyControlClient({
      baseUrl: 'https://example.test', token: 'token', worldId: 'world:personal:control', fetch: fetcher as typeof fetch,
    });
    await client.configure(parseSocietyControl(control, version), 'playing', 4);
    expect(fetcher.mock.calls[0]![1]?.method).toBe('PUT');
    expect(String(fetcher.mock.calls[0]![0])).toContain(`world_id=${encodeURIComponent('world:personal:control')}`);
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({ base_revision: 2, mode: 'playing', speed: 4 });
  });

  it('reads the latest living session, its closing fields null exactly while it is open', () => {
    const open = parseSocietyControl({ ...control, session: openSession }, version);
    expect(open.livingSession).toEqual({
      sessionId: 'session-1', state: 'open',
      limits: { wallSeconds: 3600, minutes: 60, decisions: 10, usd: '1.00000000', calls: 100 },
      used: { wallSeconds: 12, minutes: 2, decisions: 3, usd: '0.00120000', calls: 3, unresolved: { count: 1, usd: '0.00040000' } },
      startTick: 4, openedAt: '2026-10-14T01:00:00+00:00', endsBy: '2026-10-14T02:00:00+00:00',
      endTick: null, closedAt: null, closedReason: null, closedReasonWords: null,
    });
    const closed = parseSocietyControl({ ...control, session: { ...openSession, ...closing } }, version);
    expect(closed.livingSession).toMatchObject({
      state: 'closed', endTick: 7, closedReason: 'session_decisions', closedReasonWords: closing.closed_reason_words,
    });
    expect(parseSocietyControl({ ...control, session: null }, version).livingSession).toBeNull();
    expect('livingSession' in parseSocietyControl(control, version)).toBe(false);
    for (const wrong of [
      { ...openSession, end_tick: 7 },
      { ...openSession, ...closing, closed_reason: null },
      { ...openSession, ...closing, closed_reason_words: null },
      { ...openSession, closed_reason_words: 'An open session has no reason.' },
      { ...openSession, used: { ...openSession.used, usd: '0.0012' } },
      { ...openSession, state: 'ended' },
    ]) {
      expect(() => parseSocietyControl({ ...control, session: wrong }, version)).toThrow('playback response');
    }
  });

  it('reads one session with its bounds, decisions in order and measures', async () => {
    const fetcher = vi.fn(async (_url, _init) => new Response(JSON.stringify(sessionRead), {
      status: 200, headers: { 'content-type': 'application/json' },
    }));
    const client = new SocietyControlClient({
      baseUrl: 'https://example.test', token: 'token', worldId: 'world:personal:control', fetch: fetcher as typeof fetch,
    });
    const read = await client.readSession(version, 'session-1');
    expect(String(fetcher.mock.calls[0]![0])).toContain('/world/versions/version/society/control/sessions/session-1?');
    expect(read).toMatchObject({
      state: 'closed', closedReason: 'session_decisions', closedReasonWords: closing.closed_reason_words, endTick: 7,
    });
    expect(read.decisions.map((one) => [one.requestId, one.decider, one.consumedTick, one.status, one.reason])).toEqual([
      ['request-1', 'model', 5, 'accepted', 'validated_choice'], ['request-2', 'person', null, 'accepted', 'validated_choice'],
    ]);
    expect(read.bounds[0]).toMatchObject({ provider: 'nebius', state: 'closed', committedCalls: 3, unresolved: { count: 1, usd: '0.00040000' } });
    expect(read.measures.counts.decisions).toBe(1);
    expect(read.byModel.map((one) => one.modelId)).toEqual(['open/model']);
    expect(read.decisionsRead).toEqual({ counted: 2, maximum: 2000, total: 2 });
    expect(() => parseLivingSession(sessionRead, 'session-2')).toThrow('playback response');
    expect(() => parseLivingSession({ ...sessionRead, decisions: [...sessionRead.decisions].reverse() }, 'session-1'))
      .toThrow('playback response');
  });
});

const limits = { wall_seconds: 3600, minutes: 60, decisions: 10, usd: '1.00000000', calls: 100 };
const used = { wall_seconds: 12, minutes: 2, decisions: 3, usd: '0.00120000', calls: 3, unresolved: { count: 1, usd: '0.00040000' } };
const openSession = {
  session_id: 'session-1', state: 'open', limits, used, start_tick: 4,
  opened_at: '2026-10-14T01:00:00+00:00', ends_by: '2026-10-14T02:00:00+00:00',
  end_tick: null, closed_at: null, closed_reason: null, closed_reason_words: null,
};
const closing = {
  state: 'closed', end_tick: 7, closed_at: '2026-10-14T01:05:00+00:00', closed_reason: 'session_decisions',
  closed_reason_words: 'The session used all the model decisions it was given.',
};
const rate = { numerator: 0, denominator: 0, minimum: 5, value: null };
const measures = {
  counts: { decisions: 1, answered: 1, refused: 0, unavailable: 0, timeouts: 0, stale: 0, applied: 1, not_applied: 0, pending: 0 },
  rates: { acceptance: rate, applied: rate, repeated_choice: rate, repeated_line: rate },
  timeouts: { longest_streak: 0, current_streak: 0 },
  repetition: { longest_choice_run: 1, longest_line_run: 0 },
  latency_ms: { n: 1, minimum: 5, p50: null, p95: null, longest: null },
  cost: { usd: '0.00040000', known_usd: '0.00040000', reserved_usd: '0.00000000', basis: 'computed', unknown_calls: 0, calls: 1 },
};
const sessionRead = {
  profile: 'exulanica.society-session/v1', session_id: 'session-1', state: 'closed',
  opened: {
    event_seq: 3, request_id: 'opening', reason: 'opened_by_person', opened_by: 'account', limits,
    start_tick: 4, start_state_sha256: 'a'.repeat(64), opened_at: openSession.opened_at, ends_by: openSession.ends_by,
  },
  closed: {
    event_seq: 9, reason: 'session_decisions', closed_by: null, end_tick: 7,
    end_state_sha256: 'b'.repeat(64), closed_at: closing.closed_at, words: closing.closed_reason_words,
  },
  used,
  bounds: [{
    provider: 'nebius', bound_id: 'bound', state: 'closed', ceiling_usd: '1.00000000', max_calls: 100,
    valid_until: '2026-10-14T02:00:00+00:00', committed_usd: '0.00120000', committed_calls: 3,
    in_flight_usd: '0.00000000', unresolved: { count: 1, usd: '0.00040000' },
    known_usage_usd: '0.00080000', reconciled_usd: '0.00000000',
  }],
  decisions: [
    { request_id: 'request-1', decision_seq: 1, role: 'people', subject_id: 'ada', decider: 'model', base_tick: 4, consumed_tick: 5, status: 'accepted', reason: 'validated_choice' },
    { request_id: 'request-2', decision_seq: 2, role: 'people', subject_id: 'bo', decider: 'person', base_tick: 6, consumed_tick: null, status: 'accepted', reason: 'validated_choice' },
  ],
  decisions_read: { counted: 2, maximum: 2000, total: 2 },
  measures,
  by_model: [{ provider: 'nebius', model_id: 'open/model', measures }],
};
