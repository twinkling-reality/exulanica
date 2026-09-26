import { describe, expect, it } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasBinding, FlightWindow } from '@exulanica/atlas-react/playcanvas';

import { FLIGHT_STATES, FlightContractError, type FlightRead } from '../src/flight-api.js';
import {
  AHEAD_MS,
  MAX_BACKOFF_MS,
  POLL_MS,
  WINDOW_STEPS,
  createSavedWorldFlight,
} from '../src/composition/saved-world-flight.js';

/**
 * The page keeps a saved world's flight drawn: the first window starts it at step 0, a window is
 * read when less than half a minute of served steps is left, each kind's parts are loaded once,
 * a changed world is drawn from its own first step, and a kind whose parts are missing is named
 * and not drawn. The renderer here is a recorder; the flock's own drawing has its own tests.
 */

function read(fromStep: number, digest = 'a'.repeat(64), available = true): FlightRead {
  const window: FlightWindow = {
    inputSha256: digest, groundMm: 0, stepMs: 100, fromStep, steps: WINDOW_STEPS,
    states: FLIGHT_STATES, flyers: [],
  };
  const part = (key: string) => ({
    assetKey: key, availability: available ? 'available' : 'missing',
    mediaType: 'model/gltf-binary', contentSha256: 'b'.repeat(64), byteSize: 10,
  });
  return {
    worldId: 'world-1', versionId: 'version-1', window, unplaced: [], lateHome: 0,
    kinds: [{
      title: 'Small bird',
      look: { key: 'small_bird', wingHingeMm: [30, 6, 66], maxBankMrad: 785, flapCycleMs: 120 },
      body: part('cc0.small-bird-body'),
      wing: part('cc0.small-bird-wing'),
    }],
  };
}

function harness(answers: (fromStep: number) => FlightRead) {
  const log: string[] = [];
  let clock = 0;
  let nextStep: number | null = null;
  let startMs = 0;
  let startStep = 0;
  const society = {
    setFlight(window: FlightWindow, nowMs: number) {
      log.push(`window ${window.fromStep} ${window.inputSha256.slice(0, 1)}`);
      if (nextStep === null) { startMs = nowMs; startStep = window.fromStep; }
      nextStep = window.fromStep + window.steps;
    },
    async setFlightKind(_app: unknown, look: { key: string }) { log.push(`kind ${look.key}`); },
    clearFlight() { log.push('clear'); nextStep = null; },
    get flightNextStep() { return nextStep; },
    flightStepAt(nowMs: number) { return nextStep === null ? null : startStep + (nowMs - startMs) / 100; },
  };
  const binding = { app: {}, authoredSociety: society, invalidate() {} } as unknown as AtlasBinding;
  const flight = createSavedWorldFlight({
    credentials: { baseUrl: 'http://api.test', token: 't' },
    worldId: 'world-1', versionId: 'version-1', regionId: 'region:starter',
    binding: () => binding,
    now: () => clock,
    client: { window: async (_version: string, fromStep: number) => { log.push(`read ${fromStep}`); return answers(fromStep); } },
    loadBytes: async () => new ArrayBuffer(10),
    setInterval: (() => 0) as unknown as typeof globalThis.setInterval,
    clearInterval: (() => undefined) as unknown as typeof globalThis.clearInterval,
  });
  return { flight, log, advance: (ms: number) => { clock += ms; } };
}

