import { describe, expect, it, vi } from 'vitest';
import { SocietyClient, parseSociety } from '../src/society-api.js';
import { SocietyControlClient, parseSocietyControl } from '../src/society-control-api.js';

/*
 * A saved world's version belongs to that world, and the server reads a version only in the world
 * a request names. These pin that every society and playback request from a saved world names it,
 * that a person's own request creates a society without naming a place, and that the places a
 * read carries belong to the input the state consumed.
 */

const WORLD = 'world:authored:0b6f5a0e-7d7f-4c3e-9a55-5a6f2d1c9e10';
const QUERY = `world_id=${encodeURIComponent(WORLD)}`;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });

const inhabitant = (i: number) => ({
  id: `person-${i}`, synthetic: true, position_mm: [i, 0], display_name: `Person ${i}`, role: 'steward',
  goal: null, route: null, motion_path_mm: [[i, 0]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: 'Awaiting a supported goal.', event_ids: [] },
});
const places = (input: { seq: number; sha: string }) => ({
  input_seq: input.seq, input_sha256: input.sha, availability: 'available', unavailable_reason: null,
  walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
  clearance_mm: 450,
  targets: [{
    target_id: 'authored:v:object-1:rest', subject_id: 'authored:v:object-1', node_id: 'ground:+00000000:+00000000',
    affordance: 'rest', duration_ticks: 3, origin: 'authored', object_id: 'object-1', version_id: 'branch', enabled: true,
  }],
  unavailable_affordances: [{
    target_id: 'authored:v:object-2:rest', subject_id: 'authored:v:object-2', object_id: 'object-2',
    version_id: 'branch', affordance: 'rest', reason: 'authored_affordance_unreachable',
  }],
});
const row = (withPlaces: boolean) => ({
  society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'derived-place',
  population_size: 100, current_tick: 2, state_sha256: 'a'.repeat(64), input_seq: 2, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick: 2, input_seq: 2,
    input_sha256: 'b'.repeat(64), inhabitants: Array.from({ length: 100 }, (_, i) => inhabitant(i)) },
  ...(withPlaces ? { places: places({ seq: 2, sha: 'b'.repeat(64) }) } : {}),
});

describe('a saved world names itself on every society request', () => {
  it('reads with places, creates without a place, steps and directs, all in the named world', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(json(row(true)))
      .mockResolvedValueOnce(json(row(false)))
      .mockResolvedValueOnce(json(row(false)))
      .mockResolvedValueOnce(json({ events: [] }));
    const client = new SocietyClient({ baseUrl: 'https://api.test', token: 'test', fetch, worldId: WORLD });
    const read = await client.read('branch', { places: true });
    const created = await client.create('branch', null, 'region:starter', 'exulanica-society/v2');
    await client.advance(created);
    await client.events(created);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      `https://api.test/world/versions/branch/society?${QUERY}&places=true`,
      `https://api.test/world/versions/branch/society?${QUERY}`,
      `https://api.test/world/versions/branch/society/steps?${QUERY}`,
      `https://api.test/world/versions/branch/society/events?${QUERY}&limit=256`,
    ]);
    // The server resolves a saved world's place; the request names none.
    expect(JSON.parse(String(fetch.mock.calls[1]![1]!.body))).toEqual({
      region_id: 'region:starter', seed: '7a'.repeat(32), profile: 'exulanica-society/v2',
    });
    expect(read.places?.targets.map((target) => [target.objectId, target.affordance])).toEqual([['object-1', 'rest']]);
    expect(read.places?.unreachable.map((place) => [place.objectId, place.reason])).toEqual([
      ['object-2', 'authored_affordance_unreachable'],
    ]);
    expect(read.places?.walkableArea).toEqual({ source: 'declared', centreMm: [0, 0], halfWidthMm: 12000, halfDepthMm: 12000 });
    expect(created.places).toBeNull();
  });

  it('names the saved world on playback reads, changes and steps', async () => {
    const control = {
      profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'branch', persisted: false,
      revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
      interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
      simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
      lease_expires_at: null, last_event_seq: 0, current_tick: 2, state_sha256: 'a'.repeat(64),
      play_ineligible_reason: null, play_eligible: true,
    };
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(json(control))
      .mockResolvedValueOnce(json({ control, society: row(false) }));
    const client = new SocietyControlClient({ baseUrl: 'https://api.test', token: 'test', fetch, worldId: WORLD });
    const held = await client.read('branch');
    await client.step(held, parseSociety(row(false)));
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      `https://api.test/world/versions/branch/society/control?${QUERY}`,
      `https://api.test/world/versions/branch/society/control/steps?${QUERY}`,
    ]);
    expect(parseSocietyControl(control, 'branch').versionId).toBe('branch');
  });

  it('reads a saved world society of a few people, and still refuses a small legacy one', () => {
    const few = { ...row(false), population_size: 8,
      state: { ...row(false).state, inhabitants: row(false).state.inhabitants.slice(0, 8) } };
    expect(parseSociety(few).state.inhabitants).toHaveLength(8);
    const legacy = { ...few, state: { tick: 2, inhabitants: few.state.inhabitants.map((p) => ({
      id: p.id, synthetic: true, position_mm: p.position_mm })) } };
    expect(() => parseSociety(legacy)).toThrow(/Invalid society/);
  });

  it('refuses places that describe an input the state did not consume', () => {
    const stale = { ...row(false), places: places({ seq: 1, sha: 'c'.repeat(64) }) };
    expect(() => parseSociety(stale)).toThrow(/society places/);
    const forged = row(true);
    (forged.places!.targets[0] as Record<string, unknown>)['affordance'] = 'sleep';
    expect(() => parseSociety(forged)).toThrow(/society place/);
  });
});
