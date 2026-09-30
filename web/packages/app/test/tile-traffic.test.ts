// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  AHEAD_MS,
  POLL_MS,
  TILE_TRAFFIC_ATTRIBUTE,
  WINDOW_SECONDS,
  startTileTraffic,
  withTileTraffic,
  type TileTrafficState,
} from '../src/composition/tile-traffic.js';
import type { TrafficRead } from '../src/traffic-api.js';

/**
 * A world's traffic, kept drawn: windows read ahead of the shared clock and handed to the layer,
 * refusals stated. Driven with a fake reader and a fake clock.
 */

/** A host with the parts the traffic reads: an update event and a root the layer adds itself to. */
function host(listeners = new Set<() => void>()) {
  return {
    app: { on: (_: string, callback: () => void) => listeners.add(callback), off: (_: string, callback: () => void) => listeners.delete(callback) },
    environmentRoot: { addChild: () => undefined },
    camera: null,
  } as never;
}

const tile = { navigationWorld: { surface: { sample: () => null } } } as never;

function read(fromSecond: number, clockSecond: number): TrafficRead {
  const seconds = WINDOW_SECONDS;
  return {
    worldSeed: 'd'.repeat(64),
    versionId: 'v',
    window: {
      inputSha256: 'a'.repeat(64),
      clockSecond,
      stepMs: 1000,
      fromSecond,
      seconds,
      modes: ['parked', 'leaving', 'driving', 'arriving'],
      crossingsFed: false,
      lateHome: [],
      vehicles: [{
        vehicleId: 'v1', vehicleClass: 'passenger_car', bodyFamily: 'sedan', colour: 'red',
        dimensionsMm: { length: 5790, width: 2130, height: 1300, wheelbase: 3350, frontOverhang: 910, rearOverhang: 1530 },
        frontAxleMm: Array.from({ length: seconds }, () => [0, 0]).flat(),
        rearAxleMm: Array.from({ length: seconds }, () => [-3350, 0]).flat(),
        mode: Array.from({ length: seconds }, () => 0),
        speedMmPerS: Array.from({ length: seconds }, () => 0),
        motionPathMm: Array.from({ length: seconds }, () => []),
      }],
    },
  };
}

/**
 * How long a wait may take: the layer is imported on first use, and a cold transform of PlayCanvas
 * after a source change takes longer than `vi.waitFor`'s one second. A test holds up to three.
 */
const EVENTUALLY = { timeout: 10_000 } as const;

async function settle(): Promise<void> {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('the tile traffic', { timeout: 3 * EVENTUALLY.timeout }, () => {
  it('reads from the clock first, then from where the served seconds end once fewer than half a minute are left', async () => {
    let nowMs = 0;
    const asked: (number | null)[] = [];
    const states: TileTrafficState[] = [];
    let timer: (() => void) | null = null;
    const traffic = startTileTraffic(host(), tile, {
      reader: {
        window: async (from: number | null) => {
          asked.push(from);
          return read(from ?? 1000, 1000);
        },
      },
      now: () => nowMs,
      setTimer: (callback) => { timer = callback; return 1; },
      clearTimer: () => { timer = null; },
      report: (state) => states.push(state),
    });
    await vi.waitFor(() => expect(asked).toEqual([null]), EVENTUALLY);
    await vi.waitFor(() => expect(states.at(-1)).toMatchObject({ state: 'driving', vehicles: 1, crossingsFed: false }), EVENTUALLY);
    // Twenty seconds on, forty are still served: nothing is due.
    nowMs = 20_000;
    timer!();
    await settle();
    expect(asked).toEqual([null]);
    // Thirty-five seconds on, twenty-five are left, under half a minute: the next window is read.
    nowMs = WINDOW_SECONDS * 1000 - AHEAD_MS + 5_000;
    timer!();
    await vi.waitFor(() => expect(asked).toEqual([null, 1000 + WINDOW_SECONDS]), EVENTUALLY);
    traffic.stop();
    expect(timer).toBeNull();
    expect(POLL_MS).toBeLessThan(AHEAD_MS);
  });

  it('reads again from the clock when its second is too far from it, and stops on a refusal it will keep', async () => {
    let nowMs = 0;
    const asked: (number | null)[] = [];
    const states: TileTrafficState[] = [];
    let timer: (() => void) | null = null;
    let calls = 0;
    startTileTraffic(host(), tile, {
      reader: {
        window: async (from: number | null) => {
          asked.push(from);
          calls += 1;
          if (calls === 2) throw new ApiError(422, 'traffic_second_out_of_range', 'too far');
          if (calls === 4) throw new ApiError(409, 'roads_unavailable', 'no class drives it');
          return read(from ?? 5000, 5000);
        },
      },
      now: () => nowMs,
      setTimer: (callback) => { timer = callback; return 1; },
      clearTimer: () => undefined,
      report: (state) => states.push(state),
    });
    await vi.waitFor(() => expect(asked).toEqual([null]), EVENTUALLY);
    await settle();
    nowMs = 45_000;
    timer!();
    await vi.waitFor(() => expect(asked).toEqual([null, 5060, null]), EVENTUALLY);
    nowMs = 90_000;
    timer!();
    await vi.waitFor(() => expect(states.at(-1)).toMatchObject({ state: 'refused', reason: 'roads_unavailable' }), EVENTUALLY);
    nowMs = 200_000;
    timer!();
    await settle();
    expect(asked).toHaveLength(4);
  });

  it('keeps the flags of the tile it wraps, and stops reading and drawing when the tile goes', async () => {
    const listeners = new Set<() => void>();
    let reads = 0;
    const fetch = (async () => {
      reads += 1;
      const second = 1000;
      const body = {
        profile: 'exulanica.traffic-window/v1', module: 'exulanica-movement/roads/v1',
        input_sha256: 'a'.repeat(64), network_sha256: 'b'.repeat(64), catalog_sha256: 'c'.repeat(64),
        step_ms: 1000, episode_steps: 1200, from_second: second, seconds: 1,
        modes: ['parked', 'leaving', 'driving', 'arriving'], crossings_fed: false, late_home: [], episodes: [],
        clock_second: second, world_seed: 'd'.repeat(64), version_id: 'e'.repeat(64), vehicles: [],
      };
      return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as unknown as typeof globalThis.fetch;
    let tileDisposed = false;
    let tileAnimating = false;
    const shell = document.createElement('div');
    const wrapped = withTileTraffic(
      {
        navigationWorld: { surface: { sample: () => null } },
        attach: () => ({ metrics: {} as never, get animating() { return tileAnimating; }, dispose: () => { tileDisposed = true; } }),
      } as never,
      { baseUrl: 'https://example.invalid/api', token: 't', fetch },
      'd'.repeat(64),
      { shell } as never,
    );
    const attachment = wrapped.attach(host(listeners));
    await vi.waitFor(() => expect(JSON.parse(shell.getAttribute(TILE_TRAFFIC_ATTRIBUTE) ?? '{}')).toMatchObject({ state: 'driving', crossingsFed: false }), EVENTUALLY);
    expect(listeners.size).toBe(1);
    expect(attachment.animating).toBe(false);
    tileAnimating = true;
    expect(attachment.animating).toBe(true);
    attachment.dispose();
    expect(tileDisposed).toBe(true);
    expect(listeners.size).toBe(0);
    expect(reads).toBe(1);
  });
});
