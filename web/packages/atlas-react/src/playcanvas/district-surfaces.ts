import type { OwnedDistrictBuilding } from '@exulanica/atlas-core';

type Point = readonly [number, number];
type Polygon = OwnedDistrictBuilding['polygons'][number];

/** Renderer-only scan conversion. Split at every vertex height so concavities and holes
 * become disjoint trapezoids, without a centre fan spilling outside the source footprint. */
export function surfaceTriangles(
  polygon: Polygon,
): readonly (readonly [Point, Point, Point])[] {
  const levels = [
    ...new Set(polygon.flatMap((ring) => ring.map((point) => point[1]))),
  ].sort((a, b) => a - b);
  const edges = polygon.flatMap((ring) =>
    ring.slice(1).map((b, i) => [ring[i]!, b] as const),
  );
  const triangles: [Point, Point, Point][] = [];
  for (let i = 1; i < levels.length; i++) {
    const low = levels[i - 1]!,
      high = levels[i]!,
      middle = (low + high) / 2;
    const crossing = edges.filter(
      ([a, b]) =>
        Math.min(a[1], b[1]) < middle && Math.max(a[1], b[1]) > middle,
    );
    const xAt = ([a, b]: readonly [Point, Point], z: number) =>
      a[0] + ((b[0] - a[0]) * (z - a[1])) / (b[1] - a[1]);
    crossing.sort((a, b) => xAt(a, middle) - xAt(b, middle));
    for (let j = 1; j < crossing.length; j += 2) {
      const left = crossing[j - 1]!,
        right = crossing[j]!;
      const a: Point = [xAt(left, low), low],
        b: Point = [xAt(left, high), high];
      const c: Point = [xAt(right, high), high],
        d: Point = [xAt(right, low), low];
      triangles.push([a, b, c], [a, c, d]);
    }
  }
  return triangles;
}

export function ringArea(ring: readonly Point[]): number {
  return (
    ring
      .slice(1)
      .reduce((sum, b, i) => sum + ring[i]![0] * b[1] - b[0] * ring[i]![1], 0) /
    2
  );
}

export function pointInRing(point: Point, ring: readonly Point[]): boolean {
  let value = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]!,
      b = ring[j]!;
    if (
      a[1] > point[1] !== b[1] > point[1] &&
      point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
    )
      value = !value;
  }
  return value;
}

/** Ray against source extrusion, including concave walls and courtyard walls. Metres in/out. */
export function buildingRayDistance(
  building: OwnedDistrictBuilding,
  origin: readonly number[],
  direction: readonly number[],
): number | null {
  const height = building.height_cm / 100;
  let nearest = Infinity;
  for (const polygon of building.polygons) {
    for (const ring of polygon)
      for (let i = 1; i < ring.length; i++) {
        const a = ring[i - 1]!,
          b = ring[i]!;
        const ax = a[0] / 100,
          az = a[1] / 100;
        const ex = (b[0] - a[0]) / 100,
          ez = (b[1] - a[1]) / 100;
        const det = direction[0]! * ez - direction[2]! * ex;
        if (Math.abs(det) < 1e-10) continue;
        const dx = ax - origin[0]!,
          dz = az - origin[2]!;
        const t = (dx * ez - dz * ex) / det;
        const u = (dx * direction[2]! - dz * direction[0]!) / det;
        const y = origin[1]! + t * direction[1]!;
        if (t >= 0 && u >= 0 && u <= 1 && y >= 0 && y <= height)
          nearest = Math.min(nearest, t);
      }
    if (Math.abs(direction[1]!) > 1e-10) {
      const t = (height - origin[1]!) / direction[1]!;
      const p: Point = [
        (origin[0]! + t * direction[0]!) * 100,
        (origin[2]! + t * direction[2]!) * 100,
      ];
      if (
        t >= 0 &&
        polygon[0] &&
        pointInRing(p, polygon[0]) &&
        !polygon.slice(1).some((ring) => pointInRing(p, ring))
      )
        nearest = Math.min(nearest, t);
    }
  }
  return Number.isFinite(nearest) ? nearest : null;
}
