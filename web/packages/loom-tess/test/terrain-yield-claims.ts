/**
 * The terrain yield rule's four claims, as arithmetic of the tests' own, for small patches where the
 * half millimetre can be walked. `terrain-yield.test.ts` holds its cases to them:
 *
 *   - no gap at all: every point of the patch that no covering's closed outline holds, on the
 *     half-millimetre lattice and at seeded points between, lies in a terrain triangle;
 *   - bounded entry: no terrain triangle meets the part of a covering more than a millimetre from its
 *     outline on each axis, which is the covering's inside shrunk by a millimetre square;
 *   - watertight between cells: where a covering edge crosses a side two cells share, and the
 *     crossing bounds uncovered ground, both cells hold the integer points on that side either side
 *     of it;
 *   - every terrain vertex's height is the grammar's surface there, floored: the cell's south-east or
 *     north-west plane, split along its south-west to north-east diagonal.
 *
 * And a patch no covering meets is the grid, unchanged. The shrunk coverings' corners are rational
 * and are compared in BigInt; everything else stays small enough for plain numbers to be exact.
 */
import type { Plan, Space } from '../src/core/integer-math.js';
import { coveringsWithArea, metCells, yieldedCell } from '../src/core/terrain-yield.js';
import type { CoveringTriangle, TerrainPatch } from '../src/core/terrain-yield.js';

/** A small deterministic generator, for property cases: never a source of shipped geometry. */
export function sequence(seed: number): () => number {
  let state = BigInt(seed);
  return () => {
    state = (state * 6364136223846793005n + 1442695040888963407n) % 18446744073709551616n;
    return Number(state >> 33n);
  };
}

export type Triangle = readonly [Plan, Plan, Plan];

export const twice = (a: Plan, b: Plan, c: Plan): number => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
export const leftTurning = (t: Triangle): Triangle => (twice(...t) >= 0 ? t : [t[0], t[2], t[1]]);

/**
 * Whether the point `(x / scale, y / scale)` lies in a closed triangle. The products stay far below
 * 2^53 for the coordinates and scales these tests use, so plain numbers are exact; the check refuses
 * any that would not be.
 */
function holdsScaled(triangle: Triangle, x: number, y: number, scale: number): boolean {
  const xs = triangle.map((point) => point[0] * scale);
  const ys = triangle.map((point) => point[1] * scale);
  if (x < Math.min(...xs) || x > Math.max(...xs) || y < Math.min(...ys) || y > Math.max(...ys)) return false;
  const [a, b, c] = leftTurning(triangle);
  const side = (p: Plan, q: Plan): number => {
    const value = (q[0] - p[0]) * (y - p[1] * scale) - (q[1] - p[1]) * (x - p[0] * scale);
    if (!Number.isSafeInteger(value)) throw new Error('a containment test past the integers a double holds');
    return value;
  };
  return side(a, b) >= 0 && side(b, c) >= 0 && side(c, a) >= 0;
}

/**
 * Whether a closed terrain triangle meets the open set of points inside a covering by more than a
 * millimetre on each axis. Along each counter-clockwise edge with outward normal `(a, b)` that set
 * is `a x + b y < c - |a| - |b|`. The two are apart when one such half-plane holds no corner of the
 * terrain triangle, when the three half-planes hold no point in common, or when one edge of the
 * terrain triangle has every corner of the shrunk covering on or outside it.
 */
