import { readFileSync } from 'node:fs';

import { describe, expect, it, vi } from 'vitest';

import {
  FLIGHT_MODULE,
  FLIGHT_STATES,
  FLIGHT_WINDOW_PROFILE,
  FlightClient,
  FlightContractError,
  parseFlightRead,
} from '../src/flight-api.js';

/**
 * A saved world's flight, read strictly.
 *
 * The profile, the module and the state order this client draws are the server's own, read from
 * the movement module table and the flight module here, so a change on either side fails rather
 * than drifting.
 */

const REPOSITORY = new URL('../../../../', import.meta.url);
const TABLE = JSON.parse(
  readFileSync(new URL('exulanica/movement/movement-modules.v1.json', REPOSITORY), 'utf8'),
) as { modules: { module: string; output: { profile: string } }[] };
const FLIGHT_SOURCE = readFileSync(new URL('exulanica/movement/flight.py', REPOSITORY), 'utf8');

function answer(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    profile: FLIGHT_WINDOW_PROFILE,
    module: FLIGHT_MODULE,
    input_sha256: 'a'.repeat(64),
    ground_mm: 0,
    step_ms: 100,
    episode_steps: 3000,
    from_step: 0,
    clock_step: 1,
    steps: 2,
    states: [...FLIGHT_STATES],
    flyers: [{
      flyer_id: 'bird-1',
      kind: 'small_bird',
      position_mm: [0, 5650, -4000, 0, 5650, -4000],
      velocity_mm_s: [0, 0, 0, 0, 0, 0],
      turn_mm_s2: [0, 0],
      state: [0, 0],
      flap: [0, 0],
      held: [0, 0],
    }],
    late_home: [],
    world_id: 'world-1',
    version_id: 'version-1',
    kinds: [{
      key: 'small_bird',
      title: 'Small bird',
      body: {
        asset_key: 'cc0.small-bird-body',
        media_type: 'model/gltf-binary',
        content_sha256: 'b'.repeat(64),
        byte_size: 99496,
        availability: 'available',
      },
      wing: { asset_key: 'cc0.small-bird-wing', availability: 'unregistered' },
      wing_hinge_mm: [30, 6, 66],
      max_bank_mrad: 785,
      flap_cycle_ms: 120,
    }],
    unplaced: [{ object_id: 'tree-2', kind: 'small_bird', count: 3, reason: 'home_perch_unusable' }],
    ...overrides,
  };
}

describe('flight parity with the server', () => {
  it('draws the window profile and module the movement module table states', () => {
    const flight = TABLE.modules.find((row) => row.module === FLIGHT_MODULE);
    expect(flight?.output.profile).toBe(FLIGHT_WINDOW_PROFILE);
  });

  it('reads state codes in the order the flight module states them', () => {
    const stated = /^STATES: Final = \(([^)]*)\)/m.exec(FLIGHT_SOURCE)?.[1];
    expect(stated?.split(',').map((item) => item.trim().replaceAll('"', '')).filter(Boolean))
      .toEqual([...FLIGHT_STATES]);
  });
});

