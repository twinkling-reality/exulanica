/**
 * The support carve rule, held to its three claims by arithmetic of this test's own:
 *
 *   - NOTHING UNSUPPORTED KEPT: no kept triangle's interior meets a clearance piece's interior, so a
 *     capsule stood anywhere on what is kept meets nothing the clearance holds;
 *   - LITTLE LOST: every point of a support surface more than two millimetres on each axis from
 *     every clearance is still kept;
 *   - KEPT TO ITS SURFACE: every kept triangle lies in one of the triangles it was given, grown by a
 *     millimetre on each axis, and every height is that triangle's own plane, floored. The
 *     millimetre is what stops a crack where two triangles of one surface share a sloping edge.
 *
 * The cases include a ring clearance round a real base ring, so the two rules are held together.
 */
import { describe, expect, it } from 'vitest';
import type { Plan, Space } from '../src/core/integer-math.js';
import { ringClearance } from '../src/core/ring-clearance.js';
import { carveSupport } from '../src/core/support-carve.js';
import type { ClearanceWalk, SupportTriangle } from '../src/core/support-carve.js';

const big = (value: number): bigint => BigInt(value);
const plan = (point: Space): Plan => [point[0], point[1]];

const twice = (a: Plan, b: Plan, c: Plan): bigint =>
  (big(b[0]) - big(a[0])) * (big(c[1]) - big(a[1])) - (big(b[1]) - big(a[1])) * (big(c[0]) - big(a[0]));

const leftTurning = (walk: readonly Plan[]): readonly Plan[] => {
  const area = walk.reduce((total, here, index) => {
    const next = walk[(index + 1) % walk.length]!;
    return total + (big(here[0]) * big(next[1]) - big(here[1]) * big(next[0]));
  }, 0n);
  return area >= 0n ? walk : [...walk].reverse();
};

/** Whether the interiors of two convex walks share a point, by the separating axis rule. */
function interiorsMeet(first: readonly Plan[], second: readonly Plan[]): boolean {
  const [a, b] = [leftTurning(first), leftTurning(second)];
  const apart = (edges: readonly Plan[], points: readonly Plan[]): boolean => edges.some((from, index) => {
    const to = edges[(index + 1) % edges.length]!;
    return points.every((point) => twice(from, to, point) <= 0n);
  });
  return !apart(a, b) && !apart(b, a);
}

/** Whether the point `(x / scale, y / scale)` lies in a closed convex walk. */
function holdsScaled(walk: readonly Plan[], x: bigint, y: bigint, scale: bigint): boolean {
  const turned = leftTurning(walk);
  return turned.every((from, index) => {
    const to = turned[(index + 1) % turned.length]!;
    return (big(to[0]) - big(from[0])) * (y - big(from[1]) * scale) - (big(to[1]) - big(from[1])) * (x - big(from[0]) * scale) >= 0n;
  });
}

/** Whether a point is more than `reach` from a walk on each axis: its grown box does not hold it. */
function beyond(walk: readonly Plan[], x: bigint, y: bigint, scale: bigint, reach: number): boolean {
  const grown = walk.flatMap((point): Plan[] => [
    [point[0] - reach, point[1] - reach], [point[0] + reach, point[1] - reach],
    [point[0] - reach, point[1] + reach], [point[0] + reach, point[1] + reach],
  ]);
  // The grown walk's convex hull holds the walk grown by `reach` on each axis, which is enough here:
  // a point outside that hull is more than `reach` from the walk on some axis.
  return !holdsScaled(hullOf(grown), x, y, scale);
}

/** The convex hull of points, counter-clockwise. */
function hullOf(points: readonly Plan[]): Plan[] {
  const sorted = [...points].sort((a, b) => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]));
  const chain = (ordered: readonly Plan[]): Plan[] => {
    const out: Plan[] = [];
    for (const point of ordered) {
      while (out.length >= 2 && twice(out[out.length - 2]!, out[out.length - 1]!, point) <= 0n) out.pop();
      out.push(point);
    }
    return out;
  };
  return [...chain(sorted).slice(0, -1), ...chain([...sorted].reverse()).slice(0, -1)];
}

/** The height of the plane through a triangle's corners at a point, floored. */
function heightOn(triangle: SupportTriangle, point: Plan): number {
  const [a, b, c] = triangle;
  const whole = twice(plan(a), plan(b), plan(c));
  const weighted = big(a[2]) * twice(point, plan(b), plan(c))
    + big(b[2]) * twice(plan(a), point, plan(c))
    + big(c[2]) * twice(plan(a), plan(b), point);
  const quotient = weighted / whole;
  return Number(weighted % whole !== 0n && (weighted < 0n) !== (whole < 0n) ? quotient - 1n : quotient);
}

