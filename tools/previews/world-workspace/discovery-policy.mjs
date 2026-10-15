/** Presentation defaults, separate from the authority and physical reach of any action. */
export const DISCOVERY = Object.freeze({
  leastExtentPx: 2, // Below two pixels the rendered subject cannot be located reliably.
  // Inspect reach runs from the camera to the nearest point of a being's box (an object's middle).
  inspectEnterMetres: 6, // Prototype exploration radius, not an engine's physical-action permission.
  inspectLeaveMetres: 7, // Hysteresis keeps a prompt stable at the boundary.
});

export function inspectionReach(distance, wasReachable = false) {
  return Number.isFinite(distance) && distance >= 0 && distance <= (wasReachable ? DISCOVERY.inspectLeaveMetres : DISCOVERY.inspectEnterMetres);
}
