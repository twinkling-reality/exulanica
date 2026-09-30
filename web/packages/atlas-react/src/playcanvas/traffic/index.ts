/**
 * @exulanica/atlas-react/traffic
 *
 * The renderer of a world's traffic: vehicles drawn from the seconds the traffic route serves. A
 * separate entry, as the generated tile's is: the app reaches it from a page that draws generated
 * streets, and a build that never imports it carries none of it.
 */

export type {
  PedestrianIndication,
  SignalGroupSamples,
  SignalSamples,
  TrafficWindow,
  VehicleDimensions,
  VehicleIndication,
  VehicleLate,
  VehicleMode,
  VehicleSamples,
} from './types.js';
export { SIGNAL_LOOKS_V1, SignalLights, SignalLookError } from './signal-lights.js';
export type { GroundAt, ToRenderer } from './types.js';
export { TrafficLayer, VEHICLE_LOOKS, VehicleLookError, pointAlong, poseBetween } from './traffic-layer.js';
