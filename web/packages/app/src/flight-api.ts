/**
 * A saved world's flight, read: `GET /world/versions/{version_id}/flight`.
 *
 * The server composes the flight from the world version and computes each window of steps with the
 * flight movement module (`exulanica/movement/flight.py`); nothing here computes a step. Every
 * answer is read strictly: a profile, a module or a state this client does not know is refused by
 * name rather than drawn as something else, and every sample is a whole number.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { FlightKindLook, FlightSamples, FlightState, FlightWindow } from '@exulanica/atlas-react/playcanvas';
import { openWorldPath } from './world-scope.js';

/** The window profile and the movement module this client draws. */
export const FLIGHT_WINDOW_PROFILE = 'exulanica.flight-window/v1';
export const FLIGHT_MODULE = 'exulanica-movement/flight/v1';
/** The states the module's window names, in the order its state codes index them. */
export const FLIGHT_STATES: readonly FlightState[] = Object.freeze([
  'perching',
  'taking_off',
  'flying',
  'landing',
]);

/** One of a flying kind's reviewed parts, as its registry row names it. */
export interface FlightKindAsset {
  readonly assetKey: string;
  /** `available` when its bytes are in storage; anything else is shown, never drawn. */
  readonly availability: string;
  readonly mediaType: string | null;
  readonly contentSha256: string | null;
  readonly byteSize: number | null;
}

export interface FlightKindRead {
  readonly title: string;
  readonly look: FlightKindLook;
  readonly body: FlightKindAsset;
  readonly wing: FlightKindAsset;
}

/** Flyers a world's objects host that the flight could not place, and why. */
export interface FlightUnplaced {
  readonly objectId: string;
  readonly kind: string;
  readonly count: number;
  readonly reason: string;
}

export interface FlightRead {
  readonly worldId: string;
  readonly versionId: string;
  readonly window: FlightWindow;
  readonly kinds: readonly FlightKindRead[];
  readonly unplaced: readonly FlightUnplaced[];
  /** Flyers not home when an episode in this window ended, each a finding the server named. */
  readonly lateHome: number;
}

