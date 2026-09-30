import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  ROADS_MODULE,
  TRAFFIC_WINDOW_PROFILE,
  TrafficClient,
  TrafficContractError,
  VEHICLE_MODES,
  WorldTrafficClient,
  parseTrafficRead,
} from '../src/traffic-api.js';

/**
 * A generated city's traffic, read strictly.
 *
 * The profile, the module and the mode order this client draws are the server's own, read from the
 * movement module table and the traffic host here, so a change on either side fails rather than
 * drifting.
 */

const REPOSITORY = new URL('../../../../', import.meta.url);
const TABLE = JSON.parse(
  readFileSync(new URL('exulanica/movement/movement-modules.v1.json', REPOSITORY), 'utf8'),
) as { modules: { module: string; output: { profile: string } }[] };
const EPISODES_SOURCE = readFileSync(new URL('exulanica/world/traffic_episodes.py', REPOSITORY), 'utf8');

function vehicle(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    vehicle_id: 'v1',
    vehicle_class: 'passenger_car',
    body_family: 'sedan',
    colour: 'red',
    dimensions_mm: { length: 5790, width: 2130, height: 1300, wheelbase: 3350, front_overhang: 910, rear_overhang: 1530 },
    front_axle_mm: [0, 0, 1000, 0],
    rear_axle_mm: [-3350, 0, -2350, 0],
    mode: [2, 2],
    speed_mm_per_s: [1000, 1000],
    slot: [-1, -1],
    motion_path_mm: [[], [910, 0, 1910, 0]],
    ...overrides,
  };
}

function answer(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    profile: TRAFFIC_WINDOW_PROFILE,
    module: ROADS_MODULE,
    input_sha256: 'a'.repeat(64),
    network_sha256: 'b'.repeat(64),
    catalog_sha256: 'c'.repeat(64),
    step_ms: 1000,
    episode_steps: 1200,
    from_second: 100,
    seconds: 2,
    modes: [...VEHICLE_MODES],
    crossings_fed: false,
    vehicles: [vehicle()],
    late_home: [],
    episodes: [],
    clock_second: 101,
    world_seed: 'd'.repeat(64),
    version_id: 'e'.repeat(64),
    ...overrides,
  };
}

describe('the traffic answer', () => {
  it('names the profile and module the movement table states, and the modes in the host order', () => {
    const roads = TABLE.modules.find((row) => row.module === ROADS_MODULE);
    expect(roads?.output.profile).toBe(TRAFFIC_WINDOW_PROFILE);
    expect(EPISODES_SOURCE).toContain(`MODES: Final = ("${VEHICLE_MODES.join('", "')}")`);
  });

  it('is read into a window of every vehicle, second by second', () => {
    const read = parseTrafficRead(answer());
    expect(read.window.vehicles[0]!.frontAxleMm).toEqual([0, 0, 1000, 0]);
    expect(read.window.vehicles[0]!.motionPathMm).toEqual([[], [910, 0, 1910, 0]]);
    expect(read.window.crossingsFed).toBe(false);
    expect(read.window.clockSecond).toBe(101);
  });

  it('is refused by name when a field does not hold for every second', () => {
    const cases: Record<string, unknown>[] = [
      { profile: 'exulanica.traffic-window/v0' },
      { module: 'exulanica-movement/flight/v1' },
      { modes: ['parked', 'driving'] },
      { crossings_fed: true },
      { vehicles: [vehicle({ front_axle_mm: [0, 0] })] },
      { vehicles: [vehicle({ mode: [2, 9] })] },
      { vehicles: [vehicle({ motion_path_mm: [[], [1, 2, 3]] })] },
      { vehicles: [vehicle({ speed_mm_per_s: [1000, 0.5] })] },
    ];
    for (const overrides of cases) {
      expect(() => parseTrafficRead(answer(overrides)), JSON.stringify(overrides)).toThrow(TrafficContractError);
    }
  });

  it('asks for the city and second it was given, and refuses an answer for another', async () => {
    let asked = '';
    const fetch = (async (url: string) => {
      asked = url;
      return new Response(JSON.stringify(answer()), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as unknown as typeof globalThis.fetch;
    const client = new TrafficClient({ baseUrl: 'https://example.invalid/api', token: 't', fetch });
    await client.window('d'.repeat(64), 100, 2);
    expect(asked).toContain('/tiles/traffic?');
    expect(asked).toContain(`world_seed=${'d'.repeat(64)}`);
    expect(asked).toContain('from_second=100');
    await expect(client.window('d'.repeat(64), 150, 2)).rejects.toThrow(TrafficContractError);
  });

  it('reads a saved world\'s traffic through its world and version, and refuses an answer for another', async () => {
    let asked = '';
    const world = { world_id: 'world:generated:town', version_id: 'version-1', roads_version: 'e'.repeat(64) };
    const fetch = (async (url: string) => {
      asked = url;
      return new Response(JSON.stringify({ ...answer(), ...world }), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as unknown as typeof globalThis.fetch;
    const client = new WorldTrafficClient({ baseUrl: 'https://example.invalid/api', token: 't', fetch });
    const read = await client.window('world:generated:town', 'version-1', 100, 2);
    expect(read.roadsVersion).toBe('e'.repeat(64));
    expect([read.worldId, read.versionId]).toEqual(['world:generated:town', 'version-1']);
    expect(asked).toContain('/world/versions/version-1/traffic?');
    expect(asked).toContain('world_id=world%3Agenerated%3Atown');
    await expect(client.window('world:generated:town', 'version-2', 100, 2)).rejects.toThrow(TrafficContractError);
    await expect(client.window('world:generated:other', 'version-1', 100, 2)).rejects.toThrow(TrafficContractError);
  });
});
