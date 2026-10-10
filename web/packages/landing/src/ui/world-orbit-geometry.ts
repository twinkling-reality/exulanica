/** Shared geometry for the optical surface and its native controls. */
export const ORBIT_PERIOD = 84;
export const ORBIT_COUNT = 24;
export interface OrbitPose { x: number; y: number; ax: number; ay: number; bx: number; by: number; material: number }
const materials = [0, 3, 1, 2, 4, 0, 1, 3, 2, 4, 1, 0];

export function orbitPose(index: number, time: number, width: number, height: number): OrbitPose {
  const ring = Math.floor(index / 12);
  const phase = index % 12 / 12 * Math.PI * 2;
  const angle = phase + time / ORBIT_PERIOD * Math.PI * 2 * (ring ? -1 : 1);
  const radius = Math.min(height * (ring ? .205 : .305), ring ? 218 : 324);
  const size = Math.min(31, Math.max(24, height * .031));
  const lens = height * 1.35;
  const xTilt = 32 * Math.PI / 180, yTilt = 26 * Math.PI / 180;
  const project = (x: number, y: number) => {
    const a = x * Math.cos(yTilt), z = -x * Math.sin(yTilt);
    const b = y * Math.cos(xTilt) - z * Math.sin(xTilt);
    const depth = y * Math.sin(xTilt) + z * Math.cos(xTilt);
    const scale = lens / (lens - depth);
    return { x: width / 2 + a * scale, y: height * .44 + b * scale };
  };
  const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius;
  const center = project(x, y), right = project(x + size, y), down = project(x, y + size);
  return { x: center.x, y: center.y, ax: right.x - center.x, ay: right.y - center.y, bx: down.x - center.x, by: down.y - center.y, material: index === 7 ? 3 : index === 14 ? 4 : materials[index % 12]! };
}