export class FlightContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FlightContractError';
  }
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new FlightContractError(`${label} is not an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new FlightContractError(`${label} is not text`);
  return value;
}

function whole(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new FlightContractError(`${label} is not a whole number`);
  }
  return value;
}

function wholes(value: unknown, count: number, label: string): readonly number[] {
  if (!Array.isArray(value) || value.length !== count) {
    throw new FlightContractError(`${label} is not ${count} whole numbers`);
  }
  for (const item of value) whole(item, label);
  return Object.freeze(value as number[]);
}

function asset(value: unknown, label: string): FlightKindAsset {
  const row = record(value, label);
  const availability = text(row['availability'], `${label} availability`);
  const present = availability !== 'unregistered';
  return Object.freeze({
    assetKey: text(row['asset_key'], `${label} key`),
    availability,
    mediaType: present ? text(row['media_type'], `${label} media type`) : null,
    contentSha256: present ? text(row['content_sha256'], `${label} digest`) : null,
    byteSize: present ? whole(row['byte_size'], `${label} size`) : null,
  });
}

function hinge(value: unknown): readonly [number, number, number] {
  const [x, y, z] = wholes(value, 3, 'wing hinge');
  return Object.freeze([x!, y!, z!] as const);
}

/** A flight answer, read strictly, or a `FlightContractError` naming what does not match. */
export function parseFlightRead(value: unknown): FlightRead {
  const row = record(value, 'flight');
  if (row['profile'] !== FLIGHT_WINDOW_PROFILE) {
    throw new FlightContractError(`flight profile ${String(row['profile'])} is not ${FLIGHT_WINDOW_PROFILE}`);
  }
  if (row['module'] !== FLIGHT_MODULE) {
    throw new FlightContractError(`movement module ${String(row['module'])} is not one this client draws`);
  }
  const states = row['states'];
  if (!Array.isArray(states) || states.join() !== FLIGHT_STATES.join()) {
    throw new FlightContractError('flight states are not the ones this client draws');
  }
  const steps = whole(row['steps'], 'steps');
  const flyersValue = row['flyers'];
  if (!Array.isArray(flyersValue)) throw new FlightContractError('flyers is not a list');
  const flyers: FlightSamples[] = flyersValue.map((item) => {
    const flyer = record(item, 'flyer');
    const state = wholes(flyer['state'], steps, 'flyer states');
    if (state.some((code) => code < 0 || code >= FLIGHT_STATES.length)) {
      throw new FlightContractError('a flyer state code names no state');
    }
    return Object.freeze({
      flyerId: text(flyer['flyer_id'], 'flyer id'),
      kind: text(flyer['kind'], 'flyer kind'),
      positionMm: wholes(flyer['position_mm'], 3 * steps, 'flyer positions'),
      velocityMmS: wholes(flyer['velocity_mm_s'], 3 * steps, 'flyer velocities'),
      turnMmS2: wholes(flyer['turn_mm_s2'], steps, 'flyer turning'),
      state,
      flap: wholes(flyer['flap'], steps, 'flyer wingbeats'),
    });
  });
  const kindsValue = row['kinds'];
  if (!Array.isArray(kindsValue)) throw new FlightContractError('kinds is not a list');
  const kinds = kindsValue.map((item) => {
    const kind = record(item, 'flight kind');
    return Object.freeze({
      title: text(kind['title'], 'flight kind title'),
      look: Object.freeze({
        key: text(kind['key'], 'flight kind key'),
        wingHingeMm: hinge(kind['wing_hinge_mm']),
        maxBankMrad: whole(kind['max_bank_mrad'], 'flight kind bank'),
        flapCycleMs: whole(kind['flap_cycle_ms'], 'flight kind wingbeat'),
      }),
      body: asset(kind['body'], 'flight kind body'),
      wing: asset(kind['wing'], 'flight kind wing'),
    });
  });
  const unplacedValue = row['unplaced'];
  const lateValue = row['late_home'];
  if (!Array.isArray(unplacedValue) || !Array.isArray(lateValue)) {
    throw new FlightContractError('unplaced or late_home is not a list');
  }
  return Object.freeze({
    worldId: text(row['world_id'], 'world id'),
    versionId: text(row['version_id'], 'version id'),
    window: Object.freeze({
      inputSha256: text(row['input_sha256'], 'flight input digest'),
      groundMm: whole(row['ground_mm'], 'ground'),
      stepMs: whole(row['step_ms'], 'step'),
      fromStep: whole(row['from_step'], 'first step'),
      steps,
      states: FLIGHT_STATES,
      flyers: Object.freeze(flyers),
    }),
    kinds: Object.freeze(kinds),
    unplaced: Object.freeze(unplacedValue.map((item) => {
      const unplaced = record(item, 'unplaced flyers');
      return Object.freeze({
        objectId: text(unplaced['object_id'], 'unplaced object'),
        kind: text(unplaced['kind'], 'unplaced kind'),
        count: whole(unplaced['count'], 'unplaced count'),
        reason: text(unplaced['reason'], 'unplaced reason'),
      });
    })),
    lateHome: lateValue.length,
  });
}

export interface FlightClientOptions extends TransportOptions {
  /** The open world, or null where none is open, as in the preview. */
  readonly worldId: string | null;
}

/** Reads windows of a saved world version's flight. */
export class FlightClient {
  private readonly transport: Transport;
  private readonly worldId: string | null;

  constructor(options: FlightClientOptions) {
    this.transport = new Transport(options);
    this.worldId = options.worldId;
  }

  async window(versionId: string, fromStep: number, steps: number): Promise<FlightRead> {
    const path = openWorldPath(
      `/world/versions/${encodeURIComponent(versionId)}/flight`,
      this.worldId,
      'flight to read',
    );
    const read = parseFlightRead(
      await this.transport.getJson<unknown>(path, { from_step: String(fromStep), steps: String(steps) }),
    );
    if (read.versionId !== versionId || read.window.fromStep !== fromStep) {
      throw new FlightContractError('the flight answered for another version or step');
    }
    return read;
  }
}
