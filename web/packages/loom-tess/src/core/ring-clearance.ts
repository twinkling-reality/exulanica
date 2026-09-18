/**
 * THE RING CLEARANCE RULE: EVERYWHERE A CAPSULE OF A GIVEN RADIUS MEETS A RING, IN INTEGERS.
 *
 * A record that obstructs a walking capsule states the ring it stands on. Nothing may be supported
 * within the capsule's radius of that ring, so support is carved by the region
 * `ring + a disk of the radius`, which has an arc at every corner and no integer vertex anywhere.
 * This rule covers that region with convex pieces whose vertices are integers, each lying outside
 * the true region, so a carve by them never leaves support the capsule would meet:
 *
 *   1. THE RING itself, cut into triangles by the ring rule: what stands inside it.
 *   2. A BAND along each edge: the parallelogram from the edge to the edge moved outward by a step
 *      whose part across the edge is at least the radius. That step is the corner rule's point at
 *      the radius along the outward normal, moved up to one further out on each axis, taking the
 *      least that reaches, so it passes the radius by under the diagonal of one step on each axis.
 *      It may lean along the edge by as much, which leaves a sliver at each end; a point in that
 *      sliver is within the radius plus that lean of the corner there, so the corner's hull holds
 *      it.
 *   3. A HULL round each corner covering the disk of the radius plus that lean: steps out at that
 *      distance plus a millimetre, from the four axes, each gap halved by the step along the sum of
 *      the two round it, which bisects their angle because both are the same distance out. A chord
 *      falls inside the circle it cuts, so the count doubles until every chord of the hull is at
 *      least that distance from the corner, which is checked exactly, not assumed.
 *
 * Every test is an integer comparison, and a distance is compared as a square, in BigInt: nothing
 * here can round.
 *
 * WHAT IT COVERS BEYOND THE TRUE REGION is `CLEARANCE_REACH_MM`, which is the sum of the parts
 * below rather than a number written down beside them. It is absolute rather than proportional, so
 * at a capsule's radius it is under two parts in a hundred, and at a small radius it is most of the
 * region. WHAT IT LEAVES OUT IS NOTHING, and that half is the one that keeps a capsule from standing
 * where it would collide. Read `CLEARANCE_REACH_MM` for how firmly each half is held, because they
 * are not held equally.
 */
import { alongByCornerRule } from './fillet-arc.js';
import { add, exact, GeometryError, multiply, subtract } from './integer-math.js';
import { hullKeepingEdges } from './piece-carve.js';
import type { Plan } from './integer-math.js';
import { requireSimpleRing, triangulateRing } from './ring-triangulation.js';

/**
 * How far a band's far side can slant along its edge: its outward step is within one of the true
 * step on each axis, so it leans under the diagonal of that, and a corner covers the radius plus
 * this, which holds what the lean leaves.
 */
const BAND_SLANT_MM = 2;

/** How far past the radius a corner's points start, before the hull's chords are checked. */
const CORNER_MARGIN_MM = 1;

/**
 * A bound on the diagonal of one millimetre on each axis, which is what flooring a point onto the
 * lattice and then stepping out by one can cost. `fillet-arc`'s `CORNER_ROUNDING_MM` is the same
 * bound for the same reason.
 */
const STEP_DIAGONAL_MM = 2;

/**
 * HOW FAR PAST THE RADIUS THIS RULE'S PIECES CAN REACH, and how firmly that is held.
 *
 * It is the sum of the three parts this rule can account for, not a number set beside them: a
 * band's slant, a corner's margin, and the diagonal a floored point costs when it steps out.
 * Writing it as the sum is the point, because a number and its account cannot then drift apart.
 *
 * IT IS TESTED, NOT PROVED. `test/ring-clearance.test.ts` asserts that every corner of every piece
 * is within `radius + CLEARANCE_REACH_MM` of the ring or inside it, over rings at radii 1, 5 and
 * the capsule's 340, and a radius far from those has not been run. The bound covers a whole piece
 * and not only its corners because the pieces are convex, and a convex piece's furthest point from
 * a ring is a corner. Re-derived from this source the worst case is about 4.414, three millimetres
 * of stated margin plus the diagonal of one, so five is the sum rounded up rather than measured.
 *
 * THE OTHER HALF IS WEAKER AND IS THE ONE THAT PROTECTS A WALKER. That the pieces HOLD everything
 * within the radius, so no support survives where a capsule would collide, is checked by SAMPLING:
 * a half-millimetre lattice for small rings and seeded points at the capsule radius. It is a
 * sampled claim rather than an exhaustive one, and anything leaning on it should know that.
 */
