/**
 * THE FILLET ARC RULE: THE CORNER BETWEEN TWO KERB LINES, BY INTEGER CHORD BISECTION.
 *
 * A curb's `kerb_line_mm` runs from the tangent point where one corner arc ends to the tangent
 * point where the next begins, and the arc between them has the curb's `corner_radius_mm`. A
 * counter-clockwise walk round a face takes a left curb's kerb line first to last and a right
 * curb's last to first; the expander that joins them does that reversal. This rule takes the corner
 * from there, with no angle and no sine:
 *
 *   Given the tangent point `P` where one walk ends, arriving along `into` (its last piece, in plan),
 *   the tangent point `Q` where the next walk begins, leaving along `out` (its first piece), the
 *   radius `r` and a segment count `n`, a power of two:
 *
 *   1. TURN. `turn` is 1 when `cross(into, out)` is positive, a left turn, and -1 when it is
 *      negative, a right one. Zero is refused: parallel pieces have no fillet.
 *   2. CENTRE. From each tangent point, by the grammar's own corner rule
 *      (`exulanica.grammar.grammars.city.document._corner_centre`, which `[corner_radius]` holds
 *      each corner to): `C = T + (floor(-turn * dy * r * S / L), floor(turn * dx * r * S / L))`,
 *      where `(dx, dy)` is that tangent point's piece, `S = 10^6` and
 *      `L = isqrt((dx * dx + dy * dy) * S * S)`. The grammar checks the two centres agree within
 *      2 mm on each axis. The arc's centre is their floored midpoint on each axis.
 *   3. POINTS. `arc[0] = P` and `arc[n] = Q`, exactly, so the arc meets both lines with no gap.
 *      Every other point halves a gap between two points already placed: between `arc[i]` and
 *      `arc[j]`, the point `arc[(i + j) / 2]` is `C` plus `r` along `u + v` by the same floored
 *      rule, `(floor(wx * r * S / L), floor(wy * r * S / L))` with `(wx, wy) = u + v` and
 *      `L = isqrt((wx * wx + wy * wy) * S * S)`, where `u` and `v` are the plan vectors from `C` to
 *      the two. Its height is `floor((z_i + z_j) / 2)`. Opposite points, where `u + v` is zero, are
 *      refused.
 *
 * The products outgrow a double, so the rule is evaluated in BigInt, which is exact on every
 * engine, and each result is refused unless it is a safe integer. A point depends only on the two
 * it halves, so the order the gaps are filled in cannot change the result.
 *
 * The segment count comes from the projection contract's `resolution_mm`, as the least power of two
 * whose every chord keeps within it (`filletSegmentsWithin`); nothing here chooses a number.
 *
 * Not yet wired into a bake. It changes no container until an expander calls it.
 */
import { add, crossVectors, dot, exact, floorDivide, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';

/** `document._CORNER_LENGTH_SCALE`: a piece's length is measured in millionths of a millimetre. */
const CORNER_LENGTH_SCALE = 1_000_000;

/** The floor of `a / b` in BigInt, for a positive `b`. */
function floorQuotient(a: bigint, b: bigint): bigint {
  const quotient = a / b;
  return a % b !== 0n && a < 0n ? quotient - 1n : quotient;
}

/** The floor square root of a non-negative BigInt, by Newton's method. */
function floorRoot(value: bigint): bigint {
  if (value < 2n) return value;
  let estimate = value;
  let better = (estimate + value / estimate) / 2n;
  while (better < estimate) {
    estimate = better;
    better = (estimate + value / estimate) / 2n;
  }
  return estimate;
}

/** A BigInt result as a number, refused unless a double holds it exactly. */
function safeNumber(value: bigint, where: string): number {
  return exact(Number(value), where);
}

/**
 * `distance` along `vector`, each component floored, measured as the grammar's corner rule
 * measures a piece: `floor(v * distance * S / isqrt(|v|^2 * S^2))`.
 */
export function alongByCornerRule(vector: Plan, distance: number, where: string): Plan {
  const [x, y] = [BigInt(exact(vector[0], where)), BigInt(exact(vector[1], where))];
  if (x === 0n && y === 0n) throw new GeometryError(`${where} measures along a zero vector`);
  const scale = BigInt(CORNER_LENGTH_SCALE);
  const length = floorRoot((x * x + y * y) * scale * scale);
  const reach = BigInt(exact(distance, where)) * scale;
  return [safeNumber(floorQuotient(x * reach, length), where), safeNumber(floorQuotient(y * reach, length), where)];
}

/** `document._corner_centre`: the tangent point plus the radius along its piece's normal toward the turn. */
export function cornerCentre(point: Plan, direction: Plan, radius: number, turn: 1 | -1, where: string): Plan {
  const normal: Plan = [exact(-turn * direction[1], where), exact(turn * direction[0], where)];
  const step = alongByCornerRule(normal, radius, where);
  return [add(point[0], step[0], where), add(point[1], step[1], where)];
}

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
  const cross = crossVectors(into, out, where);
  if (cross === 0) throw new GeometryError(`${where} joins parallel lines, which have no fillet`);
  const turn = cross > 0 ? 1 : -1;
  const fromP = cornerCentre(plan(p), into, radius, turn, where);
  const fromQ = cornerCentre(plan(q), out, radius, turn, where);
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
      const [x, y] = offset(centre, alongByCornerRule(toward, radius, where), where);
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
