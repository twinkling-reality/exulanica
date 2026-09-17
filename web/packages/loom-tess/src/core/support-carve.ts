/**
 * THE SUPPORT CARVE RULE: SUPPORT KEPT CLEAR OF WHAT OBSTRUCTS A CAPSULE, IN INTEGERS.
 *
 * A surface a person may stand on is support only where a capsule stood on it meets nothing. What it
 * must keep clear of comes as convex pieces: a ring clearance round a record's base ring
 * (`ring-clearance.ts`), or the plan box of a part low enough to stand in the way, each already
 * grown by the capsule's radius. This rule cuts support to what is left:
 *
 *   1. Every clearance piece is GROWN by a millimetre on each axis, the convex hull of its corners
 *      moved a millimetre each way, which holds the piece itself.
 *   2. Each support triangle is carved by those grown pieces with the piece carve rule
 *      (`piece-carve.ts`), whose hulls lie within their face grown by a millimetre on each axis.
 *      Growing first and cutting second is what makes the hulls stay outside the clearance itself:
 *      support never enters what obstructs, which is the claim a capsule depends on.
 *   3. Each kept walk is cut into triangles by the ring rule, its heights the source triangle's own
 *      plane, floored, so support is sampled at the height its surface states.
 *
 * What it gives up is under two millimetres of support beside an obstruction: a millimetre of
 * growth and a millimetre of hull. Nothing else is lost, and nothing unsupported is kept. What it
 * keeps may reach a millimetre past the triangle it came from, on each axis, which is what stops a
 * crack opening where two triangles of one surface share a sloping edge.
 */
import { add } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';
import { carvedPiece, heightOnPlane, hullKeepingEdges, twiceArea, withArea } from './piece-carve.js';
import type { ObstructionWalk } from './piece-carve.js';
import { triangulateRing } from './ring-triangulation.js';

/** How far a clearance piece grows before the carve, so the carve's own rounding stays outside it. */
const GROWTH_MM = 1;

/** A triangle of a surface a person may stand on, with its heights. */
export type SupportTriangle = readonly [Space, Space, Space];

/** A convex piece, counter-clockwise, a capsule may not stand in. */
export type ClearanceWalk = readonly Plan[];

/** A convex walk grown by a millimetre on each axis: the hull of its corners moved each way. */
export function grownByAMillimetre(walk: ClearanceWalk, where: string): Plan[] {
  const corners: Plan[] = [];
  for (const point of walk) {
    for (const dx of [-GROWTH_MM, GROWTH_MM]) {
      for (const dy of [-GROWTH_MM, GROWTH_MM]) {
        corners.push([add(point[0], dx, where), add(point[1], dy, where)]);
      }
    }
  }
  return hullKeepingEdges(corners, where);
}

/**
 * The grown clearance pieces, counter-clockwise, as the carve takes them. Each stays one convex
 * walk rather than a fan of triangles: the arrangement's work grows with the square of the segments
 * a piece meets, and an arc covered by sixty-four corners is sixty-four segments as a walk and
 * three times that as a fan.
 */
export function clearanceObstructions(walks: readonly ClearanceWalk[], where: string): ObstructionWalk[] {
  const out: ObstructionWalk[] = [];
  for (const walk of walks) {
    const grown = grownByAMillimetre(walk, where);
    if (grown.length < 3) continue;
    out.push(grown);
  }
  return withArea(out, where);
}

/**
 * The support triangles less every clearance, by the support carve rule. Each triangle given is
 * carved on its own, so the answer keeps to the surfaces it was given. `hold`, when given, is a
 * convex region every kept corner must lie in: a caller whose surfaces must stay inside a stated
 * extent names that extent, and the millimetre a hull may reach past its triangle is trimmed at
 * that boundary alone, where there is no neighbouring triangle to crack away from.
 */
export function carveSupport(
  support: readonly SupportTriangle[],
  clearances: readonly ClearanceWalk[],
  hold: readonly Plan[] | undefined,
  where: string,
): SupportTriangle[] {
  const obstructions = clearanceObstructions(clearances, where);
  const spans = obstructions.map(spanOf);
  const out: SupportTriangle[] = [];
  for (const triangle of support) {
    const turned: SupportTriangle = twiceArea(plan(triangle[0]), plan(triangle[1]), plan(triangle[2]), where) < 0
      ? [triangle[0], triangle[2], triangle[1]]
      : triangle;
    const piece = turned.map(plan);
    if (twiceArea(piece[0]!, piece[1]!, piece[2]!, where) === 0) continue;
    // Two answers need no arrangement: a triangle no clearance reaches is kept whole, and one a
    // single clearance holds entirely is gone. Spans are compared first, being the cheapest test.
    const span = spanOf(piece);
    const near: ObstructionWalk[] = [];
    let held = false;
    for (let index = 0; index < obstructions.length; index += 1) {
      if (apartInSpan(span, spans[index]!)) continue;
      const obstruction = obstructions[index]!;
      if (holdsAll(obstruction, piece, where)) {
        held = true;
        break;
      }
      if (meets(piece, obstruction, where)) near.push(obstruction);
    }
    if (held) continue;
    if (near.length === 0) {
      out.push(turned);
      continue;
    }
    // Not held to the triangle: a sliver shaved off a sloping edge would crack one surface in two.
    for (const walk of carvedPiece(piece, near, hold, where)) {
      const corners = walk.map((point): Space => [point[0], point[1], heightOnPlane(turned, point, where)]);
      const cut = triangulateRing(walk, where);
      for (let corner = 0; corner + 2 < cut.length; corner += 3) {
        out.push([corners[cut[corner]!]!, corners[cut[corner + 1]!]!, corners[cut[corner + 2]!]!]);
      }
    }
  }
  return out;
}

const plan = (point: Space): Plan => [point[0], point[1]];

/** A walk's plan span, west, south, east and north. */
function spanOf(walk: readonly Plan[]): readonly [number, number, number, number] {
  let [west, south] = [walk[0]![0], walk[0]![1]];
  let [east, north] = [west, south];
  for (const point of walk) {
    if (point[0] < west) west = point[0];
    if (point[0] > east) east = point[0];
    if (point[1] < south) south = point[1];
    if (point[1] > north) north = point[1];
  }
  return [west, south, east, north];
}

/** Whether two spans are apart, which puts their walks apart. */
function apartInSpan(first: readonly number[], second: readonly number[]): boolean {
  if (first[2]! < second[0]!) return true;
  if (second[2]! < first[0]!) return true;
  if (first[3]! < second[1]!) return true;
  return second[3]! < first[1]!;
}

/** Whether a closed counter-clockwise convex walk holds every point of another. */
function holdsAll(walk: readonly Plan[], points: readonly Plan[], where: string): boolean {
  return points.every((point) => walk.every((corner, index) =>
    twiceArea(corner, walk[(index + 1) % walk.length]!, point, where) >= 0));
}

/** Whether two closed counter-clockwise convex walks share a point, by the separating axis rule. */
function meets(first: readonly Plan[], second: readonly Plan[], where: string): boolean {
  const apart = (edges: readonly Plan[], points: readonly Plan[]): boolean => edges.some((from, index) => {
    const to = edges[(index + 1) % edges.length]!;
    return points.every((point) => twiceArea(from, to, point, where) <= 0);
  });
  if (apart(first, second)) return false;
  return !apart(second, first);
}
