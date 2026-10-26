import { WORLD_SCENES } from './world-scenes.js';
import { orbitMaterial } from './world-materials.js';

/** Shared geometry for the optical surface and its native controls. */
export const ORBIT_PERIOD = 84;
export const ORBIT_OUTER_COUNT = 12;
export const ORBIT_INNER_COUNT = 12;
export const ORBIT_COUNT = ORBIT_OUTER_COUNT + ORBIT_INNER_COUNT;
/** The least half-width of a world's orb as a touch target: 44 pixels across. */
export const ORBIT_TOUCH_RADIUS = 22;
/** Content fills the existing slots without changing either track. */
export const WORLD_ORBIT_SLOTS: readonly number[] = Array.from({ length: Math.min(WORLD_SCENES.length, ORBIT_COUNT) }, (_, index) => index);
export interface OrbitPose { x: number; y: number; ax: number; ay: number; bx: number; by: number; material: number }

const X_TILT = 32 * Math.PI / 180, Y_TILT = 26 * Math.PI / 180;

/** A ring's radius, its orbs' size and how far it narrows across a stage too narrow for it. */
function track(ring: number, width: number, height: number) {
  const radius = Math.min(height * (ring ? .205 : .305), ring ? 218 : 324);
  const density = Math.min(1, Math.max(.7, (width - 80) / 340));
  const size = Math.min(31, Math.max(24, height * .031)) * density;
  const trackScale = Math.min(1, Math.max(1, width / 2 - 48) / (radius * .95));
  return { radius, size, trackScale };
}

/**
 * Whether a slot's orb is drawn on a stage of this size. Each ring narrows by its own measure across a narrow stage,
 * so there the two would meet at their sides; where they cannot stand one whole orb apart (two touch radii and a
 * margin), only the outer ring is drawn and no orb stands over another.
 */
export function orbitDrawn(index: number, width: number, height: number): boolean {
  if (index < ORBIT_OUTER_COUNT) return true;
  const outer = track(0, width, height), inner = track(1, width, height);
  if (outer.trackScale >= 1) return true;
  const apart = (outer.radius * outer.trackScale - inner.radius * inner.trackScale) * Math.cos(Y_TILT);
  return apart >= 2 * Math.max(ORBIT_TOUCH_RADIUS, outer.size) + 12;
}

export function orbitPose(index: number, time: number, width: number, height: number): OrbitPose {
  const ring = index < ORBIT_OUTER_COUNT ? 0 : 1;
  const phase = (ring ? (index - ORBIT_OUTER_COUNT) / ORBIT_INNER_COUNT : index / ORBIT_OUTER_COUNT) * Math.PI * 2;
  const angle = phase + time / ORBIT_PERIOD * Math.PI * 2 * (ring ? -1 : 1);
  const { radius, size, trackScale } = track(ring, width, height);
  const lens = height * 1.35;
  const project = (x: number, y: number) => {
    const a = x * Math.cos(Y_TILT), z = -x * Math.sin(Y_TILT);
    const b = y * Math.cos(X_TILT) - z * Math.sin(X_TILT);
    const depth = y * Math.sin(X_TILT) + z * Math.cos(X_TILT);
    const scale = lens / (lens - depth);
    return { x: width / 2 + a * scale * trackScale, y: height * .44 + b * scale };
  };
  const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius;
  const center = project(x, y), right = project(x + size, y), down = project(x, y + size);
  return { x: center.x, y: center.y, ax: (right.x - center.x) / trackScale, ay: right.y - center.y, bx: (down.x - center.x) / trackScale, by: down.y - center.y, material: orbitMaterial(index) };
}
