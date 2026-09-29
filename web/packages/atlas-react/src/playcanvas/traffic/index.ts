/**
 * @exulanica/atlas-react/traffic
 *
 * The renderer of a world's traffic: vehicles drawn from the seconds the traffic route serves. A
 * separate entry, as the generated tile's is: the app reaches it from a page that draws generated
 * streets, and a build that never imports it carries none of it.
 */

export type { TrafficWindow, VehicleDimensions, VehicleLate, VehicleMode, VehicleSamples } from './types.js';
export type { GroundAt, ToRenderer } from './traffic-layer.js';
export { TrafficLayer, VEHICLE_LOOKS, VehicleLookError, pointAlong, poseBetween } from './traffic-layer.js';
