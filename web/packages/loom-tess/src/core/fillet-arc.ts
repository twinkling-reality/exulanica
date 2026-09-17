/**
 * THE FILLET ARC RULE: THE CORNER BETWEEN TWO KERB LINES, BY INTEGER CHORD BISECTION.
 *
 * A curb's `kerb_line_mm` runs from the tangent point where one corner arc ends to the tangent
 * point where the next begins, and the arc between them has the curb's `corner_radius_mm`. The
 * grammar leaves the arc to the tessellator (`exulanica.grammar.grammars.city.streets`). This is
 * that rule, with no angle and no sine:
 *
 *   Given the tangent point `P` where the first line ends, travelling along `into` (its last piece,
 *   in plan), the tangent point `Q` where the second line starts, travelling along `out` (its first
 *   piece), the radius `r` and a segment count `n`, a power of two:
 *
 *   1. TURN. `cross(into, out)` is positive for a left turn and negative for a right one. Zero is
 *      refused: parallel lines have no fillet.
 *   2. CENTRE. From each tangent point, `r` along the normal on the turning side, by the facing
 *      rule (`facing.ts`): `C_P = P + turn(into, 0, +r or -r)` and `C_Q = Q + turn(out, 0, +r or -r)`.
 *      The centre is `C = floor((C_P + C_Q) / 2)` on each axis, so neither tangent point is
 *      favoured.
 *   3. POINTS. `arc[0] = P` and `arc[n] = Q`, exactly, so the arc meets both lines with no gap.
 *      Every other point halves a gap between two points already placed: between `arc[i]` and
 *      `arc[j]`, the point `arc[(i + j) / 2]` is `C + turn(u + v, r, 0)`, with `u` and `v` the plan
 *      vectors from `C` to the two, which is `r` from `C` toward the middle of the chord. Its height
 *      is `floor((z_i + z_j) / 2)`. Opposite points, where `u + v` is zero, are refused.
 *
 * A point depends only on the two it halves, so the order the gaps are filled in cannot change
 * the result. Every placed point is within a millimetre or two of the circle; the tangent points
 * are wherever the records put them.
 *
 * What this rule does not decide, stated so nobody assumes it: the segment count. No record states
 * one. `filletSegmentsWithin` finds the least power of two whose every chord keeps within a given
 * sagitta, exactly, but the sagitta itself is not chosen here; the expander that wires this in
 * states where it comes from, with a new `TESSELLATOR_SOURCE_VERSION`. Nor does it check that the
 * tangent points are consistent with the radius; that is the grammar's document check.
 *
 * Not yet wired into a bake. It changes no container until an expander calls it.
 */
import { turnByFacing } from './facing.js';
import { add, crossVectors, dot, floorDivide, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';

function plan(point: Space): Plan {
  return [point[0], point[1]];
}

function offset(point: Plan, by: Plan, where: string): Plan {
  return [add(point[0], by[0], where), add(point[1], by[1], where)];
}

function between(from: Plan, to: Plan, where: string): Plan {
  return [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
}

/** Whether `count` is a positive power of two. */
function isPowerOfTwo(count: number): boolean {
  if (!Number.isSafeInteger(count)) return false;
  if (count < 1) return false;
  let rest = count;
  while (rest > 1) {
    if (rest % 2 !== 0) return false;
    rest /= 2;
  }
  return true;
}

/** The centre of the fillet from `P` along `into` to `Q` along `out`, by the rule's second step. */
export function filletCentre(p: Space, into: Plan, q: Space, out: Plan, radius: number, where: string): Plan {
  if (!Number.isSafeInteger(radius)) throw new GeometryError(`${where} has a radius that is not an integer`);
  if (radius < 1) throw new GeometryError(`${where} has no radius, so there is no arc`);
  const turn = crossVectors(into, out, where);
  if (turn === 0) throw new GeometryError(`${where} joins parallel lines, which have no fillet`);
  const side = turn > 0 ? radius : -radius;
  const fromP = offset(plan(p), turnByFacing(into, 0, side, where), where);
  const fromQ = offset(plan(q), turnByFacing(out, 0, side, where), where);
  return [
    floorDivide(add(fromP[0], fromQ[0], where), 2, where),
    floorDivide(add(fromP[1], fromQ[1], where), 2, where),
  ];
}

/**
 * The fillet arc from `p` to `q`, `segments + 1` points, the first `p` and the last `q`, by the
 * fillet arc rule. `into` is the direction the first line arrives at `p` along, and `out` the
 * direction the second leaves `q` along.
 */
export function filletArc(
  p: Space,
  into: Plan,
  q: Space,
  out: Plan,
  radius: number,
  segments: number,
  where: string,
): Space[] {
  if (!isPowerOfTwo(segments)) throw new GeometryError(`${where} has ${String(segments)} segments, not a power of two`);
  const centre = filletCentre(p, into, q, out, radius, where);
  const arc = new Array<Space>(segments + 1);
  arc[0] = p;
  arc[segments] = q;
  for (let gap = segments; gap > 1; gap /= 2) {
    for (let start = 0; start < segments; start += gap) {
      const first = arc[start]!;
      const last = arc[start + gap]!;
      const toward = offset(between(centre, plan(first), where), between(centre, plan(last), where), where);
      if (toward[0] === 0 && toward[1] === 0) throw new GeometryError(`${where} halves a chord between opposite points`);
      const [x, y] = offset(centre, turnByFacing(toward, radius, 0, where), where);
      arc[start + gap / 2] = [x, y, floorDivide(add(first[2], last[2], where), 2, where)];
    }
  }
  return arc;
}

/**
 * The least power of two, up to `maximumSegments`, for which every chord of the fillet arc keeps
 * within `maximumSagittaMm` of the circle: `4 * (r - s)^2 <= |u + v|^2` for each chord's plan
 * vectors `u` and `v` from the centre, which is the chord's midpoint at least `r - s` from it,
 * exactly. Refused when no count up to the maximum does.
 */
export function filletSegmentsWithin(
  p: Space,
  into: Plan,
  q: Space,
  out: Plan,
  radius: number,
  maximumSagittaMm: number,
  maximumSegments: number,
  where: string,
): number {
  if (!isPowerOfTwo(maximumSegments)) throw new GeometryError(`${where} has a segment maximum that is not a power of two`);
  if (!Number.isSafeInteger(maximumSagittaMm)) throw new GeometryError(`${where} has a sagitta that is not an integer`);
  if (maximumSagittaMm < 0) throw new GeometryError(`${where} has a negative sagitta`);
  const centre = filletCentre(p, into, q, out, radius, where);
  const reach = subtract(radius, maximumSagittaMm, where);
  // A sagitta as large as the radius admits any chord short of a half circle.
  if (reach <= 0) return 1;
  const doubledReach = multiply(reach, 2, where);
  const least = multiply(doubledReach, doubledReach, where);
  for (let segments = 1; segments <= maximumSegments; segments *= 2) {
    const arc = filletArc(p, into, q, out, radius, segments, where);
    const within = arc.slice(1).every((point, index) => {
      const sum = offset(between(centre, plan(arc[index]!), where), between(centre, plan(point), where), where);
      return dot(sum, sum, where) >= least;
    });
    if (within) return segments;
  }
  throw new GeometryError(`${where} needs more than ${maximumSegments} segments to keep within ${maximumSagittaMm} mm`);
}
