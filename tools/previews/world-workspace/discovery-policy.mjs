/** Presentation defaults, separate from the authority and physical reach of any action. */
export const DISCOVERY = Object.freeze({
  leastExtentPx: 2, // Below two pixels the rendered subject cannot be located reliably.
  // Inspect reach runs from the camera to the nearest point of a being's box (an object's middle).
  inspectEnterMetres: 6, // Prototype exploration radius, not an engine's physical-action permission.
  inspectLeaveMetres: 7, // Hysteresis keeps a prompt stable at the boundary.
  clickChooseMetres: 30, // A click chooses anyone seen this near (F3): a pointer reaches past the reticle's reach.
  lookStayMs: 500, // The look tag stays this long after the aim leaves its subject (F4), and E still chooses them.
});

/** Whether a click on a subject this far away chooses it (F3): anyone seen within the click's reach. */
export function clickReach(distance) {
  return Number.isFinite(distance) && distance >= 0 && distance <= DISCOVERY.clickChooseMetres;
}

export function inspectionReach(distance, wasReachable = false) {
  return Number.isFinite(distance) && distance >= 0 && distance <= (wasReachable ? DISCOVERY.inspectLeaveMetres : DISCOVERY.inspectEnterMetres);
}
