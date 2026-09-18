/**
 * THE SEGMENTAL ARCH RULE: AN OPENING'S HEAD, FROM THREE POINTS, BY INTEGER CHORD BISECTION.
 *
 * The grammar states an arched head as a rise at the middle of the opening's width
 * (`exulanica.grammar.grammars.city.facade.OpeningGrid`): the two springings sit on the head line
 * at each side of the opening, and the crown sits `head_rise_mm` above that line, midway between
 * them. Three points, and a segmental arch is the circle through them.
 *
 * WHY THIS IS NOT THE FILLET RULE. A fillet is given two TANGENT DIRECTIONS and a radius, and finds
 * its centre from them. An arch is given no direction and no radius: it is given a third point, and
 * its radius follows from the three. Widening the fillet rule to take a point where it takes a
 * tangent would leave one rule with two ways of finding a centre, one of them used in one place.
 *
 * THE CIRCLE IS EXACT IN INTEGERS, in units of `8 * rise` of a millimetre. Writing `w` for the
 * opening's width, `rise` for the head's rise and `zh` for the head line's height, and measuring
 * `u` along the face's run and `z` above the city datum:
 *
 *     centre     (4 * rise * (uLeft + uRight),  8 * rise * zh - (w * w - 4 * rise * rise))
 *     radius      w * w + 4 * rise * rise
 *     springings  (plus or minus 4 * rise * w,  w * w - 4 * rise * rise)
 *     crown       (0, radius)
 *
 * Each of those is an integer, and the radius is exact rather than a square root, because
 * `(4 * rise * w)^2 + (w^2 - 4 * rise^2)^2` is `(w^2 + 4 * rise^2)^2` exactly. Divided by the scale
 * the radius is `(w^2 + 4 * rise^2) / (8 * rise)`, which is the segmental arch's own radius. The
 * centre plus the right springing is `8 * rise * uRight` and the centre plus the crown is
 * `8 * rise * (zh + rise)`, both exact, so the three points the record states are on the circle and
 * not near it.
 *
 * THE BISECTION halves a gap between two points already placed, exactly as the fillet rule does and
 * for the same reason: a point depends only on the two it halves, so the order the gaps are filled
 * in cannot change the result. Between the vectors `u` and `v` from the centre, the halving point is
 * the radius along `u + v`, placed by the grammar's own corner rule (`alongByCornerRule`).
 *
 * THE THREE POINTS SEED IT, which is what makes the rule need no tangent and also what makes it
 * safe: `arc[0]` is the right springing, `arc[segments]` the left, and `arc[segments / 2]` the
 * crown. So the first chord halved is a half of the arch rather than the whole of it, and a
 * semicircular head, whose springings are opposite points on the circle and have no halving point at
 * all, is drawn rather than refused.
 *
 * THE POINTS ARE HELD IN THE SCALED FRAME and floored to millimetres once, at the end, so the
 * bisection never compounds its own rounding. What a caller gets is a chord within the sagitta it
 * asked for plus the flooring of one millimetre on each axis, which is what `ARCH_ROUNDING_MM`
 * allows for, on the same reasoning the fillet rule's `CORNER_ROUNDING_MM` is there for: a criterion
 * that asks integer points to sit closer to a circle than integers can does not converge.
 */
