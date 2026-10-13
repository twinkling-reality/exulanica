import { WORLD_SCENES } from './world-scenes.js';
import { orbitMaterial } from './world-materials.js';

/** Shared geometry for the optical surface and its native controls. */
export const ORBIT_PERIOD = 84;
export const ORBIT_OUTER_COUNT = 12;
export const ORBIT_INNER_COUNT = 12;
export const ORBIT_COUNT = ORBIT_OUTER_COUNT + ORBIT_INNER_COUNT;
/** Content fills the existing slots without changing either track. */
export const WORLD_ORBIT_SLOTS: readonly number[] = Array.from({ length: Math.min(WORLD_SCENES.length, ORBIT_COUNT) }, (_, index) => index);
export interface OrbitPose { x: number; y: number; ax: number; ay: number; bx: number; by: number; material: number }

export function orbitPose(index: number, time: number, width: number, height: number): OrbitPose {
  const ring = index < ORBIT_OUTER_COUNT ? 0 : 1;
  const phase = (ring ? (index - ORBIT_OUTER_COUNT) / ORBIT_INNER_COUNT : index / ORBIT_OUTER_COUNT) * Math.PI * 2;
  const angle = phase + time / ORBIT_PERIOD * Math.PI * 2 * (ring ? -1 : 1);
  const radius = Math.min(height * (ring ? .205 : .305), ring ? 218 : 324);
  const density = Math.min(1, Math.max(.7, (width - 80) / 340));
  const size = Math.min(31, Math.max(24, height * .031)) * density;
  const lens = height * 1.35;
  const xTilt = 32 * Math.PI / 180, yTilt = 26 * Math.PI / 180;
  const trackScale = Math.min(1, Math.max(1, width / 2 - 48) / (radius * .95));
  const project = (x: number, y: number) => {
    const a = x * Math.cos(yTilt), z = -x * Math.sin(yTilt);
    const b = y * Math.cos(xTilt) - z * Math.sin(xTilt);
    const depth = y * Math.sin(xTilt) + z * Math.cos(xTilt);
    const scale = lens / (lens - depth);
    return { x: width / 2 + a * scale * trackScale, y: height * .44 + b * scale };
  };
  const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius;
  const center = project(x, y), right = project(x + size, y), down = project(x, y + size);
  return { x: center.x, y: center.y, ax: (right.x - center.x) / trackScale, ay: right.y - center.y, bx: (down.x - center.x) / trackScale, by: down.y - center.y, material: orbitMaterial(index) };
}
