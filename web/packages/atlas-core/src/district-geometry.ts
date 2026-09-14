import type { OwnedDistrict } from './owned-district.js';

export type DistrictPoint = readonly [number, number];
type Ring = readonly DistrictPoint[];
const sq = (v: bigint): bigint => v * v;
const delta = (a: number, b: number): bigint => BigInt(a) - BigInt(b);
const cross = (a: DistrictPoint, b: DistrictPoint, c: DistrictPoint): bigint =>
  delta(b[0], a[0]) * delta(c[1], a[1]) - delta(b[1], a[1]) * delta(c[0], a[0]);

function inside(p: DistrictPoint, ring: Ring): boolean {
  let hit = false;
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1]!; const b = ring[i]!;
    if ((a[1] > p[1]) !== (b[1] > p[1])) {
      const lhs = delta(p[0], a[0]) * delta(b[1], a[1]);
      const rhs = delta(b[0], a[0]) * delta(p[1], a[1]);
      if (b[1] > a[1] ? lhs < rhs : lhs > rhs) hit = !hit;
    }
  }
  return hit;
}
function near(p: DistrictPoint, a: DistrictPoint, b: DistrictPoint, radius: number): boolean {
  const dx = delta(b[0], a[0]); const dz = delta(b[1], a[1]);
  const den = sq(dx) + sq(dz); const dot = delta(p[0], a[0]) * dx + delta(p[1], a[1]) * dz;
  const r2 = sq(BigInt(radius));
  if (dot <= 0n) return sq(delta(p[0], a[0])) + sq(delta(p[1], a[1])) <= r2;
  if (dot >= den) return sq(delta(p[0], b[0])) + sq(delta(p[1], b[1])) <= r2;
  return sq(delta(p[0], a[0]) * dz - delta(p[1], a[1]) * dx) <= r2 * den;
}
function intersects(a: DistrictPoint, b: DistrictPoint, c: DistrictPoint, d: DistrictPoint, r: number): boolean {
  if (Math.max(a[0], b[0]) + r < Math.min(c[0], d[0]) || Math.max(c[0], d[0]) + r < Math.min(a[0], b[0]) ||
      Math.max(a[1], b[1]) + r < Math.min(c[1], d[1]) || Math.max(c[1], d[1]) + r < Math.min(a[1], b[1])) return false;
  return (cross(a, b, c) * cross(a, b, d) <= 0n && cross(c, d, a) * cross(c, d, b) <= 0n) ||
    near(a, c, d, r) || near(b, c, d, r) || near(c, a, b, r) || near(d, a, b, r);
}
const touches = (a: DistrictPoint, b: DistrictPoint, ring: Ring, r: number): boolean =>
  ring.slice(1).some((d, i) => intersects(a, b, ring[i]!, d, r));

/** Integer-exact whole-segment clearance; holes in sidewalks excluded, building exteriors solid. */
export function districtSegmentSupported(district: OwnedDistrict, a: DistrictPoint, b: DistrictPoint, radius = 450): boolean {
  if (![...a, ...b, radius].every(Number.isSafeInteger) || radius < 450) return false;
  const [w, n, e, s] = district.bounds_cm.map(v => v * 10) as [number, number, number, number];
  if ([a, b].some(p => p[0] <= w + radius || p[0] >= e - radius || p[1] <= n + radius || p[1] >= s - radius)) return false;
  const loX = Math.min(a[0], b[0]) - radius; const loZ = Math.min(a[1], b[1]) - radius;
  const hiX = Math.max(a[0], b[0]) + radius; const hiZ = Math.max(a[1], b[1]) + radius;
  const mm = (ring: Ring): Ring => ring.map(([x, z]) => [x * 10, z * 10]);
  for (const building of district.buildings) {
    const box = building.bbox_cm.map(v => v * 10);
    if (box[2]! < loX || box[0]! > hiX || box[3]! < loZ || box[1]! > hiZ) continue;
    for (const polygon of building.polygons) {
      const ring = mm(polygon[0]!);
      if (inside(a, ring) || inside(b, ring) || touches(a, b, ring, radius)) return false;
    }
  }
  return district.sidewalks.some(sidewalk => {
    const box = sidewalk.bbox_cm.map(v => v * 10);
    return box[0]! <= loX && box[1]! <= loZ && box[2]! >= hiX && box[3]! >= hiZ && sidewalk.polygons.some(p => {
      const polygon = p.map(mm);
      return inside(a, polygon[0]!) && inside(b, polygon[0]!) &&
        !polygon.slice(1).some(r => inside(a, r) || inside(b, r)) &&
        !polygon.some(r => touches(a, b, r, radius));
    });
  });
}