import { alongByCornerRule } from './fillet-arc.js';
import { add, dot, exact, floorDivide, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';

/** A bound on how far inside its circle the flooring of a point to millimetres can place it. */
const ARCH_ROUNDING_MM = 2;

/**
 * The circle an arched head is a segment of, in units of `scale` of a millimetre: its centre and
 * radius, and the vector from that centre to the right-hand springing.
 */
export interface ArchCircle {
  /** `8 * rise`: the unit every other value here is measured in. */
  readonly scale: number;
  readonly centre: Plan;
  readonly radius: number;
  readonly springing: Plan;
}

/** Whether `count` is a power of two, and at least two, which is what three points seed. */
function isHalvableCount(count: number): boolean {
  if (!Number.isSafeInteger(count)) return false;
  if (count < 2) return false;
  let rest = count;
  while (rest > 1) {
    if (rest % 2 !== 0) return false;
    rest /= 2;
  }
  return true;
}

/**
 * The circle through an arched head's three points, by the rule above. `uLeft` and `uRight` are the
 * springings along the face's run, `headZ` the head line they sit on and `rise` the height of the
 * crown above it.
 */
export function archCircle(uLeft: number, uRight: number, headZ: number, rise: number, where: string): ArchCircle {
  const width = subtract(uRight, uLeft, where);
  if (width < 1) throw new GeometryError(`${where} has a head ${String(width)} mm wide, which is no span`);
  if (exact(rise, where) < 1) throw new GeometryError(`${where} has no rise, so its head is not an arch`);
  const twiceRise = multiply(rise, 2, where);
  // Past half the width the arc would pass outside the opening it heads, and the head would be
  // wider at its springing than the opening below it.
  if (twiceRise > width) {
    throw new GeometryError(`${where} rises ${String(rise)} mm over a head ${String(width)} mm wide, which passes half its width`);
  }
  const scale = multiply(multiply(twiceRise, 2, where), 2, where);
  const acrossSquared = multiply(width, width, where);
  const alongSquared = multiply(twiceRise, twiceRise, where);
  const radius = add(acrossSquared, alongSquared, where);
  const springing: Plan = [
    multiply(multiply(twiceRise, 2, where), width, where),
    subtract(acrossSquared, alongSquared, where),
  ];
  const centre: Plan = [
    multiply(multiply(twiceRise, 2, where), add(uLeft, uRight, where), where),
    subtract(multiply(scale, headZ, where), springing[1], where),
  ];
  return { scale, centre, radius, springing };
}

/**
 * The vectors from an arch's centre to its points, in the scaled frame, from the RIGHT springing to
 * the left, `segments + 1` of them. The direction is the one a counter-clockwise walk round the
 * opening takes along its head.
 */
export function archVectors(circle: ArchCircle, segments: number, where: string): Plan[] {
  if (!isHalvableCount(segments)) {
    throw new GeometryError(`${where} has ${String(segments)} segments, not a power of two of at least two`);
  }
  const half = floorDivide(segments, 2, where);
  const arc = new Array<Plan>(segments + 1);
  arc[0] = circle.springing;
  arc[segments] = [subtract(0, circle.springing[0], where), circle.springing[1]];
  arc[half] = [0, circle.radius];
  for (let gap = half; gap > 1; gap /= 2) {
    for (let start = 0; start < segments; start += gap) {
      const first = arc[start]!;
      const last = arc[start + gap]!;
      const toward: Plan = [add(first[0], last[0], where), add(first[1], last[1], where)];
      if (toward[0] === 0 && toward[1] === 0) {
        throw new GeometryError(`${where} halves a chord between opposite points`);
      }
      arc[start + gap / 2] = alongByCornerRule(toward, circle.radius, where);
    }
  }
  return arc;
}

/** An arch's points in the face's own `(u, z)` millimetres, from the right springing to the left. */
export function archPoints(circle: ArchCircle, segments: number, where: string): Plan[] {
  return archVectors(circle, segments, where).map((vector): Plan => [
    floorDivide(add(circle.centre[0], vector[0], where), circle.scale, where),
    floorDivide(add(circle.centre[1], vector[1], where), circle.scale, where),
  ]);
}

/** The arch's radius in whole millimetres, which is what bounds how finely it is worth cutting. */
export function archRadiusMm(circle: ArchCircle, where: string): number {
  return floorDivide(circle.radius, circle.scale, where);
}

/**
 * The power of two an arch's segments may not pass: the least one at or above its radius in
 * millimetres, which is the bound the fillet rule takes for a corner (`streets.segmentBound`).
 */
export function archSegmentBound(circle: ArchCircle, where: string): number {
  const radius = archRadiusMm(circle, where);
  let bound = 2;
  while (bound < radius) bound *= 2;
  return bound;
}

/** Twice the vector from a circle's centre to the midpoint of the chord between two of its points. */
function chordReach(circle: ArchCircle, first: Plan, second: Plan, where: string): Plan {
  const axis = (index: 0 | 1): number => subtract(
    multiply(circle.scale, add(first[index], second[index], where), where),
    multiply(circle.centre[index], 2, where),
    where,
  );
  return [axis(0), axis(1)];
}

/**
 * The least power of two, up to `maximumSegments`, for which every chord of the arch keeps within
 * `maximumSagittaMm` of its circle: each chord's midpoint lies at least the radius less that sagitta
 * from the centre, which `4 * reach^2 <= |u + v|^2` states exactly over the chord's two vectors from
 * the centre.
 *
 * IT IS MEASURED ON THE POINTS THE RULE EMITS, in millimetres, and not on the exact scaled ones the
 * bisection holds. That is the whole point of the allowance: those points are floored onto the
 * millimetre lattice, so each sits up to the diagonal of a millimetre inside its circle and a
 * criterion asking them to sit closer than integers can does not converge. Measuring the exact
 * points instead would be an allowance made for a rounding that had not happened yet, and the
 * flooring's own error would then land on top of the tolerance rather than inside it, which is how
 * this was found: a half round head came out 3.33 mm from its circle under a rule claiming 3.
 */
export function archSegmentsWithin(
  circle: ArchCircle,
  maximumSagittaMm: number,
  maximumSegments: number,
  where: string,
): number {
  if (!isHalvableCount(maximumSegments)) {
    throw new GeometryError(`${where} has a segment maximum that is not a power of two of at least two`);
  }
  if (!Number.isSafeInteger(maximumSagittaMm)) throw new GeometryError(`${where} has a sagitta that is not an integer`);
  if (maximumSagittaMm < 0) throw new GeometryError(`${where} has a negative sagitta`);
  const allowance = multiply(circle.scale, add(maximumSagittaMm, ARCH_ROUNDING_MM, where), where);
  const reach = subtract(circle.radius, allowance, where);
  // A sagitta as large as the radius admits any chord short of a half circle, and three points
  // never span more than one.
  if (reach <= 0) return 2;
  const doubledReach = multiply(reach, 2, where);
  const least = multiply(doubledReach, doubledReach, where);
  for (let segments = 2; segments <= maximumSegments; segments *= 2) {
    const arc = archPoints(circle, segments, where);
    const within = arc.slice(1).every((point, index) => {
      const sum = chordReach(circle, arc[index]!, point, where);
      return dot(sum, sum, where) >= least;
    });
    if (within) return segments;
  }
  throw new GeometryError(`${where} needs more than ${String(maximumSegments)} segments to keep within ${String(maximumSagittaMm)} mm`);
}

/**
 * An arched head's points in the face's `(u, z)` millimetres, cut as finely as the projection's
 * resolution asks and no finer, from the right springing to the left.
 */
export function archHead(
  uLeft: number,
  uRight: number,
  headZ: number,
  rise: number,
  resolutionMm: number,
  where: string,
): Plan[] {
  const circle = archCircle(uLeft, uRight, headZ, rise, where);
  const segments = archSegmentsWithin(circle, resolutionMm, archSegmentBound(circle, where), where);
  const points = archPoints(circle, segments, where);
  points.forEach((point, index) => {
    if (index === 0) return;
    const before = points[index - 1]!;
    if (before[0] === point[0] && before[1] === point[1]) {
      throw new GeometryError(`${where} cuts an arch into chords whose ends meet at one millimetre point`);
    }
  });
  return points;
}
