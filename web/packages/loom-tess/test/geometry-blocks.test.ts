/**
 * The building blocks of the full expanders, held to their stated rules before any bake calls them:
 * exact integer arithmetic, the facing rule, the ring rule and the fillet arc rule. None of these
 * is wired into a bake yet, and the conformance goldens prove the container has not moved.
 */
import { describe, expect, it } from 'vitest';
import { FACING_LIMIT_MM, turnByFacing } from '../src/core/facing.js';
import { filletArc, filletCentre, filletSegmentsWithin } from '../src/core/fillet-arc.js';
import { absolute, cross, floorDivide, floorSquareRoot, GeometryError, multiply } from '../src/core/integer-math.js';
import type { Plan, Space } from '../src/core/integer-math.js';
import { ringTwiceArea, requireSimpleRing, triangulateRing } from '../src/core/ring-triangulation.js';
import { fixtureObject, recordsOf } from './support.js';

/** A small deterministic generator, for property cases: never a source of shipped geometry. */
function sequence(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state;
  };
}

describe('exact integer arithmetic', () => {
  it('floors division toward negative infinity for every sign', () => {
    for (const a of [-7, -6, -1, 0, 1, 6, 7, -9007199254740991, 9007199254740991]) {
      for (const b of [1, 2, 3, 7, 1000]) {
        expect(floorDivide(a, b, 'case')).toBe(Number(BigInt.asIntN(64, (BigInt(a) - (((BigInt(a) % BigInt(b)) + BigInt(b)) % BigInt(b))) / BigInt(b))));
      }
    }
    expect(Object.is(floorDivide(-0, 5, 'case'), 0)).toBe(true);
    expect(() => floorDivide(1, 0, 'case')).toThrow(GeometryError);
  });

  it('takes the floor square root exactly, up to the largest safe integer', () => {
    const exactRoot = (n: bigint): bigint => {
      let low = 0n;
      let high = n + 1n;
      while (high - low > 1n) {
        const middle = (low + high) / 2n;
        if (middle * middle <= n) low = middle;
        else high = middle;
      }
      return low;
    };
    const next = sequence(7);
    const cases = [0, 1, 2, 3, 4, 15, 16, 17, 99, 100, 101, 2 ** 52, 2 ** 53 - 2, 94906265 ** 2, 94906265 ** 2 - 1];
    for (let index = 0; index < 500; index += 1) cases.push(next() * next() % 9007199254740990);
    for (const value of cases) {
      expect(floorSquareRoot(value, 'case'), String(value)).toBe(Number(exactRoot(BigInt(value))));
    }
    expect(() => floorSquareRoot(-1, 'case')).toThrow(GeometryError);
  });

  it('refuses a product a double would round, and never returns negative zero', () => {
    expect(() => multiply(94906267, 94906267, 'case')).toThrow(/not an integer a double holds exactly/);
    expect(Object.is(multiply(0, -5, 'case'), 0)).toBe(true);
    expect(absolute(-3, 'case')).toBe(3);
    expect(cross([0, 0], [1, 0], [0, 1], 'case')).toBe(1);
  });
});

