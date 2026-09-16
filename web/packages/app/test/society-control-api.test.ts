import { describe, expect, it, vi } from 'vitest';
import { SocietyControlClient, parseSocietyControl } from '../src/society-control-api.js';

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
    const client = new SocietyControlClient({ baseUrl: 'https://example.test', token: 'token', fetch: fetcher as typeof fetch });
    await client.configure(parseSocietyControl(control, version), 'playing', 4);
    expect(fetcher.mock.calls[0]![1]?.method).toBe('PUT');
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({ base_revision: 2, mode: 'playing', speed: 4 });
  });
});
