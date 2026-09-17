/**
 * The support clearance rule, held to what it claims before any bake calls it: no point it keeps is
 * on or inside an obstruction grown by the radius, every point it keeps is inside the support it
 * was given and on that support's plane rounded down, the pieces it keeps meet without cracks, and
 * what it loses to rounding lies within a few millimetres of a line it cut along. Each check here
 * is its own exact arithmetic in BigInt, not the rule's.
 */
import { describe, expect, it } from 'vitest';
import { GeometryError } from '../src/core/integer-math.js';
import type { Space } from '../src/core/integer-math.js';
import { carveSupport } from '../src/core/support-clearance.js';
import type { ClearanceBox, SupportTriangle } from '../src/core/support-clearance.js';

/** A small deterministic generator, for property cases: never a source of shipped geometry. */
function sequence(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state;
  };
}

const twice = (a: Space, b: Space, c: Space): bigint =>
  (BigInt(b[0]) - BigInt(a[0])) * (BigInt(c[1]) - BigInt(a[1])) - (BigInt(b[1]) - BigInt(a[1])) * (BigInt(c[0]) - BigInt(a[0]));

const areaOf = (triangles: readonly SupportTriangle[]): bigint => triangles.reduce((total, [a, b, c]) => total + twice(a, b, c), 0n);

/** The triangle turned counter-clockwise. */
const leftTurning = (triangle: SupportTriangle): SupportTriangle =>
  twice(...triangle) >= 0n ? triangle : [triangle[0], triangle[2], triangle[1]];

/** Whether a plan point is inside or on a triangle. */
function holds(triangle: SupportTriangle, point: Space): boolean {
  const [a, b, c] = leftTurning(triangle);
  return twice(a, b, point) >= 0n && twice(b, c, point) >= 0n && twice(c, a, point) >= 0n;
}

/** Whether a closed triangle and a closed box share a point, by the separating axis rule. */
function touches(triangle: SupportTriangle, box: ClearanceBox): boolean {
  const xs = triangle.map((point) => point[0]);
  const ys = triangle.map((point) => point[1]);
  if (xs.every((x) => x < box.min_x) || xs.every((x) => x > box.max_x)) return false;
  if (ys.every((y) => y < box.min_y) || ys.every((y) => y > box.max_y)) return false;
  const corners: Space[] = [[box.min_x, box.min_y, 0], [box.max_x, box.min_y, 0], [box.max_x, box.max_y, 0], [box.min_x, box.max_y, 0]];
  const [a, b, c] = leftTurning(triangle);
  const edges: [Space, Space][] = [[a, b], [b, c], [c, a]];
  return !edges.some(([from, to]) => corners.every((corner) => twice(from, to, corner) < 0n));
}

const grown = (box: ClearanceBox, radius: number): ClearanceBox => ({
  min_x: box.min_x - radius,
  min_y: box.min_y - radius,
  max_x: box.max_x + radius,
  max_y: box.max_y + radius,
});

/** A plane `z = floor((a x + b y + c) / d)`, and a point on it whose height is exact. */
interface Slope {
  readonly a: bigint;
  readonly b: bigint;
  readonly c: bigint;
  readonly d: bigint;
}

const floorOn = (slope: Slope, x: number, y: number): number => {
  const value = slope.a * BigInt(x) + slope.b * BigInt(y) + slope.c;
  const quotient = value / slope.d;
  return Number(value % slope.d !== 0n && value < 0n ? quotient - 1n : quotient);
};

/** The point with `x` moved down to the nearest place the slope's height is exact. */
function onSlope(slope: Slope, x: number, y: number): Space {
  const value = slope.a * BigInt(x) + slope.b * BigInt(y) + slope.c;
  const off = Number(((value % slope.d) + slope.d) % slope.d);
  const moved = x - off;
  return [moved, y, floorOn(slope, moved, y)];
}

const FLAT: Slope = { a: 0n, b: 0n, c: 0n, d: 1n };
const TILT: Slope = { a: 1n, b: 2n, c: 700n, d: 5n };
/** Below zero everywhere the seeded cases reach, where rounding down and toward zero differ. */
const SUNK: Slope = { a: 1n, b: 2n, c: -90000n, d: 5n };

/** The square `[0, side] x [0, side]` on a slope, as two triangles split along its diagonal. */
function square(side: number, slope: Slope): SupportTriangle[] {
  const corner = (x: number, y: number): Space => [x, y, floorOn(slope, x, y)];
  return [
    [corner(0, 0), corner(side, 0), corner(side, side)],
    [corner(0, 0), corner(side, side), corner(0, side)],
  ];
}