function entersDeeply(terrain: Triangle, covering: Triangle): boolean {
  const [p, q, r] = leftTurning(covering);
  const lines = ([[p, q], [q, r], [r, p]] as [Plan, Plan][]).map(([from, to]) => {
    const [a, b] = [BigInt(to[1] - from[1]), BigInt(from[0] - to[0])];
    const size = (a < 0n ? -a : a) + (b < 0n ? -b : b);
    return { a, b, c: a * BigInt(from[0]) + b * BigInt(from[1]) - size };
  });
  const big = (point: Plan): [bigint, bigint] => [BigInt(point[0]), BigInt(point[1])];
  if (lines.some((line) => terrain.every((point) => line.a * big(point)[0] + line.b * big(point)[1] >= line.c))) return false;
  // The shrunk covering's corners, where consecutive lines meet: (x / w, y / w) with w positive.
  const corners = lines.map((line, index) => {
    const before = lines[(index + 2) % 3]!;
    const w = before.a * line.b - line.a * before.b;
    const x = before.c * line.b - line.c * before.b;
    const y = before.a * line.c - line.a * before.c;
    return w < 0n ? { x: -x, y: -y, w: -w } : { x, y, w };
  });
  if (corners.some((corner) => corner.w === 0n)) return false;
  // Past the covering's inradius the shifted lines meet in a flipped copy, which has the same turn;
  // the shrunk covering holds a point exactly when each corner is strictly inside the third line.
  const holdsPoint = corners.every((corner, index) => {
    const third = lines[(index + 1) % 3]!;
    return third.a * corner.x + third.b * corner.y < third.c * corner.w;
  });
  if (!holdsPoint) return false;
  const [a, b, c] = leftTurning(terrain);
  return !([[a, b], [b, c], [c, a]] as [Plan, Plan][]).some(([from, to]) => corners.every((corner) =>
    BigInt(to[0] - from[0]) * (corner.y - BigInt(from[1]) * corner.w) - BigInt(to[1] - from[1]) * (corner.x - BigInt(from[0]) * corner.w) <= 0n));
}

/** The grammar's terrain surface at a point, floored, from this test's own reading of the grid. */
function surfaceHeight(patch: TerrainPatch, point: Plan): number {
  const cells = patch.side - 1;
  const clamp = (value: number): number => (value < 0 ? 0 : value > cells - 1 ? cells - 1 : value);
  const column = clamp(Math.floor((point[0] - patch.originX) / patch.cell));
  const row = clamp(Math.floor((point[1] - patch.originY) / patch.cell));
  const west = patch.originX + column * patch.cell;
  const south = patch.originY + row * patch.cell;
  const at = (dc: number, dr: number): Space => [west + dc * patch.cell, south + dr * patch.cell, patch.heights[(row + dr) * patch.side + column + dc]!];
  const [sw, se, ne, nw] = [at(0, 0), at(1, 0), at(1, 1), at(0, 1)];
  const [a, b, c] = point[0] - west >= point[1] - south ? [sw, se, ne] : [sw, ne, nw];
  const plan = (s: Space): Plan => [s[0], s[1]];
  const whole = BigInt(twice(plan(a), plan(b), plan(c)));
  const weighted = BigInt(a[2]) * BigInt(twice(point, plan(b), plan(c)))
    + BigInt(b[2]) * BigInt(twice(plan(a), point, plan(c)))
    + BigInt(c[2]) * BigInt(twice(plan(a), plan(b), point));
  const quotient = weighted / whole;
  return Number(weighted % whole !== 0n && (weighted < 0n) !== (whole < 0n) ? quotient - 1n : quotient);
}

interface Yielded {
  readonly triangles: Triangle[];
  readonly vertices: Space[];
  /** Each cell's vertices, by row-major cell index. */
  readonly byCell: Map<number, Space[]>;
}

