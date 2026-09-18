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
 * RINGS WITH HOLES (a tier and its light wells) are first joined into one ring, then cut the same
 * way:
 *
 *   1. The outer ring and every hole are checked as above, every hole must lie strictly inside the
 *      outer ring (`geometry.ring_inside_ring`), and no two holes may meet (`geometry.rings_disjoint`).
 *   2. Holes are joined in descending order of their greatest x, ties by their order as given.
 *   3. A hole's BRIDGE starts at its vertex with the greatest x, the first such in hole order, `M`.
 *      It ends at a vertex `V` of the ring joined so far, taken in ascending squared distance from
 *      `M`, ties by position in that ring, skipping any position the ring already holds twice (an
 *      earlier bridge's end): the first whose segment from `M` meets no edge of the joined ring or of
 *      a hole not yet joined anywhere but at `V` or `M` themselves. Such a segment runs through the
 *      interior. None found refuses the ring.
 *   4. The joined ring runs to `V`, round the hole clockwise from `M` back to `M`, back to `V`, and on.
 *   5. It is cut by the rule above, except that a vertex at the same position as a corner of the
 *      candidate ear does not stop that ear: the two ends of a bridge are such copies.
 *
 * Triangles index the outer ring's vertices, then each hole's in the order given, so every vertex
 * is an original one, and their areas sum to the outer ring's less the holes'.
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

/** Where a point lies against a ring: `geometry.point_in_ring`. */
export type RingSide = 'inside' | 'outside' | 'boundary';

export function pointInRing(point: Plan, ring: readonly Plan[], where: string): RingSide {
  const count = ring.length;
  for (let index = 0; index < count; index += 1) {
    if (onSegment(point, ring[index]!, ring[(index + 1) % count]!, where)) return 'boundary';
  }
  let inside = false;
  ring.forEach((a, index) => {
    const b = ring[(index + 1) % count]!;
    if ((a[1] > point[1]) !== (b[1] > point[1])) {
      const left = multiply(subtract(point[0], a[0], where), subtract(b[1], a[1], where), where);
      const right = multiply(subtract(point[1], a[1], where), subtract(b[0], a[0], where), where);
      if (b[1] > a[1] && left < right) inside = !inside;
      if (b[1] < a[1] && left > right) inside = !inside;
    }
  });
  return inside ? 'inside' : 'outside';
}

function edgesMeet(first: readonly Plan[], second: readonly Plan[], where: string): boolean {
  return first.some((a, index) => second.some((c, other) => segmentsIntersect(
    a, first[(index + 1) % first.length]!, c, second[(other + 1) % second.length]!, where,
  )));
}

/** Whether `inner` lies strictly inside `outer`, touching nowhere: `geometry.ring_inside_ring`. */
export function ringInsideRing(inner: readonly Plan[], outer: readonly Plan[], where: string): boolean {
  if (inner.some((point) => pointInRing(point, outer, where) !== 'inside')) return false;
  return !edgesMeet(inner, outer, where);
}

/** Whether two rings share no point at all: `geometry.rings_disjoint`. */
export function ringsDisjoint(first: readonly Plan[], second: readonly Plan[], where: string): boolean {
  if (edgesMeet(first, second, where)) return false;
  if (first.some((point) => pointInRing(point, second, where) !== 'outside')) return false;
  return second.every((point) => pointInRing(point, first, where) === 'outside');
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
  return cutEars(ring, ring.map((_point, index) => index), where);
}

const samePlace = (a: Plan, b: Plan): boolean => a[0] === b[0] && a[1] === b[1];

/**
 * Ear clipping over `order`, a ring of indices into `points` that may visit one position twice,
 * as a joined ring does at each bridge. A copy of a candidate ear's corner does not stop the ear.
 */
function cutEars(points: readonly Plan[], order: readonly number[], where: string): number[] {
  const ring = points;
  const remaining = [...order];
  const triangles: number[] = [];
  while (remaining.length > 3) {
    const count = remaining.length;
    const ear = remaining.findIndex((b, position) => {
      const a = remaining[(position + count - 1) % count]!;
      const c = remaining[(position + 1) % count]!;
      if (cross(ring[a]!, ring[b]!, ring[c]!, where) <= 0) return false;
      return !remaining.some((other) => {
        const place = ring[other]!;
        if (samePlace(place, ring[a]!)) return false;
        if (samePlace(place, ring[b]!)) return false;
        if (samePlace(place, ring[c]!)) return false;
        return inClosedTriangle(place, ring[a]!, ring[b]!, ring[c]!, where);
      });
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

/** Whether the segment from `m` to `v` meets the edge `p q` anywhere but at `m` or `v` themselves. */
function bridgeMeets(m: Plan, v: Plan, p: Plan, q: Plan, where: string): boolean {
  if (!segmentsIntersect(m, v, p, q, where)) return false;
  const ends = [m, v];
  const sharesEnd = [p, q].some((point) => ends.some((end) => samePlace(end, point)));
  if (!sharesEnd) return true;
  // Sharing an end, the edge meets the bridge elsewhere only by running along it.
  if (cross(m, v, p, where) !== 0) return false;
  if (cross(m, v, q, where) !== 0) return false;
  const inside = (point: Plan): boolean => !ends.some((end) => samePlace(end, point)) && onSegment(point, m, v, where);
  if (inside(p)) return true;
  if (inside(q)) return true;
  return onSegment(m, p, q, where) && onSegment(v, p, q, where);
}

/**
 * The outer ring and its holes cut into counter-clockwise triangles by the ring rule's hole step.
 * `vertices` is the outer ring's vertices, then each hole's in the order given, and `triangles`
 * indexes it, three per triangle.
 */
export function triangulateRingWithHoles(
  outer: readonly Plan[],
  holes: readonly (readonly Plan[])[],
  where: string,
): { readonly vertices: readonly Plan[]; readonly triangles: number[] } {
  requireSimpleRing(outer, `${where} outer ring`);
  holes.forEach((hole, index) => {
    requireSimpleRing(hole, `${where} hole ${index}`);
    if (!ringInsideRing(hole, outer, where)) throw new GeometryError(`${where}: hole ${index} is not strictly inside the outer ring`);
    holes.forEach((other, second) => {
      if (second > index && !ringsDisjoint(hole, other, where)) {
        throw new GeometryError(`${where}: holes ${index} and ${second} meet`);
      }
    });
  });
  const vertices: Plan[] = [...outer];
  const starts: number[] = [];
  for (const hole of holes) {
    starts.push(vertices.length);
    vertices.push(...hole);
  }
  const greatestX = (hole: readonly Plan[]): number => hole.reduce((best, point) => (point[0] > best ? point[0] : best), hole[0]![0]);
  const joinOrder = holes.map((_hole, index) => index).sort((a, b) => {
    const byX = greatestX(holes[b]!) - greatestX(holes[a]!);
    return byX !== 0 ? byX : a - b;
  });
  let joined: number[] = outer.map((_point, index) => index);
  const unjoined = new Set(joinOrder);
  for (const holeIndex of joinOrder) {
    unjoined.delete(holeIndex);
    const hole = holes[holeIndex]!;
    const m = hole.findIndex((point) => point[0] === greatestX(hole));
    const mPoint = hole[m]!;
    const edges: [Plan, Plan][] = joined.map((index, position) => [vertices[index]!, vertices[joined[(position + 1) % joined.length]!]!]);
    for (const other of unjoined) {
      const ring = holes[other]!;
      ring.forEach((point, position) => edges.push([point, ring[(position + 1) % ring.length]!]));
    }
    hole.forEach((point, position) => edges.push([point, hole[(position + 1) % hole.length]!]));
    const distance = (point: Plan): number => {
      const dx = subtract(point[0], mPoint[0], where);
      const dy = subtract(point[1], mPoint[1], where);
      return add(multiply(dx, dx, where), multiply(dy, dy, where), where);
    };
    const copies = (point: Plan): number => joined.filter((index) => samePlace(vertices[index]!, point)).length;
    const candidates = joined
      .map((index, position) => ({ index, position }))
      .filter((candidate) => copies(vertices[candidate.index]!) === 1)
      .sort((a, b) => {
        const byDistance = distance(vertices[a.index]!) - distance(vertices[b.index]!);
        return byDistance !== 0 ? byDistance : a.position - b.position;
      });
    const bridge = candidates.find((candidate) =>
      !edges.some(([p, q]) => bridgeMeets(mPoint, vertices[candidate.index]!, p, q, where)));
    if (bridge === undefined) throw new GeometryError(`${where}: hole ${holeIndex} has no bridge to the outer ring`);
    const around: number[] = [];
    for (let step = 0; step <= hole.length; step += 1) {
      around.push(starts[holeIndex]! + ((m - step + hole.length) % hole.length));
    }
    joined = [
      ...joined.slice(0, bridge.position + 1),
      ...around,
      bridge.index,
      ...joined.slice(bridge.position + 1),
    ];
  }
  return { vertices, triangles: cutEars(vertices, joined, where) };
}
