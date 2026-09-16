/**
 * Exact geometric predicates the gate decides with. Plain numbers in, plain numbers out.
 *
 * The planar predicates reproduce the product's own collision code in
 * `web/packages/atlas-core/src/navigation.ts` (even-odd ring containment, clamped segment
 * distance), so a gate that says a capsule touches a ring agrees with the rule that stops a
 * player. The spatial ones are the standard closest-point constructions and carry no tolerance of
 * their own; every tolerance is a named threshold in `keys.ts`.
 */

export type Vec3 = readonly [number, number, number];
export type Point2 = readonly [number, number];

const EPSILON = 1e-12;

/** Even-odd containment, exactly as the product's `pointInRing`. */
export function pointInRing(x: number, z: number, ring: readonly Point2[]): boolean {
  let inside = false;
  for (let index = 0, prior = ring.length - 1; index < ring.length; prior = index++) {
    const a = ring[index]!;
    const b = ring[prior]!;
    if (
      (a[1] > z) !== (b[1] > z) &&
      x < ((b[0] - a[0]) * (z - a[1])) / (b[1] - a[1]) + a[0]
    ) inside = !inside;
  }
  return inside;
}

/** Planar distance from a point to a segment, clamped to the segment. */
export function pointSegmentDistance2(
  px: number, pz: number, ax: number, az: number, bx: number, bz: number,
): number {
  const dx = bx - ax;
  const dz = bz - az;
  const length2 = dx * dx + dz * dz;
  const t = length2 < EPSILON ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / length2));
  return Math.hypot(px - (ax + t * dx), pz - (az + t * dz));
}

/** The smallest planar distance from a point to any edge of a closed ring. */
export function ringEdgeDistance(x: number, z: number, ring: readonly Point2[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (let index = 1; index < ring.length; index += 1) {
    const a = ring[index - 1]!;
    const b = ring[index]!;
    const value = pointSegmentDistance2(x, z, a[0], a[1], b[0], b[1]);
    if (value < best) best = value;
  }
  return best;
}

export function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function add(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

function scale(a: Vec3, s: number): Vec3 {
  return [a[0] * s, a[1] * s, a[2] * s];
}

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** Unit geometric normal by winding, or null for a degenerate triangle. */
export function triangleNormal(a: Vec3, b: Vec3, c: Vec3): Vec3 | null {
  const n = cross(sub(b, a), sub(c, a));
  const length = Math.hypot(n[0], n[1], n[2]);
  return length < EPSILON ? null : [n[0] / length, n[1] / length, n[2] / length];
}

/** Closest point on a triangle to a point (Ericson, Real-Time Collision Detection, 5.1.5). */
export function closestPointOnTriangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3): Vec3 {
  const ab = sub(b, a);
  const ac = sub(c, a);
  const ap = sub(p, a);
  const d1 = dot(ab, ap);
  const d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const bp = sub(p, b);
  const d3 = dot(ab, bp);
  const d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return add(a, scale(ab, d1 / (d1 - d3)));
  const cp = sub(p, c);
  const d5 = dot(ab, cp);
  const d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return add(a, scale(ac, d2 / (d2 - d6)));
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
    return add(b, scale(sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))));
  }
  const denominator = va + vb + vc;
  if (Math.abs(denominator) < EPSILON) {
    // Degenerate triangle: the nearest of its three edges.
    let best = a;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const [s, t] of [[a, b], [b, c], [c, a]] as const) {
      const q = closestPointOnSegment(p, s, t);
      const value = distance(p, q);
      if (value < bestDistance) {
        bestDistance = value;
        best = q;
      }
    }
    return best;
  }
  const v = vb / denominator;
  const w = vc / denominator;
  return add(add(a, scale(ab, v)), scale(ac, w));
}

export function pointTriangleDistance(p: Vec3, a: Vec3, b: Vec3, c: Vec3): number {
  return distance(p, closestPointOnTriangle(p, a, b, c));
}

export function closestPointOnSegment(p: Vec3, a: Vec3, b: Vec3): Vec3 {
  const ab = sub(b, a);
  const length2 = dot(ab, ab);
  if (length2 < EPSILON) return a;
  const t = Math.max(0, Math.min(1, dot(sub(p, a), ab) / length2));
  return add(a, scale(ab, t));
}