/** Every claim, for one carve, over the half-millimetre lattice of the surfaces' box. */
function holdsTheRule(support: readonly SupportTriangle[], clearances: readonly ClearanceWalk[]): SupportTriangle[] {
  const kept = carveSupport(support, clearances, 'case');
  for (const triangle of kept) {
    const walk = triangle.map(plan);
    expect(twice(walk[0]!, walk[1]!, walk[2]!) > 0n, `${JSON.stringify(triangle)} turns counter-clockwise with area`).toBe(true);
    for (const clearance of clearances) {
      expect(interiorsMeet(walk, clearance), `${JSON.stringify(walk)} keeps out of ${JSON.stringify(clearance)}`).toBe(false);
    }
    const grown = (triangle: SupportTriangle): Plan[] => hullOf(triangle.flatMap((point): Plan[] => [
      [point[0] - 1, point[1] - 1], [point[0] + 1, point[1] - 1],
      [point[0] - 1, point[1] + 1], [point[0] + 1, point[1] + 1],
    ]));
    const source = support.find((candidate) => walk.every((point) => holdsScaled(grown(candidate), big(point[0]), big(point[1]), 1n)));
    expect(source, `${JSON.stringify(walk)} lies in one surface it was given, grown a millimetre`).toBeDefined();
    for (const point of triangle) {
      expect(point[2], `${JSON.stringify(point)} is on its surface`).toBe(heightOn(source!, plan(point)));
    }
  }
  const xs = support.flatMap((triangle) => triangle.map((point) => point[0]));
  const ys = support.flatMap((triangle) => triangle.map((point) => point[1]));
  for (let y = 2 * Math.min(...ys); y <= 2 * Math.max(...ys); y += 1) {
    for (let x = 2 * Math.min(...xs); x <= 2 * Math.max(...xs); x += 1) {
      const onSurface = support.some((triangle) => holdsScaled(triangle.map(plan), big(x), big(y), 2n));
      if (!onSurface) continue;
      if (!clearances.every((clearance) => beyond(clearance, big(x), big(y), 2n, 2))) continue;
      const held = kept.some((triangle) => holdsScaled(triangle.map(plan), big(x), big(y), 2n));
      if (!held) throw new Error(`(${x}/2, ${y}/2) is on a surface, clear of every clearance, and not kept`);
    }
  }
  return kept;
}

/** A flat square of support, as two triangles, at a stated height. */
function flatSquare(west: number, south: number, side: number, height: number): SupportTriangle[] {
  const at = (x: number, y: number): Space => [x, y, height];
  return [
    [at(west, south), at(west + side, south), at(west + side, south + side)],
    [at(west, south), at(west + side, south + side), at(west, south + side)],
  ];
}

describe('the support carve rule', () => {
  it('keeps a surface no clearance meets exactly as it was given', () => {
    const support = flatSquare(0, 0, 20, 7);
    expect(carveSupport(support, [], 'case')).toEqual(support);
    expect(carveSupport(support, [[[100, 100], [110, 100], [110, 110], [100, 110]]], 'case')).toEqual(support);
  });

  it('keeps nothing where a clearance covers the whole surface', () => {
    const support = flatSquare(0, 0, 10, 0);
    expect(carveSupport(support, [[[-5, -5], [15, -5], [15, 15], [-5, 15]]], 'case')).toEqual([]);
  });

  it('carves a square clearance out of a sloping surface, keeping heights on its plane', () => {
    const support: SupportTriangle[] = [
      [[0, 0, 0], [24, 0, 12], [24, 18, 21]],
      [[0, 0, 0], [24, 18, 21], [0, 18, 9]],
    ];
    const kept = holdsTheRule(support, [[[8, 6], [15, 6], [15, 12], [8, 12]]]);
    expect(kept.length).toBeGreaterThan(4);
  });

  it('carves a ring clearance, so a base ring and its radius take support together', () => {
    const support = flatSquare(0, 0, 40, 3);
    const ring: Plan[] = [[14, 12], [26, 14], [24, 26], [12, 24]];
    holdsTheRule(support, ringClearance(ring, 5, 'case'));
  });

  it('carves a ring clearance with a chamfered corner, at a radius of three', () => {
    const support = flatSquare(-4, -4, 36, 0);
    const ring: Plan[] = [[8, 6], [20, 6], [24, 10], [24, 20], [8, 20]];
    holdsTheRule(support, ringClearance(ring, 3, 'case'));
  });

  it('carves several clearances that overlap each other', () => {
    const support = flatSquare(0, 0, 30, 5);
    holdsTheRule(support, [
      ...ringClearance([[6, 6], [14, 6], [14, 14], [6, 14]], 2, 'case'),
      ...ringClearance([[11, 10], [21, 13], [16, 21]], 3, 'case'),
    ]);
  });
});
