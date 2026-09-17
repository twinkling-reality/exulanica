/**
 * THE TERRAIN YIELD RULE: TERRAIN IS NOT A SURFACE WHERE A DRAWN COVERING SURFACE COVERS IT.
 *
 * A covering is a triangle of a horizontal surface a record that covers the ground has drawn, in
 * plan. Terrain gives way to the union of the coverings in integers, and no terrain cell a covering
 * does not meet changes at all. The rule holds four claims, each tested exactly:
 *
 *   - NO GAP AT ALL. Every point of the patch that no covering's closed outline holds lies in some
 *     terrain triangle. This is stronger than any bound on a gap's size: there is none.
 *   - BOUNDED ENTRY. Every terrain point inside a covering lies within a millimetre of that
 *     covering's outline, on each axis.
 *   - WATERTIGHT BETWEEN CELLS. Where a covering edge crosses a line two cells share, both cells
 *     take the same integer vertices there, since rounding is decided by the point, not the cell.
 *   - HEIGHTS. Every vertex's height is the grammar's terrain surface there, floored.
 *
 * No gap and no entry cannot both be exact with integer vertices: two coverings can leave a channel
 * a millimetre square fits in whose integer points all lie on one line, so no terrain with area fits
 * inside it. The rule chooses no gap, and enters coverings by less than a millimetre. Where a
 * covering is higher or lower than the terrain the sliver is hidden under or behind it. Where they
 * are coplanar, a parcel at grade, it may flicker in a band under a pixel; that is known and not yet
 * measured, a runtime depth matter to measure once such a covering is drawn.
 *
 *   1. A cell is MET when its closed plan square and a closed covering triangle share a point. A
 *      cell no covering meets is drawn as the terrain grid draws it, and in the same order.
 *   2. A met cell is cut in PIECES that each lie on one plane of the terrain: the whole square when
 *      its two triangles are coplanar (`h_sw + h_ne = h_se + h_nw`), and otherwise the grid's two
 *      triangles, south-east of the diagonal from its south-west sample to its north-east one, then
 *      north-west of it.
 *   3. ROWS. The piece's rows are the heights `y` of the covering vertices that lie in the closed
 *      piece. The uncovered part of the piece turns inward only at a covering vertex, which is an
 *      integer point, so cut along those rows every FACE is convex.
 *   4. FACES. The piece less the union of the coverings, divided along its rows, is found exactly by
 *      the plan arrangement rule (`plan-arrangement.ts`); a face that is not convex is refused.
 *   5. Each face becomes the convex hull of the integer points `(floor or ceil x, floor or ceil y)`
 *      round each of its vertices that lie in the closed piece, keeping the points that lie along
 *      the hull's edges, cut into triangles by the ring rule. Each vertex of the face lies in the
 *      hull of the integer points round it that are in the piece, so the hull holds the face: no
 *      gap. Each of those points is within a millimetre on each axis of a vertex of the face, and
 *      the face is convex, so the hull lies within the face grown by a millimetre on each axis:
 *      bounded entry. A point where a covering edge crosses a cell side or a row takes the integer
 *      points on that line either side of it, the same from either side of the line.
 *   6. Each vertex's height is the piece's plane at it, floored: `floor` of the barycentric sum of
 *      the piece's corner heights, in BigInt.
 *
 * Met cells follow the untouched grid, in row-major order of cells, then pieces, then faces in the
 * arrangement's order.
 */
import { add, bigFloorQuotient, exact, floorDivide, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan, Space } from './integer-math.js';
import { sideOf, uncoveredRegions } from './plan-arrangement.js';
import { triangulateRing } from './ring-triangulation.js';
import type { RationalPoint } from './plan-arrangement.js';

/** A covering triangle in plan. */
export type CoveringTriangle = readonly [Plan, Plan, Plan];

/** A terrain grid: its south-west sample, its cell, its samples per side and their heights, row-major. */
export interface TerrainPatch {
  readonly originX: number;
  readonly originY: number;
  readonly cell: number;
  readonly side: number;
  readonly heights: readonly number[];
}

/** A met cell's terrain, its vertices absolute and its triangles indexing them. */
export interface CellTerrain {
  readonly vertices: readonly Space[];
  readonly triangles: readonly number[];
}

const twiceArea = (a: Plan, b: Plan, c: Plan, where: string): number =>
  subtract(
    multiply(subtract(b[0], a[0], where), subtract(c[1], a[1], where), where),
    multiply(subtract(b[1], a[1], where), subtract(c[0], a[0], where), where),
    where,
  );

/** The coverings with area, each turned counter-clockwise. */
export function coveringsWithArea(coverings: readonly CoveringTriangle[], where: string): CoveringTriangle[] {
  const out: CoveringTriangle[] = [];
  for (const [a, b, c] of coverings) {
    const area = twiceArea(a, b, c, where);
    if (area > 0) out.push([a, b, c]);
    if (area < 0) out.push([a, c, b]);
  }
  return out;
}

/** Whether a closed counter-clockwise triangle and a closed axis-aligned square share a point. */
function meetsSquare(triangle: CoveringTriangle, west: number, south: number, east: number, north: number, where: string): boolean {
  const xs = triangle.map((point) => point[0]);
  const ys = triangle.map((point) => point[1]);
  if (xs.every((x) => x < west)) return false;
  if (xs.every((x) => x > east)) return false;
  if (ys.every((y) => y < south)) return false;
  if (ys.every((y) => y > north)) return false;
  const corners: Plan[] = [[west, south], [east, south], [east, north], [west, north]];
  return !triangle.some((from, index) => {
    const to = triangle[(index + 1) % triangle.length]!;
    return corners.every((corner) => twiceArea(from, to, corner, where) < 0);
  });
}

