/**
 * CARVING ONE CONVEX PIECE BY CONVEX OBSTRUCTIONS, IN INTEGERS.
 *
 * Two rules need the same cut: terrain yielding to the ground drawn records take, and support kept
 * clear of what obstructs a capsule. Both take a convex piece of a surface and a set of convex
 * obstructions, and both must answer in integer vertices, so both use this:
 *
 *   1. ROWS. The heights of the obstruction vertices that lie in the closed piece. The uncovered
 *      part of a piece turns inward only at such a vertex, so cut along those rows every FACE of it
 *      is convex.
 *   2. FACES. The piece less the union of the obstructions, divided along its rows, found exactly by
 *      the plan arrangement rule (`plan-arrangement.ts`). A face that is not convex is refused.
 *   3. HULLS. Each face becomes the convex hull of the integer points `(floor or ceil x, floor or
 *      ceil y)` round each of its vertices, keeping the points along the hull's edges so neighbours
 *      meet vertex to vertex.
 *
 * A hull HOLDS its face, so nothing uncovered is lost, and lies within its face grown by a
 * millimetre on each axis, so it enters an obstruction by no more than that. A rule that must not
 * enter its obstructions at all grows them by a millimetre before carving, and then the hulls stay
 * outside the obstructions themselves.
 *
 * HOLDING TO THE PIECE. A caller may keep only the points inside the closed piece. Terrain does,
 * because its pieces are cells whose sides cross every row at an integer point, so it loses nothing
 * by it and no cell's terrain reaches into the next. A surface with a sloping edge must not: a row
 * crosses such an edge between integer points, and holding to the piece would shave a sliver off
 * the edge itself. Where two triangles of one surface share that edge both would shave it, and the
 * crack between them is one a person would fall through.
 */
import { bigFloorQuotient, exact, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';
import { sideOf, uncoveredRegions } from './plan-arrangement.js';
import type { RationalPoint } from './plan-arrangement.js';

/** A convex obstruction in plan, counter-clockwise, as triangles. */
export type ObstructionTriangle = readonly [Plan, Plan, Plan];

export const twiceArea = (a: Plan, b: Plan, c: Plan, where: string): number =>
  subtract(
    multiply(subtract(b[0], a[0], where), subtract(c[1], a[1], where), where),
    multiply(subtract(b[1], a[1], where), subtract(c[0], a[0], where), where),
    where,
  );

/** The obstructions with area, each turned counter-clockwise. */
export function withArea(obstructions: readonly ObstructionTriangle[], where: string): ObstructionTriangle[] {
  const out: ObstructionTriangle[] = [];
  for (const [a, b, c] of obstructions) {
    const area = twiceArea(a, b, c, where);
    if (area > 0) out.push([a, b, c]);
    if (area < 0) out.push([a, c, b]);
  }
  return out;
}

/** The height at an integer plan point on the plane through a piece's first three corners, floored. */
export function heightOnPlane(corners: readonly Space[], point: Plan, where: string): number {
  const [a, b, c] = corners as [Space, Space, Space];
  const plan = (space: Space): Plan => [space[0], space[1]];
  const whole = BigInt(twiceArea(plan(a), plan(b), plan(c), where));
  if (whole <= 0n) throw new GeometryError(`${where} takes heights from a piece of no area`);
  const weighted = BigInt(a[2]) * BigInt(twiceArea(point, plan(b), plan(c), where))
    + BigInt(b[2]) * BigInt(twiceArea(plan(a), point, plan(c), where))
    + BigInt(c[2]) * BigInt(twiceArea(plan(a), plan(b), point, where));
  return exact(Number(bigFloorQuotient(weighted, whole)), where);
}

/** A piece's rows, step 1: the distinct heights of the obstruction vertices in the closed piece, ascending. */
function rowsOf(piece: readonly Plan[], obstructions: readonly ObstructionTriangle[], where: string): number[] {
  const rows = new Set<number>();
  for (const triangle of obstructions) {
    for (const point of triangle) {
      if (inPiece(piece, point, where)) rows.add(point[1]);
    }
  }
  return [...rows].sort((a, b) => a - b);
}

/** Whether an integer point lies in a closed counter-clockwise convex piece. */
function inPiece(piece: readonly Plan[], point: Plan, where: string): boolean {
  return piece.every((corner, index) => twiceArea(corner, piece[(index + 1) % piece.length]!, point, where) >= 0);
}

const lessPoint = (a: Plan, b: Plan): number => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]);

/**
 * The convex hull of integer points, counter-clockwise, keeping every point that lies along an edge
 * of it, so a neighbour that holds the same points on a shared line meets it vertex to vertex.
 */
export function hullKeepingEdges(points: readonly Plan[], where: string): Plan[] {
  const sorted = [...points].sort(lessPoint).filter((point, index, all) => index === 0 ? true : lessPoint(point, all[index - 1]!) !== 0);
  if (sorted.length < 3) return [];
  const chain = (ordered: readonly Plan[]): Plan[] => {
    const out: Plan[] = [];
    for (const point of ordered) {
      while (out.length >= 2 && twiceArea(out[out.length - 2]!, out[out.length - 1]!, point, where) < 0) out.pop();
      out.push(point);
    }
    return out;
  };
  const lower = chain(sorted);
  const upper = chain([...sorted].reverse());
  // With every point collinear the two chains are the same line: no hull with area.
  if (lower.length === sorted.length && upper.length === sorted.length) return [];
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** A face's hull corners, step 3, holding to the piece or not as the caller's rule needs. */
function faceHull(face: readonly RationalPoint[], piece: readonly Plan[], holdToPiece: boolean, where: string): Plan[] {
  const corners: Plan[] = [];
  for (const vertex of face) {
    const lowX = bigFloorQuotient(vertex.x, vertex.w);
    const lowY = bigFloorQuotient(vertex.y, vertex.w);
    const xs = lowX * vertex.w === vertex.x ? [lowX] : [lowX, lowX + 1n];
    const ys = lowY * vertex.w === vertex.y ? [lowY] : [lowY, lowY + 1n];
    for (const x of xs) {
      for (const y of ys) {
        const point: Plan = [exact(Number(x), where), exact(Number(y), where)];
        if (holdToPiece && !inPiece(piece, point, where)) continue;
        corners.push(point);
      }
    }
  }
  return hullKeepingEdges(corners, where);
}

/** Whether a face turns only left or straight on, as step 4 requires. */
function convex(face: readonly RationalPoint[]): boolean {
  return face.every((here, index) => {
    const before = face[(index + face.length - 1) % face.length]!;
    const after = face[(index + 1) % face.length]!;
    return sideOf(before, here, after) >= 0n;
  });
}

/**
 * The convex piece less the obstructions, as convex integer walks, by the rule above. Each walk
 * turns counter-clockwise and has area.
 */
export function carvedPiece(
  piece: readonly Plan[],
  obstructions: readonly ObstructionTriangle[],
  holdToPiece: boolean,
  where: string,
): Plan[][] {
  const walks: Plan[][] = [];
  for (const region of uncoveredRegions(piece, obstructions, rowsOf(piece, obstructions, where), where)) {
    if (region.holes.length > 0) throw new GeometryError(`${where}: a face cut along its rows still holds a hole`);
    if (!convex(region.outer)) throw new GeometryError(`${where}: a face cut along its rows is not convex`);
    const hull = faceHull(region.outer, piece, holdToPiece, where);
    if (hull.length >= 3) walks.push(hull);
  }
  return walks;
}
