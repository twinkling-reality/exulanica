/**
 * THE RING RULE: A SIMPLE COUNTER-CLOCKWISE RING, CUT INTO TRIANGLES BY EXACT INTEGER TESTS.
 *
 * A lot, a block, a roof deck and a tree pit are each a ring in plan, and a horizontal surface is
 * that ring cut into triangles that use the ring's own vertices and no others. The cut is ear
 * clipping, stated exactly so two builds make the same triangles in the same order:
 *
 *   1. The ring is checked first, by `exulanica.grammar.geometry.require_ring`'s own tests: at least
 *      three vertices, no zero-length edge, no spike, a positive twice area, and no two edges that
 *      touch anywhere except the vertex adjacent edges share. Anything else is refused, not
 *      repaired.
 *   2. The remaining vertices start as the whole ring, in ring order. An EAR is a remaining vertex
 *      `b`, with `a` before it and `c` after it, where `a, b, c` turns strictly left and no other
 *      remaining vertex lies inside the closed triangle `a, b, c`, its edges included. A vertex on
 *      a straight run is not an ear until its neighbours change, so no triangle has zero area and
 *      no vertex of the ring is dropped.
 *   3. The first ear in remaining order is cut off: the triangle `a, b, c` is emitted and `b`
 *      leaves the remaining vertices. The search starts again from the first remaining vertex.
 *   4. The last three remaining vertices are the last triangle.
 *
 * Every triangle is counter-clockwise, as the ring is, and their areas sum to the ring's. A simple
 * ring always has an ear; if the search ever finds none, the ring is refused rather than drawn.
 * The cost is cubic in the vertex count, which for a lot or a roof is a few dozen.
 *
 * Coordinates enter every test as differences, and a cross product subtracts two products of them,
 * so every ring up to about 67 km on a side is exact; a test a larger one would round is refused.
 *
 * Not yet wired into a bake. It changes no container until an expander calls it, which is a new
 * `TESSELLATOR_SOURCE_VERSION`.
 */
import { add, cross, dot, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';

/** Whether `point` lies on the closed segment `a`, `b`. */
function onSegment(point: Plan, a: Plan, b: Plan, where: string): boolean {
  if (cross(a, b, point, where) !== 0) return false;
  const low = (axis: number): number => (a[axis]! < b[axis]! ? a[axis]! : b[axis]!);
  const high = (axis: number): number => (a[axis]! < b[axis]! ? b[axis]! : a[axis]!);
  for (const axis of [0, 1]) {
    if (point[axis]! < low(axis)) return false;
    if (point[axis]! > high(axis)) return false;
  }
  return true;
}

const sign = (value: number): number => (value > 0 ? 1 : value < 0 ? -1 : 0);

/** Whether the closed segments `p1 p2` and `q1 q2` share any point. `geometry.segments_intersect`. */
function segmentsIntersect(p1: Plan, p2: Plan, q1: Plan, q2: Plan, where: string): boolean {
  const d1 = sign(cross(q1, q2, p1, where));
  const d2 = sign(cross(q1, q2, p2, where));
  const d3 = sign(cross(p1, p2, q1, where));
  const d4 = sign(cross(p1, p2, q2, where));
  if (d1 * d2 < 0 && d3 * d4 < 0) return true;
  if (d1 === 0 && onSegment(p1, q1, q2, where)) return true;
  if (d2 === 0 && onSegment(p2, q1, q2, where)) return true;
  if (d3 === 0 && onSegment(q1, p1, p2, where)) return true;
  return d4 === 0 && onSegment(q2, p1, p2, where);
}

/** Twice the signed area of a ring: positive when counter-clockwise. `geometry.ring_twice_area`. */
export function ringTwiceArea(ring: readonly Plan[], where: string): number {
  let total = 0;
  ring.forEach((here, index) => {
    const after = ring[(index + 1) % ring.length]!;
    total = add(total, subtract(multiply(here[0], after[1], where), multiply(after[0], here[1], where), where), where);
  });
  return total;
}

/** The ring, or a refusal naming the first test it fails. `geometry.require_ring`. */
export function requireSimpleRing(ring: readonly Plan[], where: string): readonly Plan[] {
  const count = ring.length;
  if (count < 3) throw new GeometryError(`${where} has fewer than three vertices`);
  const at = (index: number): Plan => ring[(index + count) % count]!;
  for (let index = 0; index < count; index += 1) {
    if (at(index)[0] === at(index + 1)[0] && at(index)[1] === at(index + 1)[1]) {
      throw new GeometryError(`${where}: edge ${index} has zero length`);
    }
  }
  for (let index = 0; index < count; index += 1) {
    const [before, here, after] = [at(index - 1), at(index), at(index + 1)];
    const incoming: Plan = [subtract(here[0], before[0], where), subtract(here[1], before[1], where)];
    const outgoing: Plan = [subtract(after[0], here[0], where), subtract(after[1], here[1], where)];
    const forward = dot(incoming, outgoing, where);
    if (cross(before, here, after, where) === 0 && forward < 0) {
      throw new GeometryError(`${where}: vertex ${index} is a spike`);
    }
  }
  if (ringTwiceArea(ring, where) <= 0) throw new GeometryError(`${where} is not counter-clockwise with a positive area`);
  for (let first = 0; first < count; first += 1) {
    for (let second = first + 2; second < count; second += 1) {
      if (first === 0 && second === count - 1) continue;
      if (segmentsIntersect(at(first), at(first + 1), at(second), at(second + 1), where)) {
        throw new GeometryError(`${where}: edges ${first} and ${second} intersect`);
      }
    }
  }
  return ring;
}

/** Whether `point` lies inside the closed counter-clockwise triangle `a, b, c`, edges included. */
function inClosedTriangle(point: Plan, a: Plan, b: Plan, c: Plan, where: string): boolean {
  if (cross(a, b, point, where) < 0) return false;
  if (cross(b, c, point, where) < 0) return false;
  return cross(c, a, point, where) >= 0;
}

/**
 * The ring cut into counter-clockwise triangles by the ring rule, as indices into `ring`, three
 * per triangle, in the order they are cut.
 */
export function triangulateRing(ring: readonly Plan[], where: string): number[] {
  requireSimpleRing(ring, where);
  const remaining = ring.map((_point, index) => index);
  const triangles: number[] = [];
  while (remaining.length > 3) {
    const count = remaining.length;
    const ear = remaining.findIndex((b, position) => {
      const a = remaining[(position + count - 1) % count]!;
      const c = remaining[(position + 1) % count]!;
      if (cross(ring[a]!, ring[b]!, ring[c]!, where) <= 0) return false;
      return !remaining.some((other) =>
        other !== a && other !== b && other !== c && inClosedTriangle(ring[other]!, ring[a]!, ring[b]!, ring[c]!, where));
    });
    if (ear < 0) throw new GeometryError(`${where} has no ear left to cut, so it is refused`);
    triangles.push(remaining[(ear + count - 1) % count]!, remaining[ear]!, remaining[(ear + 1) % count]!);
    remaining.splice(ear, 1);
  }
  const [a, b, c] = remaining;
  if (cross(ring[a!]!, ring[b!]!, ring[c!]!, where) <= 0) {
    throw new GeometryError(`${where} leaves a last triangle with no area, so it is refused`);
  }
  triangles.push(a!, b!, c!);
  return triangles;
}