describe('the facing rule', () => {
  it('reads its limit from the grammar table', () => {
    expect(FACING_LIMIT_MM).toBe(1_000_000);
  });

  it('turns exactly along the axes and along a Pythagorean direction', () => {
    const [along, left] = [1200, -350];
    expect(turnByFacing([1, 0], along, left, 'case')).toEqual([1200, -350]);
    expect(turnByFacing([0, 1], along, left, 'case')).toEqual([350, 1200]);
    expect(turnByFacing([-7, 0], along, left, 'case')).toEqual([-1200, 350]);
    expect(turnByFacing([0, -1_000_000], along, left, 'case')).toEqual([-350, -1200]);
    expect(turnByFacing([3, 4], 500, 0, 'case')).toEqual([300, 400]);
    expect(turnByFacing([3, 4], 0, 500, 'case')).toEqual([-400, 300]);
  });

  it('lands within a millimetre plus two parts in the limit of the true rotation, always floored', () => {
    const next = sequence(11);
    for (let index = 0; index < 2000; index += 1) {
      const direction: Plan = [(next() % 2_000_001) - 1_000_000, (next() % 2_000_001) - 1_000_000];
      if (direction[0] === 0 && direction[1] === 0) continue;
      const along = (next() % 40_001) - 20_000;
      const left = (next() % 40_001) - 20_000;
      const [x, y] = turnByFacing(direction, along, left, 'case');
      const length = Math.hypot(direction[0], direction[1]);
      const trueX = (direction[0] * along - direction[1] * left) / length;
      const trueY = (direction[1] * along + direction[0] * left) / length;
      const bound = 1 + (2 * Math.hypot(along, left)) / FACING_LIMIT_MM;
      expect(Math.abs(x - trueX), `${direction} ${along} ${left}`).toBeLessThanOrEqual(bound);
      expect(Math.abs(y - trueY), `${direction} ${along} ${left}`).toBeLessThanOrEqual(bound);
    }
  });

  it('refuses a zero direction and a component beyond the grammar bound', () => {
    expect(() => turnByFacing([0, 0], 1, 1, 'case')).toThrow(/zero direction/);
    expect(() => turnByFacing([1_000_001, 0], 1, 1, 'case')).toThrow(/beyond 1000000/);
  });
});

/** Twice the signed area of one triangle. */
const twiceArea = (a: Plan, b: Plan, c: Plan): number => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

/** Exact point in ring for a test: inside, outside or boundary, on integer coordinates. */
function inside(point: Plan, ring: readonly Plan[]): boolean {
  let crossing = false;
  ring.forEach((a, index) => {
    const b = ring[(index + 1) % ring.length]!;
    if ((a[1] > point[1]) !== (b[1] > point[1])) {
      const left = (point[0] - a[0]) * (b[1] - a[1]);
      const right = (point[1] - a[1]) * (b[0] - a[0]);
      if ((b[1] > a[1] && left < right) || (b[1] < a[1] && left > right)) crossing = !crossing;
    }
  });
  return crossing;
}

/** Every property the ring rule states, checked on the ring starting at each of its vertices. */
function holdsTheRingRule(ring: readonly Plan[]): void {
  ring.forEach((_point, start) => holdsTheRingRuleFrom([...ring.slice(start), ...ring.slice(0, start)]));
}

function holdsTheRingRuleFrom(ring: readonly Plan[]): void {
  const triangles = triangulateRing(ring, 'case');
  expect(triangles).toHaveLength((ring.length - 2) * 3);
  expect(new Set(triangles)).toEqual(new Set(ring.map((_point, index) => index)));
  let total = 0;
  for (let index = 0; index < triangles.length; index += 3) {
    const [a, b, c] = [ring[triangles[index]!]!, ring[triangles[index + 1]!]!, ring[triangles[index + 2]!]!];
    const area = twiceArea(a, b, c);
    expect(area, `triangle ${index / 3}`).toBeGreaterThan(0);
    total += area;
    // The centroid, at three times scale so it stays integer, lies strictly inside the ring.
    const tripled = ring.map((point): Plan => [point[0] * 3, point[1] * 3]);
    expect(inside([a[0] + b[0] + c[0], a[1] + b[1] + c[1]], tripled), `triangle ${index / 3} centroid`).toBe(true);
  }
  expect(total).toBe(ringTwiceArea(ring, 'case'));
}

/** A star-shaped ring, rounded from floating trigonometry here in the test; the rule sees only integers. */
function starRing(next: () => number, count: number): Plan[] {
  const ring: Plan[] = [];
  for (let index = 0; index < count; index += 1) {
    const angle = (2 * Math.PI * index) / count;
    const radius = 1000 + (next() % 9000);
    ring.push([Math.round(radius * Math.cos(angle)), Math.round(radius * Math.sin(angle))]);
  }
  return ring;
}