export const CLEARANCE_REACH_MM = BAND_SLANT_MM + CORNER_MARGIN_MM + STEP_DIAGONAL_MM;

/** How many times a corner's directions may be bisected before the rule refuses the ring. */
const MOST_BISECTIONS = 8;

/** The directions a corner hull starts from, the four axes, before bisection. */
const AXIS_DIRECTIONS: readonly Plan[] = [[1, 0], [0, 1], [-1, 0], [0, -1]];

/** A convex piece of a clearance region: integer vertices, counter-clockwise, with area. */
export type ClearancePiece = readonly Plan[];

const bigDot = (u: Plan, v: Plan): bigint => BigInt(u[0]) * BigInt(v[0]) + BigInt(u[1]) * BigInt(v[1]);
const bigCross = (u: Plan, v: Plan): bigint => BigInt(u[0]) * BigInt(v[1]) - BigInt(u[1]) * BigInt(v[0]);
const minus = (a: Plan, b: Plan, where: string): Plan => [subtract(a[0], b[0], where), subtract(a[1], b[1], where)];
const plus = (a: Plan, b: Plan, where: string): Plan => [add(a[0], b[0], where), add(a[1], b[1], where)];
const sign = (value: number): number => (value > 0 ? 1 : value < 0 ? -1 : 0);

/**
 * Whether the part of `step` across `direction` is at least `distance`: `step . n >= distance |n|`
 * with `n` the outward normal, compared as squares so no root is taken.
 */
function reachesAcross(step: Plan, normal: Plan, distance: number, where: string): boolean {
  const along = bigDot(step, normal);
  if (along < 0n) return false;
  exact(distance, where);
  return along * along >= BigInt(distance) * BigInt(distance) * bigDot(normal, normal);
}

/**
 * An integer step whose part along `normal` is at least `distance`: the corner rule's point at that
 * distance, which floors each axis, moved up to one further step out on each axis.
 */
function stepAlong(normal: Plan, distance: number, where: string): Plan {
  const floored = alongByCornerRule(normal, distance, where);
  const out: Plan = [sign(normal[0]), sign(normal[1])];
  const candidates: Plan[] = [
    floored,
    [add(floored[0], out[0], where), floored[1]],
    [floored[0], add(floored[1], out[1], where)],
    [add(floored[0], out[0], where), add(floored[1], out[1], where)],
  ];
  // The least of those that reaches, so a step passes the distance by as little as it can.
  const reaching = candidates.filter((candidate) => reachesAcross(candidate, normal, distance, where));
  if (reaching.length === 0) throw new GeometryError(`${where} found no integer step ${String(distance)} along a normal`);
  return reaching.reduce((best, candidate) => (bigDot(candidate, normal) < bigDot(best, normal) ? candidate : best));
}

/**
 * A corner's steps out, in order round it: the four axes at `distance`, then each gap halved by the
 * step along the sum of the two steps round it, which bisects their angle because both are that
 * distance out, as the fillet arc rule's bisection does.
 */
function stepsRound(distance: number, steps: number, where: string): Plan[] {
  let round = AXIS_DIRECTIONS.map((axis) => stepAlong(axis, distance, where));
  for (let step = 0; step < steps; step += 1) {
    const next: Plan[] = [];
    round.forEach((here, index) => {
      const after = round[(index + 1) % round.length]!;
      next.push(here, stepAlong(plus(here, after, where), distance, where));
    });
    round = next;
  }
  return round;
}

