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
  flightUnplacedWords,
} from '../src/composition/saved-world-flight.js';

/**
 * The page keeps a saved world's flight drawn on the flight's shared clock: the first read names
 * no step and the server answers from its clock, a window is read when less than half a minute of
 * served steps is left, each kind's parts are loaded once, a changed world is drawn from the clock,
 * an edit aborts a read in flight and draws nothing of the old flight, and a kind whose parts are
 * missing is named and not drawn. The renderer here is a recorder; the flock's own drawing has its
 * own tests.
 */

/** The server clock's step when a test starts: 2026-09-26 18:00 UTC, in 100 ms steps. */
const C = 17_904_456_000;

function read(fromStep: number, digest = 'a'.repeat(64), available = true, clockStep = fromStep): FlightRead {
  const window: FlightWindow = {
    inputSha256: digest, clockStep, groundMm: 0, stepMs: 100, fromStep, steps: WINDOW_STEPS,
    states: FLIGHT_STATES, flyers: [], lateHome: [],
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

type Answer = (
  fromStep: number,
  signal: AbortSignal | undefined,
  serverStep: number,
) => FlightRead | Promise<FlightRead>;

function harness(answers: Answer) {
  const log: string[] = [];
  /** The page's own clock, which a sleep stops, and the server's, which it does not. */
  let clock = 0;
  let serverMs = 0;
  let nextStep: number | null = null;
  let startMs = 0;
  let startStep = 0;
  const society = {
    setFlight(window: FlightWindow, nowMs: number) {
      log.push(`window ${window.fromStep} ${window.inputSha256.slice(0, 1)}`);
      // As the flock does: the first window starts the clock, a later one re-sets a drifted one.
      const at = nextStep === null ? null : startStep + (nowMs - startMs) / 100;
      if (at === null || Math.abs(at - window.clockStep) > 2) { startMs = nowMs; startStep = window.clockStep; }
      nextStep = Math.max(nextStep ?? 0, window.fromStep + window.steps);
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
    client: {
      window: async (_version: string, fromStep: number | null, _steps: number, signal?: AbortSignal) => {
        log.push(`read ${fromStep ?? 'now'}`);
        // A read that names no step starts at the server's clock, which a step too far from is
        // refused, as the route refuses it.
        const serverStep = C + Math.floor(serverMs / 100);
        if (fromStep !== null && Math.abs(fromStep - serverStep) > 3_000) {
          throw new ApiError(422, 'flight_step_out_of_range', 'too far from the clock');
        }
        return answers(fromStep ?? serverStep, signal, serverStep);
      },
    },
    loadBytes: async () => new ArrayBuffer(10),
    setInterval: (() => 0) as unknown as typeof globalThis.setInterval,
    clearInterval: (() => undefined) as unknown as typeof globalThis.clearInterval,
  });
  return {
    flight,
    log,
    advance: (ms: number) => { clock += ms; serverMs += ms; },
    /** A sleep: the page's clock stops, the server's goes on. */
    sleep: (ms: number) => { serverMs += ms; },
  };
}

describe('createSavedWorldFlight', () => {
  it('draws the first window from the clock once its kind is loaded, and reads ahead when due', async () => {
    const { flight, log, advance } = harness((from) => read(from));
    await flight.start();
    expect(log).toEqual(['read now', 'kind small_bird', `window ${C} a`]);
    await flight.poll();
    expect(log).toHaveLength(3);
    advance(WINDOW_STEPS * 100 - AHEAD_MS - 1);
    await flight.poll();
    expect(log).toHaveLength(3);
    advance(2);
    await flight.poll();
    expect(log.slice(3)).toEqual([`read ${C + WINDOW_STEPS}`, `window ${C + WINDOW_STEPS} a`]);
  });

  it('after a long sleep, reads again from the clock the read-ahead the server refused, and flies on', async () => {
    const { flight, log, advance, sleep } = harness((from, _signal, serverStep) => read(from, 'a'.repeat(64), true, serverStep));
    await flight.start();
    // Ten minutes asleep: the page's clock stopped, the server's did not.
    sleep(10 * 60_000);
    advance(WINDOW_STEPS * 100 - AHEAD_MS + 1);
    await flight.poll();
    const now = C + 6_000 + Math.floor((WINDOW_STEPS * 100 - AHEAD_MS + 1) / 100);
    expect(log.slice(3)).toEqual([`read ${C + WINDOW_STEPS}`, 'read now', `window ${now} a`]);
    expect(flight.status.state).toBe('flying');
  });

  it('after a short sleep, re-sets its clock from the served one and catches up with every other page', async () => {
    const { flight, log, advance, sleep } = harness((from, _signal, serverStep) => read(from, 'a'.repeat(64), true, serverStep));
    await flight.start();
    sleep(2 * 60_000);
    advance(WINDOW_STEPS * 100 - AHEAD_MS + 1);
    await flight.poll();
    // The read-ahead is within the clock's reach and served; its clock says the page is behind.
    expect(log.slice(3)).toEqual([`read ${C + WINDOW_STEPS}`, `window ${C + WINDOW_STEPS} a`]);
    await flight.poll();
    const now = C + 1_200 + Math.floor((WINDOW_STEPS * 100 - AHEAD_MS + 1) / 100);
    expect(log.slice(5)).toEqual(['read now', `window ${now} a`]);
  });

  it('reads from the clock when the clock has passed the served steps, as in a background page', async () => {
    const { flight, log, advance } = harness((from) => read(from));
    await flight.start();
    advance(5 * WINDOW_STEPS * 100);
    await flight.poll();
    expect(log.slice(3)).toEqual(['read now', `window ${C + 5 * WINDOW_STEPS} a`]);
  });

  it('draws a changed world from the clock', async () => {
    let digest = 'a'.repeat(64);
    const { flight, log, advance } = harness((from) => read(from, digest));
    await flight.start();
    digest = 'c'.repeat(64);
    advance(WINDOW_STEPS * 100);
    await flight.poll();
    expect(log.slice(3)).toEqual([`read ${C + WINDOW_STEPS}`, 'clear', 'read now', `window ${C + WINDOW_STEPS} c`]);
  });

  it('names a kind whose parts are not in storage and draws none of it', async () => {
    const { flight, log } = harness((from) => read(from, 'a'.repeat(64), false));
    await flight.start();
    expect(log).toEqual(['read now', `window ${C} a`]);
    expect(flight.status.undrawnKinds).toEqual(['small_bird: cc0.small-bird-body is missing']);
  });

  it('says in words which flyers have no home, with the kind title the server served', async () => {
    const titled = (from: number): FlightRead => {
      const answer = read(from);
      return {
        ...answer,
        kinds: [{ ...answer.kinds[0]!, title: 'Served title' }],
        unplaced: [{ objectId: 'tree-2', kind: 'small_bird', count: 3, reason: 'home_perch_unusable' }],
      };
    };
    const { flight } = harness((from) => titled(from));
    expect(flight.status.unplacedWords).toBeNull();
    await flight.start();
    expect(flight.status.unplacedWords).toBe(
      'Served title: 3 cannot live here; the object meant to host them has too few usable perches.',
    );
  });

  it('draws an edited world from the clock at once', async () => {
    let digest = 'a'.repeat(64);
    const { flight, log } = harness((from) => read(from, digest));
    await flight.start();
    digest = 'd'.repeat(64);
    await flight.restart();
    expect(log.slice(3)).toEqual(['clear', 'read now', `window ${C} d`]);
  });

  it('aborts a read in flight at an edit, draws nothing of it, and draws the edited world at once', async () => {
    let digest = 'a'.repeat(64);
    let held: { from: number; signal: AbortSignal | undefined; release: () => void } | null = null;
    const { flight, log, advance } = harness((from, signal) => {
      if (from === C + WINDOW_STEPS) {
        // The read ahead, begun before the edit: it answers only when released.
        return new Promise<FlightRead>((resolve) => {
          held = { from, signal, release: () => resolve(read(from, 'a'.repeat(64))) };
        });
      }
      return read(from, digest);
    });
    await flight.start();
    const dueMs = WINDOW_STEPS * 100 - AHEAD_MS + 1;
    advance(dueMs);
    const ahead = flight.poll();
    await Promise.resolve();
    expect(held).not.toBeNull();
    digest = 'd'.repeat(64);
    await flight.restart();
    expect(held!.signal?.aborted).toBe(true);
    // The edited world is read and drawn without waiting for the old read or the next poll.
    const edited = `window ${C + Math.floor(dueMs / 100)} d`;
    expect(log.slice(3)).toEqual([`read ${C + WINDOW_STEPS}`, 'clear', 'read now', edited]);
    held!.release();
    await ahead;
    // The old answer arrives after the edit and is never drawn.
    expect(log.slice(7)).toEqual([]);
    expect(flight.status.state).toBe('flying');
  });

  it('stops reading and clears the flight when the world closes', async () => {
    const { flight, log } = harness((from) => read(from));
    await flight.start();
    flight.stop();
    await flight.poll();
    expect(log).toEqual(['read now', 'kind small_bird', `window ${C} a`, 'clear']);
  });

  it('stops reading at a refusal the server will keep giving, names it, and reads again after an edit', async () => {
    let refuse = true;
    const { flight, log, advance } = harness((from) => {
      if (refuse) throw new ApiError(409, 'too_many_flyers', "a world's objects host 30 flyers");
      return read(from);
    });
    await flight.start();
    expect(log).toEqual(['read now']);
    expect([flight.status.state, flight.status.failure]).toEqual(['refused', 'too_many_flyers']);
    expect(flight.status.refusalWords).toBe(
      "Flight stopped: this world's objects would host more flyers than one world may hold.",
    );
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    await flight.poll();
    expect(log).toEqual(['read now']);
    refuse = false;
    await flight.restart();
    expect(log.slice(1)).toEqual(['clear', 'read now', 'kind small_bird', `window ${C + 100 * MAX_BACKOFF_MS / 1000} a`]);
    expect(flight.status.state).toBe('flying');
  });

  it('takes an answer this client cannot read as a refusal that lasts', async () => {
    const { flight, log, advance } = harness(() => { throw new FlightContractError('flight states are not the ones this client draws'); });
    await flight.start();
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    expect(log).toEqual(['read now']);
    expect(flight.status.state).toBe('refused');
    expect(flight.status.refusalWords).toBe('Flight stopped: this page cannot read the flight the server sent.');
  });

  // Only a refusal the server keeps giving for the world as it stands stops the reading.
  it.each([
    [409, 'flight_world_too_large', 'Flight stopped: this world is too large to fly over.'],
    [409, 'flight_unavailable', 'Flight stopped: something in this world cannot be placed for flight.'],
    [409, 'home_perch_unusable', "Flight stopped: a flyer's home in this world is not a perch it can use."],
    [422, 'flight_step_out_of_range',
      'Flight stopped: this page asked for flight too far from the present moment; open the world again.'],
    [409, 'a_code_this_page_does_not_know', 'Flight stopped: the server refused it (a_code_this_page_does_not_know).'],
  ])('stops at a %i %s and says why in words', async (status, code, words) => {
    const { flight, log, advance } = harness(() => { throw new ApiError(status, code, 'refused'); });
    await flight.start();
    advance(10 * MAX_BACKOFF_MS);
    await flight.poll();
    expect(log).toEqual(['read now']);
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
    expect(log).toEqual(['read now', 'read now', 'kind small_bird', `window ${C + POLL_MS / 100} a`]);
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
    expect(log).toEqual(['read now']);
    advance(POLL_MS);
    await flight.poll();
    expect(log).toEqual(['read now', 'read now']);
    advance(2 * POLL_MS - 1);
    await flight.poll();
    expect(log).toHaveLength(2);
    advance(1);
    await flight.poll();
    advance(4 * POLL_MS);
    await flight.poll();
    expect(log.slice(-3)).toEqual(['read now', 'kind small_bird', `window ${C + 7 * POLL_MS / 100} a`]);
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

describe('flightUnplacedWords', () => {
  const titles = new Map([['small_bird', 'Small bird'], ['owl', 'Tawny owl']]);
  const row = (objectId: string, count: number, kind = 'small_bird', reason = 'home_perch_unusable') =>
    ({ objectId, kind, count, reason });

  it('says nothing when every flyer has a home', () => {
    expect(flightUnplacedWords([], titles)).toBeNull();
  });

  it('names the served kind title, the count and why, for one flyer and for several', () => {
    expect(flightUnplacedWords([row('tree-1', 3)], titles)).toBe(
      'Small bird: 3 cannot live here; the object meant to host them has too few usable perches.',
    );
    expect(flightUnplacedWords([row('tree-1', 1)], titles)).toBe(
      'Small bird: 1 cannot live here; the object meant to host it has too few usable perches.',
    );
  });

  it('counts the objects and the flyers of one kind and reason together', () => {
    expect(flightUnplacedWords([row('tree-1', 3), row('lamp-4', 2)], titles)).toBe(
      'Small bird: 5 cannot live here; the 2 objects meant to host them have too few usable perches.',
    );
  });

  it('names no kind of object, whatever the objects are called', () => {
    // The flight serves the flyers' kind, not the objects': a tree is never assumed.
    expect(flightUnplacedWords([row('tree-1', 3)], titles)).not.toMatch(/tree/iu);
  });

  it('says each kind in the order of its key, and shows a key or a code it has no words for', () => {
    expect(flightUnplacedWords([
      row('tree-1', 3),
      row('tree-1', 1, 'owl'),
      row('tower-2', 2, 'swift'),
      row('tree-3', 4, 'small_bird', 'a_reason_this_page_does_not_know'),
    ], titles)).toBe([
      'Tawny owl: 1 cannot live here; the object meant to host it has too few usable perches.',
      'Small bird: 4 cannot live here (a_reason_this_page_does_not_know).',
      'Small bird: 3 cannot live here; the object meant to host them has too few usable perches.',
      'swift: 2 cannot live here; the object meant to host them has too few usable perches.',
    ].join(' '));
  });
});