/** An orthogonal staircase ring, full of straight runs and reflex corners. */
function staircase(steps: number, rise: number, run: number): Plan[] {
  // Straight runs: a vertex in the middle of the base, and one in the middle of the left side.
  const ring: Plan[] = [[0, 0], [(steps * run) / 2, 0], [steps * run, 0]];
  for (let step = steps; step > 0; step -= 1) {
    ring.push([step * run, (steps - step + 1) * rise]);
    ring.push([(step - 1) * run, (steps - step + 1) * rise]);
  }
  ring.push([0, (steps * rise) / 2]);
  return ring;
}

describe('the ring rule', () => {
  it('cuts a square into two triangles in the stated order', () => {
    expect(triangulateRing([[0, 0], [10, 0], [10, 10], [0, 10]], 'case')).toEqual([3, 0, 1, 1, 2, 3]);
  });

  it('pins the order of a concave ring with a straight run', () => {
    const ring: Plan[] = [[0, 0], [4000, 0], [8000, 0], [8000, 3000], [3000, 3000], [3000, 8000], [0, 8000]];
    expect(triangulateRing(ring, 'case')).toEqual([6, 0, 1, 1, 2, 3, 1, 3, 4, 6, 1, 4, 4, 5, 6]);
    holdsTheRingRule(ring);
    // Started on its straight run, the first vertex is collinear, so the first ear cut is another.
    const fromTheRun: Plan[] = [...ring.slice(1), ring[0]!];
    expect(triangulateRing(fromTheRun, 'case')[1]).not.toBe(0);
  });

  it('holds its rule on every ring the fixture states', () => {
    const document = fixtureObject();
    const rings: Plan[][] = [
      ...recordsOf(document, 'city.block').map((record: any) => record.fields.boundary_mm),
      ...recordsOf(document, 'city.parcel').map((record: any) => record.fields.boundary_mm),
      ...recordsOf(document, 'city.district').map((record: any) => record.fields.boundary_mm),
      ...recordsOf(document, 'city.massing').flatMap((record: any) => record.fields.tiers.map((tier: any) => tier.ring_mm)),
      ...recordsOf(document, 'city.parking_space').map((record: any) => record.fields.footprint_mm),
      ...recordsOf(document, 'city.street_tree').map((record: any) => record.fields.pit_mm),
    ];
    expect(rings.length).toBeGreaterThan(8);
    for (const ring of rings) holdsTheRingRule(ring);
  });

  it('holds its rule on star-shaped and staircase rings', () => {
    const next = sequence(5);
    for (let index = 0; index < 150; index += 1) holdsTheRingRule(starRing(next, 3 + (index % 40)));
    for (let steps = 1; steps < 12; steps += 1) holdsTheRingRule(staircase(steps, 700, 1100));
  });

  it('refuses every ring the grammar refuses', () => {
    expect(() => requireSimpleRing([[0, 0], [10, 0]], 'case')).toThrow(/fewer than three/);
    expect(() => requireSimpleRing([[0, 0], [10, 0], [10, 0], [0, 10]], 'case')).toThrow(/zero length/);
    expect(() => requireSimpleRing([[0, 0], [10, 0], [5, 0], [5, 10]], 'case')).toThrow(/spike/);
    expect(() => requireSimpleRing([[0, 0], [0, 10], [10, 10], [10, 0]], 'case')).toThrow(/counter-clockwise/);
    expect(() => requireSimpleRing([[0, 0], [10, 10], [20, 0], [20, 10], [10, 0], [0, 10]], 'case')).toThrow(/intersect|counter-clockwise/);
    expect(() => triangulateRing([[0, 0], [10, 0], [10, 10], [5, 0], [0, 10]], 'case')).toThrow(GeometryError);
  });
});