/** The whole yielded patch: the grid's untouched cells, and each met cell by the rule. */
function yielded(patch: TerrainPatch, stated: readonly CoveringTriangle[]): Yielded {
  const coverings = coveringsWithArea(stated, 'case');
  const met = metCells(patch, coverings, 'case');
  const triangles: Triangle[] = [];
  const vertices: Space[] = [];
  const byCell = new Map<number, Space[]>();
  const cells = patch.side - 1;
  for (let row = 0; row < cells; row += 1) {
    for (let column = 0; column < cells; column += 1) {
      const key = row * cells + column;
      const list = met.get(key);
      if (list === undefined) {
        const low = row * patch.side + column;
        const at = (index: number, dc: number, dr: number): Space => [patch.originX + (column + dc) * patch.cell, patch.originY + (row + dr) * patch.cell, patch.heights[index]!];
        const [sw, se, ne, nw] = [at(low, 0, 0), at(low + 1, 1, 0), at(low + patch.side + 1, 1, 1), at(low + patch.side, 0, 1)];
        triangles.push([[sw[0], sw[1]], [se[0], se[1]], [ne[0], ne[1]]], [[sw[0], sw[1]], [ne[0], ne[1]], [nw[0], nw[1]]]);
        vertices.push(sw, se, ne, nw);
        byCell.set(key, [sw, se, ne, nw]);
        continue;
      }
      const cell = yieldedCell(patch, row, column, list.map((index) => coverings[index]!), 'case');
      for (let corner = 0; corner < cell.triangles.length; corner += 3) {
        const p = (index: number): Plan => [cell.vertices[index]![0], cell.vertices[index]![1]];
        triangles.push([p(cell.triangles[corner]!), p(cell.triangles[corner + 1]!), p(cell.triangles[corner + 2]!)]);
      }
      vertices.push(...cell.vertices);
      byCell.set(key, [...cell.vertices]);
    }
  }
  return { triangles, vertices, byCell };
}

/** Every claim of the rule, for one patch and its coverings, with `samples` seeded rational points. */
/** How many shared-side crossings each call to `holdsTheRule` checked, for tests that need some. */
export const crossingsChecked: number[] = [];

export function holdsTheRule(patch: TerrainPatch, stated: readonly CoveringTriangle[], samples: number): Yielded {
  const result = yielded(patch, stated);
  const coverings = stated.filter((covering) => twice(...covering) !== 0);
  const where = (label: string): string => `${label}, with coverings ${JSON.stringify(stated)} and heights ${JSON.stringify(patch.heights)}`;

  for (const triangle of result.triangles) {
    if (twice(...triangle) <= 0) throw new Error(where(`${JSON.stringify(triangle)} does not turn counter-clockwise with area`));
    for (const covering of coverings) {
      if (entersDeeply(triangle, covering)) throw new Error(where(`${JSON.stringify(triangle)} enters ${JSON.stringify(covering)} by more than a millimetre`));
    }
  }
  for (const vertex of result.vertices) {
    if (vertex[2] !== surfaceHeight(patch, [vertex[0], vertex[1]])) throw new Error(where(`${JSON.stringify(vertex)} is off the terrain surface`));
  }

  const span = (patch.side - 1) * patch.cell;
  const uncovered = (x: number, y: number, scale: number): boolean => !coverings.some((covering) => holdsScaled(covering, x, y, scale));
  const onTerrain = (x: number, y: number, scale: number): boolean => result.triangles.some((triangle) => holdsScaled(triangle, x, y, scale));
  const check = (x: number, y: number, scale: number): void => {
    if (uncovered(x, y, scale) && !onTerrain(x, y, scale)) {
      throw new Error(where(`the point (${x}/${scale}, ${y}/${scale}) is neither covered nor on terrain`));
    }
  };
  for (let y = 0; y <= 2 * span; y += 1) {
    for (let x = 0; x <= 2 * span; x += 1) check(patch.originX * 2 + x, patch.originY * 2 + y, 2);
  }
  const next = sequence(span + stated.length);
  for (let sample = 0; sample < samples; sample += 1) {
    check(patch.originX * 97 + (next() % (span * 97 + 1)), patch.originY * 97 + (next() % (span * 97 + 1)), 97);
  }

  // Watertight: each covering edge crossing a side two cells share, where the crossing bounds uncovered ground.
  const cells = patch.side - 1;
  let checked = 0;
  for (const covering of coverings) {
    for (const [from, to] of [[covering[0], covering[1]], [covering[1], covering[2]], [covering[2], covering[0]]] as [Plan, Plan][]) {
      for (let line = 1; line < cells; line += 1) {
        for (const axis of [0, 1] as const) {
          const other = axis === 0 ? 1 : 0;
          const at = (axis === 0 ? patch.originX : patch.originY) + line * patch.cell;
          const [u, v] = [from[axis] - at, to[axis] - at];
          if (u === 0 || v === 0 || (u < 0) === (v < 0)) continue;
          // The crossing along the other axis is numerator / denominator.
          let numerator = from[other] * (v - u) - (to[other] - from[other]) * u;
          let denominator = v - u;
          if (denominator < 0) [numerator, denominator] = [-numerator, -denominator];
          if (numerator % denominator === 0) continue;
          const low = Math.floor(numerator / denominator);
          const origin = axis === 0 ? patch.originY : patch.originX;
          if (low < origin || low + 1 > origin + span) continue;
          // The crossing bounds uncovered ground when a point a thousandth of its denominator along
          // the line, to either side, is uncovered.
          const beside = [-1, 1].some((step) => {
            const scale = 1000 * denominator;
            const [bx, by] = axis === 0 ? [at * scale, 1000 * numerator + step] : [1000 * numerator + step, at * scale];
            return uncovered(bx, by, scale);
          });
          if (!beside) continue;
          checked += 1;
          const across = Math.floor((low - origin) / patch.cell);
          const keys = axis === 0
            ? [across * cells + line - 1, across * cells + line]
            : [(line - 1) * cells + across, line * cells + across];
          for (const key of keys) {
            const held = (result.byCell.get(key) ?? []).filter((point) => point[axis] === at).map((point) => point[other]);
            if (!(held.includes(low) && held.includes(low + 1))) {
              throw new Error(where(`cell ${key} does not hold ${low} and ${low + 1} on the line ${axis === 0 ? 'x' : 'y'} = ${at}`));
            }
          }
        }
      }
    }
  }
  crossingsChecked.push(checked);
  return result;
}