/** Every property the rule claims, checked for one carve. */
function holdsTheRule(support: readonly SupportTriangle[], obstructions: readonly ClearanceBox[], radius: number, kept: readonly SupportTriangle[], slope: Slope): void {
  for (const triangle of kept) {
    expect(twice(...triangle) > 0n, `${JSON.stringify(triangle)} turns counter-clockwise with area`).toBe(true);
    for (const obstruction of obstructions) {
      expect(touches(triangle, grown(obstruction, radius)), `${JSON.stringify(triangle)} keeps off ${JSON.stringify(obstruction)}`).toBe(false);
    }
    expect(support.some((source) => triangle.every((point) => holds(source, point))), `${JSON.stringify(triangle)} is inside one support triangle`).toBe(true);
    for (const point of triangle) expect(point[2], `${JSON.stringify(point)} is on the support's plane`).toBe(floorOn(slope, point[0], point[1]));
  }
}

describe('the support clearance rule', () => {
  it('removes an obstruction in the middle of a square, less exactly the open box a millimetre past it', () => {
    const support = square(10000, TILT);
    const obstruction: ClearanceBox = { min_x: 4000, min_y: 4500, max_x: 6000, max_y: 5000 };
    const kept = carveSupport(support, [obstruction], 340, 'case');
    holdsTheRule(support, [obstruction], 340, kept, TILT);
    // The open box (4000 - 340 - 1, 6000 + 340 + 1) x (4500 - 340 - 1, 5000 + 340 + 1).
    expect(areaOf(kept)).toBe(2n * (10000n * 10000n - 2682n * 1182n));
  });

  it('keeps a support no obstruction meets exactly as given', () => {
    const support = square(10000, TILT);
    expect(carveSupport(support, [{ min_x: 20000, min_y: 0, max_x: 21000, max_y: 100 }], 340, 'case')).toEqual(support);
    expect(carveSupport(support, [], 340, 'case')).toEqual(support);
  });

  it('keeps a triangle whole when its plan bounds meet a box but its long edge keeps it apart', () => {
    const triangle: SupportTriangle = [[0, 0, 0], [10000, 0, 0], [0, 10000, 0]];
    expect(carveSupport([triangle], [{ min_x: 8000, min_y: 8000, max_x: 9000, max_y: 9000 }], 0, 'case')).toEqual([triangle]);
    // The open box's corner (5000, 5000) is on the edge x + y = 10000, so the two keep apart.
    expect(carveSupport([triangle], [{ min_x: 5001, min_y: 5001, max_x: 9000, max_y: 9000 }], 0, 'case')).toEqual([triangle]);
    // A millimetre further and the corner (4999, 5000) is inside the triangle: it is carved.
    const near: ClearanceBox = { min_x: 5000, min_y: 5001, max_x: 9000, max_y: 9000 };
    const carved = carveSupport([triangle], [near], 0, 'case');
    expect(carved).not.toEqual([triangle]);
    holdsTheRule([triangle], [near], 0, carved, FLAT);
  });

  it('removes only the part of an obstruction over the support where it reaches past an edge', () => {
    const support = square(10000, FLAT);
    const obstruction: ClearanceBox = { min_x: 9500, min_y: 3000, max_x: 12000, max_y: 4000 };
    const kept = carveSupport(support, [obstruction], 340, 'case');
    holdsTheRule(support, [obstruction], 340, kept, FLAT);
    // Over the support the open box spans x in (9159, 10000] and y in (2659, 4341).
    expect(areaOf(kept)).toBe(2n * (10000n * 10000n - 841n * 1682n));
  });

  it('keeps nothing when an obstruction covers the whole support', () => {
    expect(carveSupport(square(10000, TILT), [{ min_x: 1000, min_y: 1000, max_x: 9000, max_y: 9000 }], 1000, 'case')).toEqual([]);
    expect(carveSupport(square(10000, TILT), [{ min_x: -1, min_y: -1, max_x: 10001, max_y: 10001 }], 0, 'case')).toEqual([]);
  });

  it('turns a clockwise support triangle counter-clockwise and draws its height from its own corners', () => {
    const triangle: SupportTriangle = [[0, 0, 100], [0, 1000, 300], [1000, 0, 200]];
    const kept = carveSupport([triangle], [{ min_x: 600, min_y: -500, max_x: 2000, max_y: 2000 }], 0, 'case');
    // x <= 599: the corners (0, 0), (599, 0), (599, 401) and (0, 1000), at heights 100 + x/10 + y/5
    // rounded down: 159.9 is 159 and 240.1 is 240.
    expect(kept).toEqual([
      [[0, 0, 100], [599, 0, 159], [599, 401, 240]],
      [[0, 0, 100], [599, 401, 240], [0, 1000, 300]],
    ]);
  });

  it('rounds a sloped edge\'s crossing inward, and drops a part thinner than a millimetre on its clip line', () => {
    const obstruction: ClearanceBox = { min_x: 501, min_y: -100, max_x: 2000, max_y: 100 };
    expect(carveSupport([[[0, 0, 0], [1000, 0, 0], [1000, 10, 0]]], [obstruction], 0, 'case')).toEqual([[[0, 0, 0], [500, 0, 0], [500, 5, 0]]]);
    // The crossing at x = 500 is y = 1.5, rounded down.
    expect(carveSupport([[[0, 0, 0], [1000, 0, 0], [1000, 3, 0]]], [obstruction], 0, 'case')).toEqual([[[0, 0, 0], [500, 0, 0], [500, 1, 0]]]);
    // The crossing is y = 0.5: on the clip line the part holds only y = 0, which has no area.
    expect(carveSupport([[[0, 0, 0], [1000, 0, 0], [1000, 1, 0]]], [obstruction], 0, 'case')).toEqual([]);
    // At x = 999 the part spans y in [4.995, 5.005], which holds one integer: one point, (999, 5).
    expect(carveSupport([[[0, 0, 0], [1000, 5, 0], [0, 10, 0]]], [{ min_x: 1000, min_y: -100, max_x: 2000, max_y: 100 }], 0, 'case'))
      .toEqual([[[0, 0, 0], [999, 5, 0], [0, 10, 0]]]);
  });

  it('keeps the pieces around an obstruction meeting along shared lines, with no crack between them', () => {
    const support = square(10000, FLAT);
    const kept = carveSupport(support, [{ min_x: 4000, min_y: 4000, max_x: 6000, max_y: 6000 }], 0, 'case');
    // Every integer point of the support outside the open box (3999, 6001) x (3999, 6001) is kept.
    for (let x = 0; x <= 10000; x += 37) {
      for (const y of [0, 1, 3998, 3999, 4000, 5000, 6000, 6001, 6002, 9999, 10000]) {
        const removed = x > 3999 && x < 6001 && y > 3999 && y < 6001;
        expect(kept.some((triangle) => holds(triangle, [x, y, 0])), `(${String(x)}, ${String(y)})`).toBe(!removed);
      }
    }
  });

  it('holds the rule for seeded supports and obstructions, and loses support only near a line it cut along', () => {
    const next = sequence(20260917);
    const within = (range: number): number => next() % range;
    for (let trial = 0; trial < 60; trial += 1) {
      const slope = trial % 2 === 0 ? TILT : SUNK;
      const support: SupportTriangle[] = [];
      for (let count = 0; count < 1 + within(4); count += 1) {
        support.push([onSlope(slope, within(20000), within(20000)), onSlope(slope, within(20000), within(20000)), onSlope(slope, within(20000), within(20000))]);
      }
      const obstructions: ClearanceBox[] = [];
      for (let count = 0; count < within(4); count += 1) {
        const [x, y] = [within(20000), within(20000)];
        obstructions.push({ min_x: x, min_y: y, max_x: x + within(3000), max_y: y + within(3000) });
      }
      const radius = within(500);
      const kept = carveSupport(support, obstructions, radius, `trial ${String(trial)}`);
      holdsTheRule(support, obstructions, radius, kept, slope);

      const margin = 2n + 2n * BigInt(obstructions.length);
      for (let sample = 0; sample < 200; sample += 1) {
        const point: Space = [within(20000), within(20000), 0];
        const deep = support.some((source) => {
          const [a, b, c] = leftTurning(source);
          return ([[a, b], [b, c], [c, a]] as [Space, Space][]).every(([from, to]) => {
            const reach = twice(from, to, point);
            const length = (BigInt(to[0]) - BigInt(from[0])) ** 2n + (BigInt(to[1]) - BigInt(from[1])) ** 2n;
            return reach > 0n && reach * reach > margin * margin * length;
          });
        });
        const clear = obstructions.every((obstruction) => {
          const box = grown(obstruction, radius);
          const m = Number(margin);
          return point[0] < box.min_x - m || point[0] > box.max_x + m || point[1] < box.min_y - m || point[1] > box.max_y + m;
        });
        if (deep && clear) {
          expect(kept.some((triangle) => holds(triangle, point)), `trial ${String(trial)} keeps ${JSON.stringify(point)}`).toBe(true);
        }
      }
    }
  });

  it('refuses a negative radius and an obstruction whose bounds cross', () => {
    const support = square(1000, FLAT);
    expect(() => carveSupport(support, [], -1, 'case')).toThrow(GeometryError);
    expect(() => carveSupport(support, [{ min_x: 10, min_y: 0, max_x: 9, max_y: 10 }], 0, 'case')).toThrow(/min_x passes its max_x/);
    expect(() => carveSupport(support, [{ min_x: 0, min_y: 10, max_x: 10, max_y: 9 }], 0, 'case')).toThrow(/min_y passes its max_y/);
  });
});