describe('the fillet arc rule', () => {
  // A kerb line travels east to (1000, 0), turns left round a 2000 mm corner, and leaves north
  // from (3000, 2000): the centre is (1000, 2000).
  const p: Space = [1000, 0, -100];
  const q: Space = [3000, 2000, -60];

  it('finds the centre on the turning side, from both tangent points', () => {
    expect(filletCentre(p, [5, 0], q, [0, 3], 2000, 'case')).toEqual([1000, 2000]);
    // The mirror: travelling east and turning right, south.
    expect(filletCentre([1000, 0, 0], [1, 0], [3000, -2000, 0], [0, -1], 2000, 'case')).toEqual([1000, -2000]);
  });

  it('meets both tangent points exactly and keeps every point within two millimetres of the circle', () => {
    for (const segments of [1, 2, 4, 8, 16, 32, 64]) {
      const arc = filletArc(p, [1, 0], q, [0, 1], 2000, segments, 'case');
      expect(arc).toHaveLength(segments + 1);
      expect(arc[0]).toEqual(p);
      expect(arc[segments]).toEqual(q);
      for (let index = 1; index < arc.length; index += 1) {
        const [x, y] = arc[index]!;
        expect(Math.abs(Math.hypot(x - 1000, y - 2000) - 2000)).toBeLessThanOrEqual(2);
        // Counter-clockwise round the centre, one step at a time.
        const before = arc[index - 1]!;
        expect(twiceArea([1000, 2000], [before[0], before[1]], [x, y])).toBeGreaterThan(0);
      }
    }
  });

  it('pins the points of a quarter turn in eight segments', () => {
    expect(filletArc(p, [1, 0], q, [0, 1], 2000, 8, 'case')).toEqual([
      [1000, 0, -100],
      [1389, 38, -95],
      [1765, 152, -90],
      [2110, 336, -85],
      [2414, 585, -80],
      [2662, 888, -75],
      [2847, 1234, -70],
      [2961, 1609, -65],
      [3000, 2000, -60],
    ]);
  });

  it('takes the centre halfway between the two tangent points\' own centres', () => {
    // Tangent points a few millimetres off one circle: from P the centre is (0, 0), from Q it is
    // (11, 8), and the rule takes the floored midpoint.
    const offP: Space = [3000, -4000, 0];
    const offQ: Space = [4010, 3010, 0];
    expect(filletCentre(offP, [4, 3], offQ, [-3010, 4010], 5000, 'case')).toEqual([5, 4]);
    expect(filletArc(offP, [4, 3], offQ, [-3010, 4010], 5000, 4, 'case')).toEqual([
      [3000, -4000, 0],
      [4305, -2546, 0],
      [4954, -702, 0],
      [4847, 1247, 0],
      [4010, 3010, 0],
    ]);
  });

  it('finds the least power of two that keeps within a sagitta, exactly', () => {
    const counts = [1000, 200, 50, 10, 2].map((sagitta) => filletSegmentsWithin(p, [1, 0], q, [0, 1], 2000, sagitta, 64, 'case'));
    expect(counts).toEqual([...counts].sort((a, b) => a - b));
    for (const [index, sagitta] of [1000, 200, 50, 10, 2].entries()) {
      const segments = counts[index]!;
      const arc = filletArc(p, [1, 0], q, [0, 1], 2000, segments, 'case');
      for (let at = 1; at < arc.length; at += 1) {
        const middle = [(arc[at - 1]![0] + arc[at]![0]) / 2, (arc[at - 1]![1] + arc[at]![1]) / 2];
        expect(2000 - Math.hypot(middle[0]! - 1000, middle[1]! - 2000)).toBeLessThanOrEqual(sagitta + 2);
      }
    }
    expect(() => filletSegmentsWithin(p, [1, 0], q, [0, 1], 2000, 0, 4, 'case')).toThrow(/more than 4 segments/);
  });

  it('refuses what has no fillet', () => {
    expect(() => filletArc(p, [1, 0], q, [2, 0], 2000, 4, 'case')).toThrow(/parallel/);
    expect(() => filletArc(p, [1, 0], q, [0, 1], 0, 4, 'case')).toThrow(/no radius/);
    expect(() => filletArc(p, [1, 0], q, [0, 1], 2000, 6, 'case')).toThrow(/not a power of two/);
  });
});
