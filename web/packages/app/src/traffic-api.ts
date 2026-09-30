/**
 * A generated world's traffic, read: a saved world's own (`GET /world/versions/{version_id}/traffic
 * ?world_id=<world>`, `WorldTrafficClient`), or a baked city's on the development preview
 * (`GET /tiles/traffic?world_seed=<seed>`, `TrafficClient`).
 *
 * The server drives the city's stored roads with the traffic simulation (`exulanica/traffic`) and
 * computes each window of seconds; nothing here computes a second. The traffic keeps shared real
 * time: a read that names no first second starts at the server's clock, and every answer says where
 * that clock was (`clock_second`). Every answer is read strictly: a profile, a module or a mode this
 * client does not know is refused by name rather than drawn as something else, every sample is a
 * whole number, and every vehicle states each field for every second of the window.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { TrafficWindow, VehicleMode, VehicleSamples } from '@exulanica/atlas-react/traffic';

/** The window profile and the movement module this client draws. */
export const TRAFFIC_WINDOW_PROFILE = 'exulanica.traffic-window/v1';
export const ROADS_MODULE = 'exulanica-movement/roads/v1';
export const VEHICLE_MODES: readonly VehicleMode[] = Object.freeze(['parked', 'leaving', 'driving', 'arriving']);

export class TrafficContractError extends Error {}

export interface TrafficRead {
  readonly worldSeed: string;
  readonly versionId: string;
  readonly window: TrafficWindow;
}

/** A saved world's traffic: the world and version asked for, and the version of its roads. */
export interface WorldTrafficRead {
  readonly worldId: string;
  readonly versionId: string;
  /** The digest of the receipt the world's records come from, which every version shares. */
  readonly roadsVersion: string;
  readonly window: TrafficWindow;
}

type Json = Record<string, unknown>;

function object(value: unknown, where: string): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TrafficContractError(`${where} is an object`);
  }
  return value as Json;
}

function whole(value: unknown, where: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new TrafficContractError(`${where} is a whole number`);
  return value;
}

function text(value: unknown, where: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TrafficContractError(`${where} is text`);
  return value;
}

function wholes(value: unknown, where: string, count: number): number[] {
  if (!Array.isArray(value) || value.length !== count) {
    throw new TrafficContractError(`${where} holds ${count} whole numbers`);
  }
  return value.map((item, index) => whole(item, `${where}[${index}]`));
}

function vehicle(value: unknown, seconds: number, modes: number, where: string): VehicleSamples {
  const row = object(value, where);
  const dimensions = object(row['dimensions_mm'], `${where}.dimensions_mm`);
  const mode = wholes(row['mode'], `${where}.mode`, seconds);
  if (mode.some((code) => code < 0 || code >= modes)) throw new TrafficContractError(`${where}.mode names no mode`);
  const paths = row['motion_path_mm'];
  if (!Array.isArray(paths) || paths.length !== seconds) {
    throw new TrafficContractError(`${where}.motion_path_mm holds a path for every second`);
  }
  return {
    vehicleId: text(row['vehicle_id'], `${where}.vehicle_id`),
    vehicleClass: text(row['vehicle_class'], `${where}.vehicle_class`),
    bodyFamily: text(row['body_family'], `${where}.body_family`),
    colour: text(row['colour'], `${where}.colour`),
    dimensionsMm: {
      length: whole(dimensions['length'], `${where}.dimensions_mm.length`),
      width: whole(dimensions['width'], `${where}.dimensions_mm.width`),
      height: whole(dimensions['height'], `${where}.dimensions_mm.height`),
      wheelbase: whole(dimensions['wheelbase'], `${where}.dimensions_mm.wheelbase`),
      frontOverhang: whole(dimensions['front_overhang'], `${where}.dimensions_mm.front_overhang`),
      rearOverhang: whole(dimensions['rear_overhang'], `${where}.dimensions_mm.rear_overhang`),
    },
    frontAxleMm: wholes(row['front_axle_mm'], `${where}.front_axle_mm`, 2 * seconds),
    rearAxleMm: wholes(row['rear_axle_mm'], `${where}.rear_axle_mm`, 2 * seconds),
    mode,
    speedMmPerS: wholes(row['speed_mm_per_s'], `${where}.speed_mm_per_s`, seconds),
    motionPathMm: paths.map((path, index) => {
      if (!Array.isArray(path) || path.length % 2 !== 0) {
        throw new TrafficContractError(`${where}.motion_path_mm[${index}] is plan points`);
      }
      return wholes(path, `${where}.motion_path_mm[${index}]`, path.length);
    }),
  };
}

