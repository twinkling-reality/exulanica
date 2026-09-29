/**
 * What the traffic route hands a renderer: a window of seconds of a world's traffic.
 *
 * The server computes every second with the traffic simulation (`exulanica/traffic`); a page draws
 * what it is handed. Each vehicle's seconds are its presentation frames
 * (`exulanica.traffic-vehicle-presentation/v1`), flattened: integer plan points in the road records'
 * frame (millimetres, x east, y north), two entries a second for a point.
 */

/** A vehicle's mode, in the order the route's mode codes index. */
export type VehicleMode = 'parked' | 'leaving' | 'driving' | 'arriving';

/** The dimensions a vehicle's class states, in millimetres. */
export interface VehicleDimensions {
  readonly length: number;
  readonly width: number;
  readonly height: number;
  readonly wheelbase: number;
  readonly frontOverhang: number;
  readonly rearOverhang: number;
}

/** One vehicle's seconds in a window. */
export interface VehicleSamples {
  readonly vehicleId: string;
  readonly vehicleClass: string;
  readonly bodyFamily: string;
  readonly colour: string;
  readonly dimensionsMm: VehicleDimensions;
  /** Two entries a second: the front axle's plan point. */
  readonly frontAxleMm: readonly number[];
  readonly rearAxleMm: readonly number[];
  readonly mode: readonly number[];
  readonly speedMmPerS: readonly number[];
  /**
   * For each second, every point the vehicle's front passed during the second that ended there,
   * flattened, first and last included; empty when it did not move.
   */
  readonly motionPathMm: readonly (readonly number[])[];
}

/** A vehicle the server found not parked at home at an episode's last second. */
export interface VehicleLate {
  readonly second: number;
  readonly vehicleId: string;
}

/** A window of consecutive seconds of one world's traffic, as the route serves it. */
export interface TrafficWindow {
  /** The digest of everything the traffic was computed from; a new one is a new traffic. */
  readonly inputSha256: string;
  /** Where the shared clock was when the server answered: second n is the nth since the epoch. */
  readonly clockSecond: number;
  readonly stepMs: number;
  readonly fromSecond: number;
  readonly seconds: number;
  readonly modes: readonly VehicleMode[];
  /** Whether a walker's crossings reached the traffic: the route states it, and states false. */
  readonly crossingsFed: boolean;
  readonly vehicles: readonly VehicleSamples[];
  readonly lateHome: readonly VehicleLate[];
}
