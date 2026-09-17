/**
 * THE SUPPORT CLEARANCE RULE: SUPPORT SURFACES CARVED AWAY FROM OBSTRUCTIONS, CONSERVATIVELY.
 *
 * A support triangle may be claimed only where a capsule stood on it keeps clear of every
 * obstruction. An obstruction is a record's stated plan extent, which contains everything the
 * record generates, grown by the capsule radius on every side. This rule removes from support
 * every point inside or on a grown box, in integers, and rounds only ever inward, so no point it
 * keeps lies within the radius of an obstruction or outside the support it was given:
 *
 *   1. With a grown box `[min_x, max_x] x [min_y, max_y]`, the removed region is the open box
 *      `(min_x - 1, max_x + 1) x (min_y - 1, max_y + 1)`, which holds the closed grown box and is
 *      the least open box on integer lines that does. A support triangle is a convex polygon.
 *      Removing that open box from it leaves at most four convex polygons that meet only along
 *      shared lines, so no crack opens between them: the part left of the box (`x <= min_x - 1`),
 *      right of it (`x >= max_x + 1`), and, between those lines, below it (`y <= min_y - 1`) and
 *      above it (`y >= max_y + 1`). Each is the polygon clipped by axis-aligned half-planes. A
 *      polygon the open box does not meet, by its plan bounds or by one of its own edges, is kept
 *      whole.
 *   2. A clip adds the points where the polygon's edges cross the clip line, which are rational. On
 *      the line, the polygon's crossing is an interval; its lower end is rounded up and its upper
 *      end down, to integers, so the kept polygon lies inside the one it was cut from. An interval
 *      that holds no integer contributes no point, and one that holds a single integer one point.
 *   3. A new point's height is on its source triangle's plane: `floor` of the barycentric sum of
 *      the corners' heights, weighted by twice areas, in BigInt.
 *   4. Boxes are removed one after another, in the order given. A polygon of no area is dropped.
 *      What remains is cut into triangles as a fan from its first vertex, dropping any of no area;
 *      every triangle returned turns counter-clockwise in plan.
 *
 * Rounding inward can leave slivers under a millimetre with no support claimed, along the support's
 * edges and along an edge two support triangles share where a clip line crosses it. That is the
 * conservative side: nothing unwalkable is claimed walkable.
 *
 * Not yet wired into a bake. Which record kinds obstruct is declared data the city descriptor will
 * state per kind; this rule takes the boxes it is given.
 */
import { add, bigFloorQuotient, exact, floorDivide, GeometryError, multiply, subtract } from './integer-math.js';
import type { Space } from './integer-math.js';

/** A closed plan box: a record's stated extent in plan. */
export interface ClearanceBox {
  readonly min_x: number;
  readonly min_y: number;
  readonly max_x: number;
  readonly max_y: number;
}

export type SupportTriangle = readonly [Space, Space, Space];

/** A convex polygon being cut, with the triangle its heights come from. */
interface Polygon {
  readonly points: readonly Space[];
  readonly source: SupportTriangle;
}

const twiceArea = (a: Space, b: Space, c: Space, where: string): number =>
  subtract(
    multiply(subtract(b[0], a[0], where), subtract(c[1], a[1], where), where),
    multiply(subtract(b[1], a[1], where), subtract(c[0], a[0], where), where),
    where,
  );

/** The height at an integer plan point on the source triangle's plane, floored. */
function heightAt(source: SupportTriangle, x: number, y: number, where: string): number {
  const [a, b, c] = source;
  const point: Space = [x, y, 0];
  const whole = BigInt(twiceArea(a, b, c, where));
  if (whole === 0n) throw new GeometryError(`${where} carves a support triangle of no area`);
  const weighted = BigInt(a[2]) * BigInt(twiceArea(point, b, c, where))
    + BigInt(b[2]) * BigInt(twiceArea(a, point, c, where))
    + BigInt(c[2]) * BigInt(twiceArea(a, b, point, where));
  return whole > 0n
    ? exact(Number(bigFloorQuotient(weighted, whole)), where)
    : exact(Number(bigFloorQuotient(-weighted, -whole)), where);
}

/** Which half-plane a clip keeps: `axis <= bound` (below) or `axis >= bound` (above). */
interface HalfPlane {
  readonly axis: 0 | 1;
  readonly bound: number;
  readonly keep: 'below' | 'above';
}

const inside = (point: Space, plane: HalfPlane): boolean =>
  plane.keep === 'below' ? point[plane.axis] <= plane.bound : point[plane.axis] >= plane.bound;

/** A rational crossing of an edge with a clip line, on the line's other axis: `numerator / denominator`. */
interface Crossing {
  readonly numerator: number;
  readonly denominator: number;
  readonly index: number;
}

