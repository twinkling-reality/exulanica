import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { createLiveSociety, type LiveSocietyView } from '../src/composition/live-society.js';
import { parseSociety, type SocietySnapshot, type SocietyEvent } from '../src/society-api.js';

function snapshot(tick = 0): SocietySnapshot {
  return parseSociety({ society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'place',
    population_size: 100, current_tick: tick, state_sha256: 'a'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
    state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick, input_seq: 1, input_sha256: 'b'.repeat(64),
      inhabitants: Array.from({ length: 100 }, (_, i) => ({ id: `person-${i}`, synthetic: true, position_mm: [i, 0],
        display_name: `Person ${i}`, role: 'steward', goal: null, route: null, motion_path_mm: [[i, 0]],
        action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
        explanation: { summary: 'Awaiting a supported goal.', event_ids: tick ? ['event', 'older-event'] : [] } })) } });
}
const event: SocietyEvent = { event_id: 'event', subject_id: 'person-0', tick: 1, event_kind: 'replanned', document_sha256: 'c'.repeat(64),
  document: { synthetic: true, summary: 'Target removed.', reason: 'target_disabled_or_removed' } };
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
function setup() {
  const views: LiveSocietyView[] = [];
  const client = { connect: vi.fn(async () => snapshot()), read: vi.fn(async () => snapshot(1)),
    advance: vi.fn(async () => snapshot(1)), events: vi.fn(async (): Promise<readonly SocietyEvent[]> => [event]) };
  const options = { preview: false, credentials: { baseUrl: 'https://example.test', token: 'test' }, versionId: 'branch', placeId: 'place', regionId: 'region',
    onChange: (view: LiveSocietyView) => views.push(view), client };
  return { client, views, options, live: createLiveSociety(options) };
}