/** A route's answer, read strictly, or a `TrafficContractError` naming what does not hold. */
export function parseTrafficRead(value: unknown): TrafficRead {
  const body = object(value, 'the traffic');
  const window = parseWindow(body);
  return {
    worldSeed: text(body['world_seed'], 'world_seed'),
    versionId: text(body['version_id'], 'version_id'),
    window,
  };
}

/** A saved world's answer, read strictly, or a `TrafficContractError` naming what does not hold. */
export function parseWorldTrafficRead(value: unknown): WorldTrafficRead {
  const body = object(value, 'the traffic');
  const window = parseWindow(body);
  return {
    worldId: text(body['world_id'], 'world_id'),
    versionId: text(body['version_id'], 'version_id'),
    roadsVersion: text(body['roads_version'], 'roads_version'),
    window,
  };
}

function parseWindow(body: Json): TrafficWindow {
  if (body['profile'] !== TRAFFIC_WINDOW_PROFILE) throw new TrafficContractError(`the traffic is not ${TRAFFIC_WINDOW_PROFILE}`);
  if (body['module'] !== ROADS_MODULE) throw new TrafficContractError(`the traffic is not ${ROADS_MODULE}'s`);
  const modes = body['modes'];
  if (!Array.isArray(modes) || modes.length !== VEHICLE_MODES.length || modes.some((mode, index) => mode !== VEHICLE_MODES[index])) {
    throw new TrafficContractError(`the traffic's modes are not ${VEHICLE_MODES.join(', ')}`);
  }
  if (body['crossings_fed'] !== false) throw new TrafficContractError('the traffic states whether crossings are fed, and they are not');
  const seconds = whole(body['seconds'], 'seconds');
  const vehicles = body['vehicles'];
  const late = body['late_home'];
  if (!Array.isArray(vehicles) || !Array.isArray(late)) throw new TrafficContractError('the traffic lists vehicles and late ones');
  return {
    inputSha256: text(body['input_sha256'], 'input_sha256'),
    clockSecond: whole(body['clock_second'], 'clock_second'),
    stepMs: whole(body['step_ms'], 'step_ms'),
    fromSecond: whole(body['from_second'], 'from_second'),
    seconds,
    modes: VEHICLE_MODES,
    crossingsFed: false,
    vehicles: vehicles.map((row, index) => vehicle(row, seconds, VEHICLE_MODES.length, `vehicles[${index}]`)),
    lateHome: late.map((row, index) => {
      const item = object(row, `late_home[${index}]`);
      return {
        second: whole(item['second'], `late_home[${index}].second`),
        vehicleId: text(item['vehicle_id'], `late_home[${index}].vehicle_id`),
      };
    }),
  };
}

/** Reads windows of a generated city's traffic. */
export class TrafficClient {
  constructor(private readonly options: TransportOptions) {}

  /** The window of `seconds` seconds from `fromSecond`, or from the server's clock when null. */
  async window(worldSeed: string, fromSecond: number | null, seconds: number, signal?: AbortSignal): Promise<TrafficRead> {
    const transport = new Transport(signal === undefined ? this.options : { ...this.options, signal });
    const query: Record<string, string> = { world_seed: worldSeed, seconds: String(seconds) };
    if (fromSecond !== null) query['from_second'] = String(fromSecond);
    const read = parseTrafficRead(await transport.getJson<unknown>('/tiles/traffic', query));
    if (read.worldSeed !== worldSeed || (fromSecond !== null && read.window.fromSecond !== fromSecond)) {
      throw new TrafficContractError('the traffic answered for another city or second');
    }
    return read;
  }
}

/** Reads windows of a saved world's traffic, through the world and version it belongs to. */
export class WorldTrafficClient {
  constructor(private readonly options: TransportOptions) {}

  /** The window of `seconds` seconds from `fromSecond`, or from the server's clock when null. */
  async window(
    worldId: string,
    versionId: string,
    fromSecond: number | null,
    seconds: number,
    signal?: AbortSignal,
  ): Promise<WorldTrafficRead> {
    const transport = new Transport(signal === undefined ? this.options : { ...this.options, signal });
    const query: Record<string, string> = { world_id: worldId, seconds: String(seconds) };
    if (fromSecond !== null) query['from_second'] = String(fromSecond);
    const read = parseWorldTrafficRead(await transport.getJson<unknown>(
      `/world/versions/${encodeURIComponent(versionId)}/traffic`, query,
    ));
    if (read.worldId !== worldId || read.versionId !== versionId
      || (fromSecond !== null && read.window.fromSecond !== fromSecond)) {
      throw new TrafficContractError('the traffic answered for another world, version or second');
    }
    return read;
  }
}