export const flat = (side: number): number[] => new Array<number>(side * side).fill(0);

/** A quad as its two triangles, `a b c` and `a c d`. */
export const quad = (a: Plan, b: Plan, c: Plan, d: Plan): CoveringTriangle[] => [[a, b, c], [a, c, d]];

/** A strip from one point to another, about `width` across, as two triangles, or none without width. */
function strip(from: Plan, to: Plan, width: number): CoveringTriangle[] {
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
  if (dx === 0 && dy === 0) return [];
  const length = Math.hypot(dx, dy);
  const [nx, ny] = [Math.round((-dy / length) * width), Math.round((dx / length) * width)];
  if (nx === 0 && ny === 0) return [];
  return quad(from, to, [to[0] + nx, to[1] + ny], [from[0] + nx, from[1] + ny]);
}

/** Whether the interiors of two triangles share a point. */
function interiorsMeet(first: Triangle, second: Triangle): boolean {
  const [a, b] = [leftTurning(first), leftTurning(second)];
  const apart = (edges: Triangle, points: Triangle): boolean =>
    edges.some((from, index) => points.every((point) => twice(from, edges[(index + 1) % 3]!, point) <= 0));
  return !apart(a, b) && !apart(b, a);
}

/** Seeded coverings: strips that meet but never overlap, or overlapping strips and loose triangles. */
export function seededCoverings(within: (range: number) => number, overlapping: boolean): CoveringTriangle[] {
  const coverings: CoveringTriangle[] = [];
  if (overlapping) {
    for (let count = 0; count < 1 + within(5); count += 1) {
      if (within(3) === 0) {
        coverings.push([[within(40) - 4, within(40) - 4], [within(40) - 4, within(40) - 4], [within(40) - 4, within(40) - 4]]);
      } else {
        coverings.push(...strip([within(41) - 4, within(41) - 4], [within(41) - 4, within(41) - 4], 1 + within(6)));
      }
    }
    return coverings;
  }
  for (let attempt = 0; attempt < 12 && coverings.length < 12; attempt += 1) {
    const candidate = coveringsWithArea(strip([within(41) - 4, within(41) - 4], [within(41) - 4, within(41) - 4], 2 + within(6)), 'case');
    if (!candidate.some((t) => coverings.some((c) => interiorsMeet(t, c)))) coverings.push(...candidate);
  }
  return coverings;
}