/** Every met cell, as its row-major index among cells, with the coverings that meet it in order. */
export function metCells(patch: TerrainPatch, coverings: readonly CoveringTriangle[], where: string): Map<number, number[]> {
  const cells = patch.side - 1;
  const met = new Map<number, number[]>();
  coverings.forEach((triangle, index) => {
    const xs = triangle.map((point) => point[0]);
    const ys = triangle.map((point) => point[1]);
    const low = (values: number[]): number => values.reduce((a, b) => (a < b ? a : b));
    const high = (values: number[]): number => values.reduce((a, b) => (a > b ? a : b));
    const first = (value: number, origin: number): number => {
      const at = subtract(floorDivide(subtract(value, origin, where), patch.cell, where), 1, where);
      return at < 0 ? 0 : at;
    };
    const last = (value: number, origin: number): number => {
      const at = floorDivide(subtract(value, origin, where), patch.cell, where);
      return at > cells - 1 ? cells - 1 : at;
    };
    for (let row = first(low(ys), patch.originY); row <= last(high(ys), patch.originY); row += 1) {
      for (let column = first(low(xs), patch.originX); column <= last(high(xs), patch.originX); column += 1) {
        const west = add(patch.originX, multiply(column, patch.cell, where), where);
        const south = add(patch.originY, multiply(row, patch.cell, where), where);
        if (!meetsSquare(triangle, west, south, add(west, patch.cell, where), add(south, patch.cell, where), where)) continue;
        const key = row * cells + column;
        const list = met.get(key);
        if (list === undefined) met.set(key, [index]);
        else list.push(index);
      }
    }
  });
  return met;
}

/** The height at an integer plan point on the plane through three corners, floored. */
function heightOn(corners: readonly Space[], point: Plan, where: string): number {
  const [a, b, c] = corners as [Space, Space, Space];
  const plan = (space: Space): Plan => [space[0], space[1]];
  const whole = BigInt(twiceArea(plan(a), plan(b), plan(c), where));
  if (whole <= 0n) throw new GeometryError(`${where} takes heights from a piece of no area`);
  const weighted = BigInt(a[2]) * BigInt(twiceArea(point, plan(b), plan(c), where))
    + BigInt(b[2]) * BigInt(twiceArea(plan(a), point, plan(c), where))
    + BigInt(c[2]) * BigInt(twiceArea(plan(a), plan(b), point, where));
  return exact(Number(bigFloorQuotient(weighted, whole)), where);
}

/** A piece's rows, step 3: the distinct heights of the covering vertices in the closed piece, ascending. */
function rowsOf(piece: readonly Plan[], coverings: readonly CoveringTriangle[], where: string): number[] {
  const rows = new Set<number>();
  for (const triangle of coverings) {
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
function hullKeepingEdges(points: readonly Plan[], where: string): Plan[] {
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

/** A face's hull corners, step 5. */
function faceHull(face: readonly RationalPoint[], piece: readonly Plan[], where: string): Plan[] {
  const corners: Plan[] = [];
  for (const vertex of face) {
    const lowX = bigFloorQuotient(vertex.x, vertex.w);
    const lowY = bigFloorQuotient(vertex.y, vertex.w);
    const xs = lowX * vertex.w === vertex.x ? [lowX] : [lowX, lowX + 1n];
    const ys = lowY * vertex.w === vertex.y ? [lowY] : [lowY, lowY + 1n];
    for (const x of xs) {
      for (const y of ys) {
        const point: Plan = [exact(Number(x), where), exact(Number(y), where)];
        if (inPiece(piece, point, where)) corners.push(point);
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

/** A met cell's terrain, by the terrain yield rule. */
export function yieldedCell(
  patch: TerrainPatch,
  row: number,
  column: number,
  coverings: readonly CoveringTriangle[],
  where: string,
): CellTerrain {
  const west = add(patch.originX, multiply(column, patch.cell, where), where);
  const south = add(patch.originY, multiply(row, patch.cell, where), where);
  const [east, north] = [add(west, patch.cell, where), add(south, patch.cell, where)];
  const low = row * patch.side + column;
  const sample = (index: number, x: number, y: number): Space => [x, y, patch.heights[index]!];
  const sw = sample(low, west, south);
  const se = sample(low + 1, east, south);
  const ne = sample(low + patch.side + 1, east, north);
  const nw = sample(low + patch.side, west, north);
  const coplanar = add(sw[2], ne[2], where) === add(se[2], nw[2], where);
  const pieces: Space[][] = coplanar ? [[sw, se, ne, nw]] : [[sw, se, ne], [sw, ne, nw]];
  const vertices: Space[] = [];
  const triangles: number[] = [];
  for (const piece of pieces) {
    const ring: Plan[] = piece.map((corner) => [corner[0], corner[1]]);
    for (const region of uncoveredRegions(ring, coverings, rowsOf(ring, coverings, where), where)) {
      if (region.holes.length > 0) throw new GeometryError(`${where}: a face cut along its rows still holds a hole`);
      if (!convex(region.outer)) throw new GeometryError(`${where}: a face cut along its rows is not convex`);
      const hull = faceHull(region.outer, ring, where);
      if (hull.length < 3) continue;
      const first = vertices.length;
      for (const point of hull) vertices.push([point[0], point[1], heightOn(piece, point, where)]);
      for (const index of triangulateRing(hull, where)) triangles.push(first + index);
    }
  }
  return { vertices, triangles };
}
