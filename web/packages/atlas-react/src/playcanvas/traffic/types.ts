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

/** What a vehicle group or a pedestrian group of a signal can show, in the order its codes index. */
export type VehicleIndication = 'green' | 'amber' | 'red';
export type PedestrianIndication = 'walk' | 'clearance' | 'dont_walk';

/** One group of a signal: where its heads stand, and what it shows each second of the window. */
export interface SignalGroupSamples {
  readonly group: string;
  readonly kind: 'vehicle' | 'pedestrian';
  /** Plan points in the road records' frame: stop lines for a vehicle group, crosswalk ends for a
   * pedestrian group, two entries a point. */
  readonly pointsMm: readonly number[];
  /** One code a second, indexing the window's vehicle or pedestrian indications. */
  readonly codes: readonly number[];
}

/** A signal the traffic runs at a junction (`exulanica.traffic-signal-presentation/v1`). */
export interface SignalSamples {
  readonly signalId: string;
  readonly junctionId: string;
  readonly groups: readonly SignalGroupSamples[];
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
  readonly vehicleIndications: readonly VehicleIndication[];
  readonly pedestrianIndications: readonly PedestrianIndication[];
  /** Every signal of the world's roads, each group's code every second of the window. */
  readonly signals: readonly SignalSamples[];
}

/** Where the drawn world's ground is at a plan point, in renderer metres, or null for none. */
export type GroundAt = (xMm: number, yMm: number) => number | null;
/** A plan point in the road records' frame, in the renderer's frame (x east, y up, z south). */
export type ToRenderer = (xMm: number, yMm: number, zMm: number) => readonly [number, number, number];