describe('authenticated society composition', () => {
  it('connects to purposeful persisted state and exposes canonical selected reasons independently of nearby rendering', async () => {
    const { live, client } = setup();
    await live.connect();
    expect(client.connect).toHaveBeenCalledWith('branch', 'place', 'region', 'exulanica-society/v2');
    await live.advance();
    expect(live.inspect('person-0').events[0]?.document['reason']).toBe('target_disabled_or_removed');
    expect(live.inspect('person-0').missingEventIds).toEqual(['older-event']);
    expect(live.inspect('person-99').inhabitant?.id).toBe('person-99');
    expect(live.inspect('unknown').inhabitant).toBeNull();
  });
  it('keeps a preceding causal replan visible when the latest explanation references only arrival', async () => {
    const { live, client } = setup();
    const replan = { ...event, event_id: 'replan', document: { synthetic: true as const, summary: 'Marker removed.', reason: 'target_disabled_or_removed' } };
    client.events.mockResolvedValue([replan, event]); await live.connect(); await live.advance();
    expect(live.inspect('person-0').events.map(row => row.event_id)).toEqual(['replan', 'event']);
    expect(live.inspect('person-1').events).toEqual([]);
    expect(live.inspect('person-0').missingEventIds).toEqual(['older-event']);
  });
  it('coalesces overlapping advances and reloads a stale write without retrying it', async () => {
    const { live, client } = setup(); await live.connect();
    client.advance.mockRejectedValueOnce(new ApiError(409, 'stale_society_state', 'changed'));
    await Promise.all([live.advance(), live.advance()]);
    expect(client.advance).toHaveBeenCalledTimes(1);
    expect(client.read).toHaveBeenCalledTimes(1);
    expect(live.view.status).toBe('stale');
    expect(live.view.snapshot?.currentTick).toBe(1);
  });
  it('does not treat any other conflict as a stale CAS or silently retry an ambiguous network write', async () => {
    for (const error of [new ApiError(409, 'invalid_society_state', 'invalid'), new Error('connection lost')]) {
      const { live, client } = setup(); await live.connect(); client.advance.mockRejectedValueOnce(error);
      await live.advance(); await live.advance();
      expect(client.advance).toHaveBeenCalledTimes(1); expect(client.read).not.toHaveBeenCalled();
      expect(live.view.status).toBe('unavailable');
    }
  });
  it.each([401, 403, 404, 424])('clears previously visible state if event authorization fails with %s', async status => {
    const { live, client } = setup(); await live.connect();
    client.events.mockRejectedValueOnce(new ApiError(status, 'unavailable', 'gone'));
    await live.refresh();
    expect(live.view.snapshot).toBeNull(); expect(live.view.events).toEqual([]);
    await live.advance(); expect(client.advance).not.toHaveBeenCalled();
  });
  it('keeps last canonical state but discloses unavailable event reads', async () => {
    const { live, client } = setup(); await live.connect(); client.events.mockRejectedValueOnce(new Error('offline'));
    await live.refresh(); expect(live.view.snapshot?.currentTick).toBe(1);
    expect(live.view.eventsAvailable).toBe(false); expect(live.inspect('person-0').missingEventIds).toEqual(['event', 'older-event']);
  });
  it('preserves edit notification during an in-flight step, refreshing without rewinding history or issuing another step', async () => {
    const { live, client } = setup(); await live.connect(); const held = deferred<SocietySnapshot>(); client.advance.mockReturnValueOnce(held.promise);
    const advancing = live.advance(); await Promise.resolve(); const edited = live.afterAuthoredEdit();
    held.resolve(snapshot(1)); await advancing; await edited;
    expect(client.read).toHaveBeenCalledTimes(1); expect(client.advance).toHaveBeenCalledTimes(1);
    expect(live.view.message).toContain('retains earlier simulation events');
  });
  it('reopening reads retained state, without issuing a progression action', async () => {
    const { live, client, options } = setup(); await live.connect(); await live.advance(); live.dispose();
    client.connect.mockResolvedValueOnce(snapshot(1)); const reopened = createLiveSociety(options); await reopened.connect();
    expect(reopened.view.snapshot?.currentTick).toBe(1); expect(client.advance).toHaveBeenCalledTimes(1);
  });
  it('ignores late replies after disposal and releases held state', async () => {
    const { live, client, views } = setup(); const held = deferred<SocietySnapshot>(); client.connect.mockReturnValueOnce(held.promise);
    const connecting = live.connect(); await Promise.resolve(); live.dispose(); const count = views.length;
    held.resolve(snapshot()); await connecting;
    expect(views).toHaveLength(count); expect(client.events).not.toHaveBeenCalled(); expect(live.view.snapshot).toBeNull();
  });
  it('rejects preview, other branch, other place, and unsupported engine profiles', async () => {
    const { options } = setup(); expect(() => createLiveSociety({ ...options, preview: true })).toThrow(/preview/);
    for (const changed of [{ versionId: 'other' }, { placeId: 'other' }, { state: { ...snapshot().state, profile: 'exulanica-society/v1' as const } }]) {
      const { live, client } = setup(); client.connect.mockResolvedValueOnce({ ...snapshot(), ...changed }); await live.connect();
      expect(live.view.status).toBe('unavailable'); expect(live.view.snapshot).toBeNull(); expect(client.events).not.toHaveBeenCalled();
    }
  });
  it('parent session cancellation clears held state and blocks subsequent requests', async () => {
    const { options, client } = setup(); const abort = new AbortController();
    const live = createLiveSociety({ ...options, credentials: { ...options.credentials, signal: abort.signal } });
    await live.connect(); abort.abort(); await live.refresh(); await live.advance();
    expect(live.view.snapshot).toBeNull(); expect(client.read).not.toHaveBeenCalled(); expect(client.advance).not.toHaveBeenCalled();
  });
  it('a disposed old session cannot overwrite a newly connected view', async () => {
    const { options, client, views } = setup(); const held = deferred<SocietySnapshot>();
    client.connect.mockReturnValueOnce(held.promise); const old = createLiveSociety(options);
    const connecting = old.connect(); await Promise.resolve(); old.dispose();
    client.connect.mockResolvedValueOnce(snapshot(8)); const current = createLiveSociety(options); await current.connect();
    held.resolve(snapshot(0)); await connecting;
    expect(views.at(-1)?.snapshot?.currentTick).toBe(8);
  });
  it('aborts real transport on disposal and never sends credentials to preview', async () => {
    const { options } = setup(); let signal: AbortSignal | null | undefined;
    const fetch = vi.fn(async (_url: unknown, init?: RequestInit) => { signal = init?.signal; return new Promise<Response>(() => undefined); });
    const { client: _injected, ...transportOptions } = options;
    const live = createLiveSociety({ ...transportOptions, credentials: { ...options.credentials, fetch } });
    void live.connect(); await Promise.resolve(); live.dispose(); expect(signal?.aborted).toBe(true);
  });
});