describe('createSavedWorldFlight', () => {
  it('draws the first window from step 0 once its kind is loaded, and reads ahead when due', async () => {
    const { flight, log, advance } = harness((from) => read(from));
    await flight.start();
    expect(log).toEqual(['read 0', 'kind small_bird', 'window 0 a']);
    await flight.poll();
    expect(log).toHaveLength(3);
    advance(WINDOW_STEPS * 100 - AHEAD_MS - 1);
    await flight.poll();
    expect(log).toHaveLength(3);
    advance(2);
    await flight.poll();
    expect(log.slice(3)).toEqual([`read ${WINDOW_STEPS}`, `window ${WINDOW_STEPS} a`]);
  });

  it('draws a changed world from its own first step', async () => {
    let digest = 'a'.repeat(64);
    const { flight, log, advance } = harness((from) => read(from, digest));
    await flight.start();
    digest = 'c'.repeat(64);
    advance(WINDOW_STEPS * 100);
    await flight.poll();
    expect(log.slice(3)).toEqual([`read ${WINDOW_STEPS}`, 'clear', 'read 0', 'window 0 c']);
  });

  it('names a kind whose parts are not in storage and draws none of it', async () => {
    const { flight, log } = harness((from) => read(from, 'a'.repeat(64), false));
    await flight.start();
    expect(log).toEqual(['read 0', 'window 0 a']);
    expect(flight.status.undrawnKinds).toEqual(['small_bird: cc0.small-bird-body is missing']);
  });

  it('draws an edited world from its own first step at once', async () => {
    let digest = 'a'.repeat(64);
    const { flight, log } = harness((from) => read(from, digest));
    await flight.start();
    digest = 'd'.repeat(64);
    await flight.restart();
    expect(log.slice(3)).toEqual(['clear', 'read 0', 'window 0 d']);
  });

  it('stops reading and clears the flight when the world closes', async () => {
    const { flight, log } = harness((from) => read(from));
    await flight.start();
    flight.stop();
    await flight.poll();
    expect(log).toEqual(['read 0', 'kind small_bird', 'window 0 a', 'clear']);
  });

  it('stops reading at a refusal the server will keep giving, names it, and reads again after an edit', async () => {
    let refuse = true;
    const { flight, log, advance } = harness((from) => {
      if (refuse) throw new ApiError(409, 'too_many_flyers', "a world's objects host 30 flyers");
      return read(from);
    });
    await flight.start();
    expect(log).toEqual(['read 0']);
    expect([flight.status.state, flight.status.failure]).toEqual(['refused', 'too_many_flyers']);
    expect(flight.status.refusalWords).toBe(
      "Flight stopped: this world's objects would host more flyers than one world may hold.",
    );
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    await flight.poll();
    expect(log).toEqual(['read 0']);
    refuse = false;
    await flight.restart();
    expect(log.slice(1)).toEqual(['clear', 'read 0', 'kind small_bird', 'window 0 a']);
    expect(flight.status.state).toBe('flying');
  });

  it('takes an answer this client cannot read as a refusal that lasts', async () => {
    const { flight, log, advance } = harness(() => { throw new FlightContractError('flight states are not the ones this client draws'); });
    await flight.start();
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    expect(log).toEqual(['read 0']);
    expect(flight.status.state).toBe('refused');
    expect(flight.status.refusalWords).toBe('Flight stopped: this page cannot read the flight the server sent.');
  });

  // Only a refusal the server keeps giving for the world as it stands stops the reading.
  it.each([
    [409, 'flight_world_too_large', 'Flight stopped: this world is too large to fly over.'],
    [409, 'flight_unavailable', 'Flight stopped: something in this world cannot be placed for flight.'],
    [422, 'flight_step_out_of_range',
      'Flight stopped: this page has shown a whole day of flight; open the world again to start it over.'],
    [409, 'a_code_this_page_does_not_know', 'Flight stopped: the server refused it (a_code_this_page_does_not_know).'],
  ])('stops at a %i %s and says why in words', async (status, code, words) => {
    const { flight, log, advance } = harness(() => { throw new ApiError(status, code, 'refused'); });
    await flight.start();
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    expect(log).toEqual(['read 0']);
    expect([flight.status.state, flight.status.failure, flight.status.refusalWords]).toEqual(['refused', code, words]);
  });

  // A lapsed sign-in is the page session's to renew, so it stays retrying; so do a busy server
  // and a server failure.
  it.each([
    [401, 'unauthorized'],
    [429, 'too_many_requests'],
    [500, 'internal_error'],
    [502, 'bad_gateway'],
  ])('backs off and tries again after a %i %s', async (status, code) => {
    let failures = 1;
    const { flight, log, advance } = harness((from) => {
      if (failures > 0) {
        failures -= 1;
        throw new ApiError(status, code, 'not now');
      }
      return read(from);
    });
    await flight.start();
    expect([flight.status.state, flight.status.failure, flight.status.refusalWords]).toEqual(['retrying', code, null]);
    advance(POLL_MS);
    await flight.poll();
    expect(log).toEqual(['read 0', 'read 0', 'kind small_bird', 'window 0 a']);
    expect(flight.status.state).toBe('flying');
  });

  it('tries again after a passing failure, waiting longer each time up to a bound', async () => {
    let failures = 3;
    const { flight, log, advance } = harness((from) => {
      if (failures > 0) {
        failures -= 1;
        throw new ApiError(503, 'unavailable', 'the server is busy');
      }
      return read(from);
    });
    await flight.start();
    expect(flight.status.state).toBe('retrying');
    await flight.poll();
    expect(log).toEqual(['read 0']);
    advance(POLL_MS);
    await flight.poll();
    expect(log).toEqual(['read 0', 'read 0']);
    advance(2 * POLL_MS - 1);
    await flight.poll();
    expect(log).toHaveLength(2);
    advance(1);
    await flight.poll();
    advance(4 * POLL_MS);
    await flight.poll();
    expect(log.slice(-3)).toEqual(['read 0', 'kind small_bird', 'window 0 a']);
    expect(flight.status.state).toBe('flying');
  });

  it('aborts a read in flight when stopped', async () => {
    let signal: AbortSignal | undefined;
    const stalled = (async (_url: unknown, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    }) as unknown as typeof globalThis.fetch;
    const society = {
      get flightNextStep() { return null; },
      flightStepAt() { return null; },
      clearFlight() {},
    };
    const flight = createSavedWorldFlight({
      credentials: { baseUrl: 'http://api.test', token: 't', fetch: stalled } as never,
      worldId: 'world-1', versionId: 'version-1', regionId: 'region:starter',
      binding: () => ({ app: {}, authoredSociety: society, invalidate() {} }) as unknown as AtlasBinding,
      now: () => 0,
      setInterval: (() => 0) as unknown as typeof globalThis.setInterval,
      clearInterval: (() => undefined) as unknown as typeof globalThis.clearInterval,
    });
    void flight.start();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(signal?.aborted).toBe(false);
    flight.stop();
    expect(signal?.aborted).toBe(true);
  });
});