/** Clip a convex polygon by one axis-aligned half-plane, rounding the crossings inward. */
function clip(polygon: Polygon, plane: HalfPlane, where: string): Polygon | undefined {
  const points = polygon.points;
  const other = plane.axis === 0 ? 1 : 0;
  const kept: (Space | Crossing)[] = [];
  points.forEach((here, index) => {
    const next = points[(index + 1) % points.length]!;
    const hereIn = inside(here, plane);
    const nextIn = inside(next, plane);
    if (hereIn) kept.push(here);
    if (hereIn !== nextIn) {
      // other = here + (next - here) * (bound - here[axis]) / (next[axis] - here[axis])
      const span = subtract(next[plane.axis], here[plane.axis], where);
      const reach = subtract(plane.bound, here[plane.axis], where);
      const numerator = add(multiply(here[other], span, where), multiply(subtract(next[other], here[other], where), reach, where), where);
      kept.push(span < 0 ? { numerator: -numerator, denominator: -span, index: kept.length } : { numerator, denominator: span, index: kept.length });
    }
  });
  const crossings = kept.filter((item): item is Crossing => !Array.isArray(item));
  if (kept.length === 0) return undefined;
  const rounded = new Map<number, number>();
  if (crossings.length === 2) {
    const [first, second] = crossings as [Crossing, Crossing];
    const firstLower = multiply(first.numerator, second.denominator, where) <= multiply(second.numerator, first.denominator, where);
    const [lower, upper] = firstLower ? [first, second] : [second, first];
    const up = subtract(0, floorDivide(-lower.numerator, lower.denominator, where), where);
    const down = floorDivide(upper.numerator, upper.denominator, where);
    if (up < down) {
      rounded.set(lower.index, up);
      rounded.set(upper.index, down);
    } else if (up === down) {
      rounded.set(lower.index, up);
    }
  } else if (crossings.length !== 0) {
    throw new GeometryError(`${where} clipped a polygon that is not convex`);
  }
  const out: Space[] = [];
  kept.forEach((item, index) => {
    if (Array.isArray(item)) {
      out.push(item as Space);
      return;
    }
    const along = rounded.get(index);
    if (along === undefined) return;
    const [x, y] = plane.axis === 0 ? [plane.bound, along] : [along, plane.bound];
    out.push([x, y, heightAt(polygon.source, x, y, where)]);
  });
  if (out.length < 3) return undefined;
  return { points: out, source: polygon.source };
}

/** Twice the signed area of a polygon. */
function polygonTwiceArea(points: readonly Space[], where: string): number {
  let total = 0;
  for (let index = 1; index + 1 < points.length; index += 1) {
    total = add(total, twiceArea(points[0]!, points[index]!, points[index + 1]!, where), where);
  }
  return total;
}

function clippedBy(polygon: Polygon, planes: readonly HalfPlane[], where: string): Polygon | undefined {
  let current: Polygon | undefined = polygon;
  for (const plane of planes) {
    if (current === undefined) return undefined;
    current = clip(current, plane, where);
  }
  if (current === undefined) return undefined;
  return polygonTwiceArea(current.points, where) > 0 ? current : undefined;
}

/** The open box `(left, right) x (below, above)` a clip removes. */
interface OpenBox {
  readonly left: number;
  readonly right: number;
  readonly below: number;
  readonly above: number;
}

/**
 * Whether a counter-clockwise convex polygon meets an open box. They are apart when the polygon's
 * plan bounds keep off the box, or when every corner of the box is on or right of the line through
 * one of the polygon's edges; an edge of no length separates nothing.
 */
function meets(polygon: Polygon, box: OpenBox, where: string): boolean {
  const points = polygon.points;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  if (xs.every((x) => x <= box.left)) return false;
  if (xs.every((x) => x >= box.right)) return false;
  if (ys.every((y) => y <= box.below)) return false;
  if (ys.every((y) => y >= box.above)) return false;
  const corners: Space[] = [
    [box.left, box.below, 0],
    [box.right, box.below, 0],
    [box.right, box.above, 0],
    [box.left, box.above, 0],
  ];
  const separated = points.some((here, index) => {
    const next = points[(index + 1) % points.length]!;
    if (here[0] === next[0] && here[1] === next[1]) return false;
    return corners.every((corner) => twiceArea(here, next, corner, where) <= 0);
  });
  return !separated;
}

/** The support triangles less every obstruction grown by `radius`, by the support clearance rule. */
export function carveSupport(
  triangles: readonly SupportTriangle[],
  obstructions: readonly ClearanceBox[],
  radius: number,
  where: string,
): SupportTriangle[] {
  if (exact(radius, where) < 0) throw new GeometryError(`${where} grows obstructions by ${String(radius)}, which is negative`);
  let polygons: Polygon[] = triangles
    .filter((triangle) => twiceArea(...triangle, where) !== 0)
    .map((triangle) => ({ points: twiceArea(...triangle, where) > 0 ? triangle : [triangle[0], triangle[2], triangle[1]], source: triangle }));
  for (const obstruction of obstructions) {
    if (obstruction.min_x > obstruction.max_x) throw new GeometryError(`${where} has an obstruction whose min_x passes its max_x`);
    if (obstruction.min_y > obstruction.max_y) throw new GeometryError(`${where} has an obstruction whose min_y passes its max_y`);
    const box: OpenBox = {
      left: subtract(subtract(obstruction.min_x, radius, where), 1, where),
      right: add(add(obstruction.max_x, radius, where), 1, where),
      below: subtract(subtract(obstruction.min_y, radius, where), 1, where),
      above: add(add(obstruction.max_y, radius, where), 1, where),
    };
    const between: HalfPlane[] = [{ axis: 0, bound: box.left, keep: 'above' }, { axis: 0, bound: box.right, keep: 'below' }];
    polygons = polygons.flatMap((polygon) => {
      if (!meets(polygon, box, where)) return [polygon];
      const parts = [
        clippedBy(polygon, [{ axis: 0, bound: box.left, keep: 'below' }], where),
        clippedBy(polygon, [{ axis: 0, bound: box.right, keep: 'above' }], where),
        clippedBy(polygon, [...between, { axis: 1, bound: box.below, keep: 'below' }], where),
        clippedBy(polygon, [...between, { axis: 1, bound: box.above, keep: 'above' }], where),
      ];
      return parts.filter((part): part is Polygon => part !== undefined);
    });
  }
  const out: SupportTriangle[] = [];
  for (const polygon of polygons) {
    const points = polygon.points;
    for (let index = 1; index + 1 < points.length; index += 1) {
      const triangle: SupportTriangle = [points[0]!, points[index]!, points[index + 1]!];
      if (twiceArea(...triangle, where) > 0) out.push(triangle);
    }
  }
  return out;
}