describe('parseFlightRead', () => {
  it('reads a window, its kinds and what could not be placed', () => {
    const read = parseFlightRead(answer());
    expect(read.window.flyers[0]?.positionMm).toEqual([0, 5650, -4000, 0, 5650, -4000]);
    expect(read.window.states).toEqual(FLIGHT_STATES);
    expect(read.kinds[0]?.look).toEqual({
      key: 'small_bird', wingHingeMm: [30, 6, 66], maxBankMrad: 785, flapCycleMs: 120,
    });
    expect(read.kinds[0]?.wing).toEqual({
      assetKey: 'cc0.small-bird-wing', availability: 'unregistered',
      mediaType: null, contentSha256: null, byteSize: null,
    });
    expect(read.unplaced).toEqual([
      { objectId: 'tree-2', kind: 'small_bird', count: 3, reason: 'home_perch_unusable' },
    ]);
    expect(read.window.clockStep).toBe(1);
  });

  it('reads the flyers the server names late, and refuses one named outside the window', () => {
    const late = parseFlightRead(answer({ late_home: [{ step: 1, flyer_id: 'bird-1' }] }));
    expect(late.window.lateHome).toEqual([{ step: 1, flyerId: 'bird-1' }]);
    expect(late.lateHome).toBe(1);
    expect(() => parseFlightRead(answer({ late_home: [{ step: 2, flyer_id: 'bird-1' }] })))
      .toThrow('outside its window');
  });

  it.each([
    ['a profile it does not know', { profile: 'exulanica.flight-window/v2' }, 'flight profile'],
    ['a module it does not draw', { module: 'exulanica-movement/roads/v1' }, 'movement module'],
    ['states in another order', { states: ['flying', 'perching', 'taking_off', 'landing'] }, 'flight states'],
    ['a step count its samples do not fill', { steps: 3 }, 'flyer states'],
    ['no reading of the shared clock', { clock_step: null }, 'clock step'],
  ])('refuses %s by name', (_what, overrides, message) => {
    expect(() => parseFlightRead(answer(overrides))).toThrow(FlightContractError);
    expect(() => parseFlightRead(answer(overrides))).toThrow(message);
  });

  it('refuses a fractional position and a state code that names no state', () => {
    const fractional = answer();
    (fractional['flyers'] as Record<string, unknown>[])[0]!['position_mm'] = [0, 5650.5, 0, 0, 0, 0];
    expect(() => parseFlightRead(fractional)).toThrow('flyer positions');
    const unknown = answer();
    (unknown['flyers'] as Record<string, unknown>[])[0]!['state'] = [0, 4];
    expect(() => parseFlightRead(unknown)).toThrow('names no state');
  });
});

describe('FlightClient', () => {
  it('asks for the named window in the open world, and refuses an answer for another', async () => {
    const asked: string[] = [];
    const fetch = async (input: RequestInfo | URL) => {
      asked.push(String(input));
      return new Response(JSON.stringify(answer()), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    const client = new FlightClient({ baseUrl: 'http://api.test', token: 't', worldId: 'world-1', fetch });
    await client.window('version-1', 0, 2);
    const url = new URL(asked[0]!);
    expect(url.pathname).toBe('/world/versions/version-1/flight');
    expect(Object.fromEntries(url.searchParams)).toEqual({ world_id: 'world-1', from_step: '0', steps: '2' });
    await expect(client.window('version-2', 0, 2)).rejects.toThrow('another version or step');
    // A read that names no step asks the server for the window at its clock.
    await client.window('version-1', null, 2);
    expect(Object.fromEntries(new URL(asked[2]!).searchParams)).toEqual({ world_id: 'world-1', steps: '2' });
  });

  it('stops listening to the client\'s signal when each read settles', async () => {
    const fetch = async () => new Response(JSON.stringify(answer()), { status: 200, headers: { 'content-type': 'application/json' } });
    const everything = new AbortController();
    const added = vi.spyOn(everything.signal, 'addEventListener');
    const removed = vi.spyOn(everything.signal, 'removeEventListener');
    const client = new FlightClient({ baseUrl: 'http://api.test', token: 't', worldId: 'world-1', fetch, signal: everything.signal });
    await client.window('version-1', 0, 2, new AbortController().signal);
    await expect(client.window('version-2', 0, 2, new AbortController().signal)).rejects.toThrow('another version');
    expect(added).toHaveBeenCalledTimes(2);
    expect(removed.mock.calls.map((call) => call[1])).toEqual(added.mock.calls.map((call) => call[1]));
  });

  it('aborts a read in flight by its own signal, and every read in flight by the client\'s', async () => {
    const seen: AbortSignal[] = [];
    // A fetch that answers only when its signal aborts, as a read still in flight.
    const fetch = (_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      const signal = init!.signal!;
      seen.push(signal);
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
    const everything = new AbortController();
    const client = new FlightClient({
      baseUrl: 'http://api.test', token: 't', worldId: 'world-1', fetch, signal: everything.signal,
    });
    const one = new AbortController();
    const first = client.window('version-1', 0, 2, one.signal);
    const second = client.window('version-1', 0, 2, new AbortController().signal);
    await Promise.resolve();
    one.abort();
    await expect(first).rejects.toBeDefined();
    expect([seen[0]?.aborted, seen[1]?.aborted]).toEqual([true, false]);
    everything.abort();
    await expect(second).rejects.toBeDefined();
    expect(seen[1]?.aborted).toBe(true);
  });
});