/** The convex hull of points given in order round a centre, counter-clockwise, corners only. */
function convexWalk(points: readonly Plan[], where: string): Plan[] {
  const sorted = [...points].sort((a, b) => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]));
  const chain = (ordered: readonly Plan[]): Plan[] => {
    const out: Plan[] = [];
    for (const point of ordered) {
      while (out.length >= 2) {
        const [before, last] = [out[out.length - 2]!, out[out.length - 1]!];
        if (bigCross(minus(last, before, where), minus(point, before, where)) > 0n) break;
        out.pop();
      }
      out.push(point);
    }
    return out;
  };
  const lower = chain(sorted);
  const upper = chain([...sorted].reverse());
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** Whether every chord of a closed convex walk is at least `distance` from `centre`. */
function chordsClear(walk: readonly Plan[], centre: Plan, distance: number, where: string): boolean {
  return walk.every((from, index) => {
    const to = walk[(index + 1) % walk.length]!;
    const edge = minus(to, from, where);
    const toCentre = minus(centre, from, where);
    // The centre lies between the chord's ends along it, since the walk goes round the centre, so
    // its distance from the chord is the cross product over the chord's length.
    const across = bigCross(edge, toCentre);
    const spread = across < 0n ? -across : across;
    return spread * spread >= BigInt(distance) * BigInt(distance) * bigDot(edge, edge);
  });
}

/** A convex integer walk round `centre` that holds every point within `radius` of it. */
function cornerHull(centre: Plan, radius: number, where: string): ClearancePiece {
  const out = add(radius, CORNER_MARGIN_MM, where);
  for (let steps = 0; steps <= MOST_BISECTIONS; steps += 1) {
    const walk = convexWalk(stepsRound(out, steps, where).map((step) => plus(centre, step, where)), where);
    if (walk.length < 3) continue;
    if (chordsClear(walk, centre, radius, where)) return walk;
  }
  throw new GeometryError(`${where} could not hold a disk of ${String(radius)} in an integer walk`);
}

/**
 * Convex pieces whose union holds every point within `radius` of the closed ring, by the ring
 * clearance rule. The ring is the grammar's own: counter-clockwise, simple, in integer millimetres.
 */
export function ringClearance(ring: readonly Plan[], radius: number, where: string): ClearancePiece[] {
  requireSimpleRing(ring, where);
  if (exact(radius, where) <= 0) throw new GeometryError(`${where} clears a radius of ${String(radius)}, which is not positive`);
  const pieces: ClearancePiece[] = [];
  const cut = triangulateRing(ring, where);
  for (let corner = 0; corner + 2 < cut.length; corner += 3) {
    pieces.push([ring[cut[corner]!]!, ring[cut[corner + 1]!]!, ring[cut[corner + 2]!]!]);
  }
  ring.forEach((from, index) => {
    const to = ring[(index + 1) % ring.length]!;
    const direction = minus(to, from, where);
    // A counter-clockwise ring keeps its inside on the left, so its outward normal is to the right.
    const normal: Plan = [direction[1], -direction[0]];
    const step = stepAlong(normal, radius, where);
    pieces.push([from, to, plus(to, step, where), plus(from, step, where)]);
    pieces.push(cornerHull(from, add(radius, BAND_SLANT_MM, where), where));
  });
  if (!turnsOnlyLeft(ring, where)) return pieces;
  // A CONVEX RING'S CLEARANCE IS CONVEX, so the hull of every piece's corners is the same region as
  // the pieces, held to the same two claims: it holds everything they hold, since it holds them,
  // and it lies inside what they lie inside, since that region is convex too and a hull of subsets
  // of a convex region stays inside it. One piece where there were a dozen, which is what a carve
  // costs: its work grows with the square of the segments a piece meets.
  const corners: Plan[] = [];
  for (const piece of pieces) {
    for (const point of piece) corners.push(point);
  }
  const whole = hullKeepingEdges(corners, where);
  if (whole.length < 3) return pieces;
  return [whole];
}

/** Whether a counter-clockwise ring turns only left, so the region it clears is convex. */
function turnsOnlyLeft(ring: readonly Plan[], where: string): boolean {
  return ring.every((here, index) => {
    const before = ring[(index + ring.length - 1) % ring.length]!;
    const after = ring[(index + 1) % ring.length]!;
    const first = minus(here, before, where);
    const second = minus(after, here, where);
    return subtract(multiply(first[0], second[1], where), multiply(first[1], second[0], where), where) >= 0;
  });
}
