import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { createLiveSociety, type LiveSocietyView } from '../src/composition/live-society.js';
import { parseSociety, type SocietyEvent, type SocietyProfile, type SocietySnapshot } from '../src/society-api.js';

/*
 * In a saved world a society exists only because the person asked for one. Opening the world
 * reads; it never creates. The person's request creates it, and a refusal is kept to be said.
 */

function snapshot(tick = 0, place = 'derived-place'): SocietySnapshot {
  return parseSociety({ society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: place,
    population_size: 100, current_tick: tick, state_sha256: 'a'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
    state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick, input_seq: 1, input_sha256: 'b'.repeat(64),
      inhabitants: Array.from({ length: 100 }, (_, i) => ({ id: `person-${i}`, synthetic: true, position_mm: [i, 0],
        display_name: `Person ${i}`, role: 'steward', goal: null, route: null, motion_path_mm: [[i, 0]],
        action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
        explanation: { summary: 'Awaiting a supported goal.', event_ids: [] } })) } });
}
const missing = () => new ApiError(404, 'unknown_reference', 'no such society');

function setup(profileWhenAsked?: () => Promise<SocietyProfile>) {
  const views: LiveSocietyView[] = [];
  const client = {
    connect: vi.fn(async () => snapshot()),
    create: vi.fn(async () => snapshot()),
    read: vi.fn(async (): Promise<SocietySnapshot> => { throw missing(); }),
    advance: vi.fn(async () => snapshot(1)),
    events: vi.fn(async (): Promise<readonly SocietyEvent[]> => []),
  };
  const live = createLiveSociety({
    preview: false, credentials: { baseUrl: 'https://example.test', token: 'test' },
    worldId: 'world:authored:one', versionId: 'branch', placeId: null, regionId: 'region:starter',
    profile: 'exulanica-society/v2', createOnConnect: false, places: true,
    onChange: (view) => views.push(view), client,
    ...(profileWhenAsked ? { profileWhenAsked } : {}),
  });
  return { client, views, live };
}

describe('a saved world society is created only when the person asks', () => {
  it('opening a world with nobody in it reads, finds nobody, and creates nothing', async () => {
    const { live, client } = setup();
    await live.connect();
    expect(client.read).toHaveBeenCalledWith('branch', { places: true });
    expect(client.connect).not.toHaveBeenCalled();
    expect(client.create).not.toHaveBeenCalled();
    expect(live.view.status).toBe('absent');
    expect(live.view.snapshot).toBeNull();
    // A refresh in the same state stays an answer, not a failure.
    await live.refresh();
    expect(live.view.status).toBe('absent');
  });

  it('the request creates the v2 society with no place named, then reads it back with its places', async () => {
    const { live, client } = setup();
    await live.connect();
    client.read.mockResolvedValue(snapshot());
    await live.bringIn();
    expect(client.create).toHaveBeenCalledWith('branch', null, 'region:starter', 'exulanica-society/v2');
    expect(client.read).toHaveBeenLastCalledWith('branch', { places: true });
    expect(live.view.status).toBe('ready');
    expect(live.view.snapshot?.placeId).toBe('derived-place');
    expect(live.view.refusal).toBeNull();
  });

  it('keeps the server refusal to be said and stays without a society', async () => {
    const { live, client } = setup();
    await live.connect();
    client.create.mockRejectedValueOnce(
      new ApiError(409, 'no_reachable_targets', 'initial society requires reachable targets'),
    );
    await live.bringIn();
    expect(live.view.status).toBe('absent');
    expect(live.view.refusal).toEqual({
      status: 409, code: 'no_reachable_targets', detail: 'initial society requires reachable targets',
    });
    client.read.mockResolvedValue(snapshot());
    await live.bringIn();
    expect(live.view.refusal).toBeNull();
    expect(live.view.status).toBe('ready');
  });

  it('pins the place the server named and refuses a later snapshot from another', async () => {
    const { live, client } = setup();
    client.read.mockResolvedValue(snapshot());
    await live.connect();
    client.read.mockResolvedValue(snapshot(1, 'another-place'));
    await live.refresh();
    expect(live.view.status).toBe('unavailable');
    expect(live.view.message).toMatch(/does not match the connected world/);
  });

  it('reads places back after a step, whose own body carries none', async () => {
    const { live, client } = setup();
    client.read.mockResolvedValue(snapshot());
    await live.connect();
    client.read.mockResolvedValue(snapshot(1));
    await live.advance();
    expect(client.advance).toHaveBeenCalledTimes(1);
    expect(client.read).toHaveBeenLastCalledWith('branch', { places: true });
    expect(live.view.snapshot?.currentTick).toBe(1);
  });

  it('asks for the engine the world states when the person asks, and once more when the server says it differs', async () => {
    // The entry, read when asked, says a placed thing makes a society of things here.
    const asked = vi.fn(async (): Promise<SocietyProfile> => 'exulanica-society/v7');
    const { live, client } = setup(asked);
    await live.connect();
    client.read.mockResolvedValue(snapshot());
    await live.bringIn();
    expect(client.create).toHaveBeenLastCalledWith('branch', null, 'region:starter', 'exulanica-society/v7');
    // A thing placed between the read and the request: refused by name, read again, asked once more.
    asked.mockResolvedValueOnce('exulanica-society/v2').mockResolvedValueOnce('exulanica-society/v7');
    client.create.mockClear();
    client.create.mockRejectedValueOnce(new ApiError(409, 'society_engine_differs', 'this world takes exulanica-society/v7'));
    await live.bringIn();
    expect(client.create.mock.calls.map((call) => (call as unknown[])[3])).toEqual(['exulanica-society/v2', 'exulanica-society/v7']);
    expect(live.view.refusal).toBeNull();
    // An entry that cannot be read asks for the engine the world opened with; the server guards it.
    asked.mockRejectedValueOnce(new Error('offline'));
    client.create.mockClear();
    await live.bringIn();
    expect(client.create).toHaveBeenLastCalledWith('branch', null, 'region:starter', 'exulanica-society/v2');
  });
});