/** Distance between two segments (Ericson, 5.1.9). */
export function segmentSegmentDistance(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3): number {
  const d1 = sub(q1, p1);
  const d2 = sub(q2, p2);
  const r = sub(p1, p2);
  const a = dot(d1, d1);
  const e = dot(d2, d2);
  const f = dot(d2, r);
  let s: number;
  let t: number;
  if (a <= EPSILON && e <= EPSILON) return distance(p1, p2);
  if (a <= EPSILON) {
    s = 0;
    t = Math.max(0, Math.min(1, f / e));
  } else {
    const c = dot(d1, r);
    if (e <= EPSILON) {
      t = 0;
      s = Math.max(0, Math.min(1, -c / a));
    } else {
      const b = dot(d1, d2);
      const denominator = a * e - b * b;
      s = denominator > EPSILON ? Math.max(0, Math.min(1, (b * f - c * e) / denominator)) : 0;
      t = (b * s + f) / e;
      if (t < 0) {
        t = 0;
        s = Math.max(0, Math.min(1, -c / a));
      } else if (t > 1) {
        t = 1;
        s = Math.max(0, Math.min(1, (b - c) / a));
      }
    }
  }
  return distance(add(p1, scale(d1, s)), add(p2, scale(d2, t)));
}

/** Whether segment pq meets triangle abc, both faces, endpoints included (Moller-Trumbore). */
export function segmentIntersectsTriangle(p: Vec3, q: Vec3, a: Vec3, b: Vec3, c: Vec3): boolean {
  const direction = sub(q, p);
  const e1 = sub(b, a);
  const e2 = sub(c, a);
  const h = cross(direction, e2);
  const det = dot(e1, h);
  if (Math.abs(det) < EPSILON) return false;
  const inverse = 1 / det;
  const s = sub(p, a);
  const u = inverse * dot(s, h);
  if (u < 0 || u > 1) return false;
  const qv = cross(s, e1);
  const v = inverse * dot(direction, qv);
  if (v < 0 || u + v > 1) return false;
  const t = inverse * dot(e2, qv);
  return t >= 0 && t <= 1;
}

/** Distance between a segment and a triangle. Zero when they meet. */
export function segmentTriangleDistance(p: Vec3, q: Vec3, a: Vec3, b: Vec3, c: Vec3): number {
  if (segmentIntersectsTriangle(p, q, a, b, c)) return 0;
  return Math.min(
    pointTriangleDistance(p, a, b, c),
    pointTriangleDistance(q, a, b, c),
    segmentSegmentDistance(p, q, a, b),
    segmentSegmentDistance(p, q, b, c),
    segmentSegmentDistance(p, q, c, a),
  );
}

/**
 * Whether a ray from `origin` along a fixed direction crosses triangle abc at t > 0.
 *
 * Used for even-odd containment in a closed component. The direction is fixed and deliberately
 * not axis-aligned, so it does not graze the edges of axis-aligned boxes; nothing is sampled.
 */
export const PARITY_DIRECTION: Vec3 = (() => {
  const raw: Vec3 = [0.7548776662466927, 0.5698402909980532, 0.3247179572447460];
  const length = Math.hypot(raw[0], raw[1], raw[2]);
  return [raw[0] / length, raw[1] / length, raw[2] / length];
})();

export function rayCrossesTriangle(origin: Vec3, a: Vec3, b: Vec3, c: Vec3): boolean {
  const e1 = sub(b, a);
  const e2 = sub(c, a);
  const h = cross(PARITY_DIRECTION, e2);
  const det = dot(e1, h);
  if (Math.abs(det) < EPSILON) return false;
  const inverse = 1 / det;
  const s = sub(origin, a);
  const u = inverse * dot(s, h);
  if (u < 0 || u > 1) return false;
  const qv = cross(s, e1);
  const v = inverse * dot(PARITY_DIRECTION, qv);
  if (v < 0 || u + v > 1) return false;
  return inverse * dot(e2, qv) > EPSILON;
}

/** Height of triangle abc's plane at (x, z) if (x, z) lies inside its planar projection. */
export function heightOnTriangle(x: number, z: number, a: Vec3, b: Vec3, c: Vec3): number | null {
  const denominator = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2]);
  if (Math.abs(denominator) < EPSILON) return null;
  const w1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / denominator;
  const w2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / denominator;
  const w3 = 1 - w1 - w2;
  const slack = -1e-9;
  if (w1 < slack || w2 < slack || w3 < slack) return null;
  return w1 * a[1] + w2 * b[1] + w3 * c[1];
}
