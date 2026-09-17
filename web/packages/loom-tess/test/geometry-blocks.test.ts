/**
 * The building blocks of the full expanders, held to their stated rules before any bake calls them:
 * exact integer arithmetic, the facing rule, the ring rule and the fillet arc rule. None of these
 * is wired into a bake yet, and the conformance goldens prove the container has not moved.
 */
import { describe, expect, it } from 'vitest';
import { FACING_LIMIT_MM, turnByFacing } from '../src/core/facing.js';
import { alongByCornerRule, cornerCentre, filletArc, filletCentre, filletSegmentsWithin } from '../src/core/fillet-arc.js';
import { absolute, cross, floorDivide, floorSquareRoot, GeometryError, multiply } from '../src/core/integer-math.js';
import type { Plan, Space } from '../src/core/integer-math.js';
import { ringTwiceArea, requireSimpleRing, triangulateRing, triangulateRingWithHoles } from '../src/core/ring-triangulation.js';
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

/** Whether two counter-clockwise triangles share no interior: some edge of one has the other wholly on its outside. */
function interiorsDisjoint(first: readonly Plan[], second: readonly Plan[]): boolean {
  const separates = (triangle: readonly Plan[], other: readonly Plan[]): boolean =>
    [0, 1, 2].some((corner) => other.every((point) => twiceArea(triangle[corner]!, triangle[(corner + 1) % 3]!, point) <= 0));
  return separates(first, second) || separates(second, first);
}

function expectNoOverlap(points: readonly Plan[], triangles: readonly number[]): void {
  const corners = (at: number): Plan[] => [points[triangles[at]!]!, points[triangles[at + 1]!]!, points[triangles[at + 2]!]!];
  for (let first = 0; first < triangles.length; first += 3) {
    for (let second = first + 3; second < triangles.length; second += 3) {
      expect(interiorsDisjoint(corners(first), corners(second)), `triangles ${first / 3} and ${second / 3}`).toBe(true);
    }
  }
}

function holdsTheRingRuleFrom(ring: readonly Plan[]): void {
  const triangles = triangulateRing(ring, 'case');
  expectNoOverlap(ring, triangles);
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
    // Each ring is tried from every starting vertex, so the sizes stay near a lot's or a roof's.
    for (let index = 0; index < 60; index += 1) holdsTheRingRule(starRing(next, 3 + (index % 18)));
    for (let steps = 1; steps < 8; steps += 1) holdsTheRingRule(staircase(steps, 700, 1100));
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

/** Every property the hole step states, on every rotation of the outer ring and of each hole. */
function holdsTheHoleRule(outer: readonly Plan[], holes: readonly (readonly Plan[])[]): void {
  const rotate = (ring: readonly Plan[], start: number): Plan[] => [...ring.slice(start), ...ring.slice(0, start)];
  outer.forEach((_point, start) => holdsTheHoleRuleOnce(rotate(outer, start), holes));
  holes.forEach((hole, which) => hole.forEach((_point, start) => {
    holdsTheHoleRuleOnce(outer, holes.map((other, index) => (index === which ? rotate(other, start) : other)));
  }));
}

function holdsTheHoleRuleOnce(outer: readonly Plan[], holes: readonly (readonly Plan[])[]): void {
  const { vertices, triangles } = triangulateRingWithHoles(outer, holes, 'case');
  expect(vertices).toEqual([...outer, ...holes.flat()]);
  expect(triangles).toHaveLength((vertices.length + 2 * holes.length - 2) * 3);
  expect(new Set(triangles)).toEqual(new Set(vertices.map((_point, index) => index)));
  const tripled = (ring: readonly Plan[]): Plan[] => ring.map((point): Plan => [point[0] * 3, point[1] * 3]);
  let total = 0;
  for (let index = 0; index < triangles.length; index += 3) {
    const [a, b, c] = [vertices[triangles[index]!]!, vertices[triangles[index + 1]!]!, vertices[triangles[index + 2]!]!];
    const area = twiceArea(a, b, c);
    expect(area, `triangle ${index / 3}`).toBeGreaterThan(0);
    total += area;
    const centroid: Plan = [a[0] + b[0] + c[0], a[1] + b[1] + c[1]];
    expect(inside(centroid, tripled(outer)), `triangle ${index / 3} centroid in the outer ring`).toBe(true);
    for (const hole of holes) expect(inside(centroid, tripled(hole)), `triangle ${index / 3} centroid in a hole`).toBe(false);
  }
  expect(total).toBe(ringTwiceArea(outer, 'case') - holes.reduce((sum, hole) => sum + ringTwiceArea(hole, 'case'), 0));
  expectNoOverlap(vertices, triangles);
}

const square = (x: number, y: number, size: number): Plan[] => [[x, y], [x + size, y], [x + size, y + size], [x, y + size]];

describe('the ring rule with holes', () => {
  it('pins the triangles of a square with a square hole', () => {
    // The well's greatest-x vertex (6000, 3000) bridges to the nearest corner, (9000, 0).
    const { triangles } = triangulateRingWithHoles(square(0, 0, 9000), [square(3000, 3000, 3000)], 'case');
    expect(triangles).toEqual([0, 1, 5, 0, 5, 4, 3, 0, 4, 3, 4, 7, 3, 7, 6, 6, 5, 1, 6, 1, 2, 6, 2, 3]);
  });

  it('holds its rule on a square with a hole and on every tier the fixture states', () => {
    holdsTheHoleRule(square(0, 0, 9000), [square(3000, 3000, 3000)]);
    const tiers = recordsOf(fixtureObject(), 'city.massing').flatMap((record: any) => record.fields.tiers);
    expect(tiers.some((tier: any) => tier.light_wells_mm.length > 0)).toBe(true);
    for (const tier of tiers) holdsTheHoleRule(tier.ring_mm, tier.light_wells_mm);
  });

  it('holds its rule with several holes, ties on greatest x, and a concave outer ring', () => {
    // An L-shaped block with three wells; two share their greatest x.
    const outer: Plan[] = [[0, 0], [20000, 0], [20000, 8000], [8000, 8000], [8000, 20000], [0, 20000]];
    const holes = [square(2000, 2000, 2000), square(12000, 2000, 3000), square(2000, 12000, 2000), square(5000, 3000, 1000)];
    holdsTheHoleRule(outer, holes);
    // A comb whose teeth hide the nearest outer vertices from a well in the back.
    const comb: Plan[] = [[0, 0], [12000, 0], [12000, 3000], [10000, 3000], [10000, 9000], [8000, 9000], [8000, 3000],
      [6000, 3000], [6000, 9000], [4000, 9000], [4000, 3000], [2000, 3000], [2000, 9000], [0, 9000]];
    holdsTheHoleRule(comb, [square(4500, 500, 1000), square(9000, 1000, 1500)]);
  });

  it('holds its rule on star-shaped rings with wells round their centre', () => {
    const next = sequence(17);
    for (let index = 0; index < 12; index += 1) {
      holdsTheHoleRule(starRing(next, 6 + (index % 8)), [square(-600, -600, 500), square(200, 100, 600)]);
    }
  });

  it('refuses a hole that is not strictly inside, and holes that meet', () => {
    const outer = square(0, 0, 9000);
    expect(() => triangulateRingWithHoles(outer, [square(0, 3000, 3000)], 'case')).toThrow(/not strictly inside/);
    expect(() => triangulateRingWithHoles(outer, [square(10000, 0, 1000)], 'case')).toThrow(/not strictly inside/);
    expect(() => triangulateRingWithHoles(outer, [square(1000, 1000, 3000), square(4000, 1000, 3000)], 'case')).toThrow(/meet/);
    const clockwise: Plan[] = [[3000, 3000], [3000, 6000], [6000, 6000], [6000, 3000]];
    expect(() => triangulateRingWithHoles(outer, [clockwise], 'case')).toThrow(/counter-clockwise/);
  });
});

/** The corner rule's arc on a piece whose components pass a kilometre, which the facing limit refuses. */
const ARC_OVER_A_KILOMETRE: Space[] = [
  [5000000, 7000000, 0],
  [5012316, 6984869, 0],
  [5029485, 6975604, 0],
  [5048892, 6973615, 0],
  [5067584, 6979205, 0],
];

describe('the fillet arc rule', () => {
  // A kerb line travels east to (1000, 0), turns left round a 2000 mm corner, and leaves north
  // from (3000, 2000): the centre is (1000, 2000).
  const p: Space = [1000, 0, -100];
  const q: Space = [3000, 2000, -60];

  it('finds each tangent point\'s centre exactly as the grammar\'s corner rule does', () => {
    // Computed by exulanica.grammar.grammars.city.document._corner_centre at lane 20's cc09474b,
    // for these same arguments. The Python test holds this parity directly once the base carries it.
    const cases: [Plan, Plan, number, 1 | -1, Plan][] = [
      [[1000, 0], [5, 0], 2000, 1, [1000, 2000]],
      [[3000, 2000], [0, 3], 2000, 1, [1000, 2000]],
      [[3000, -4000], [4, 3], 5000, 1, [0, 0]],
      [[4010, 3010], [-3010, 4010], 5000, 1, [11, 8]],
      [[1000, 0], [1, 0], 2000, -1, [1000, -2000]],
      [[123457, -98765], [-7, 13], 3001, -1, [126099, -97343]],
      [[5_000_000, 7_000_000], [900_001, -1_700_003], 50_000, 1, [5044189, 7023394]],
      [[0, 0], [1, 1], 1, 1, [-1, 0]],
    ];
    for (const [point, direction, radius, turn, centre] of cases) {
      expect(cornerCentre(point, direction, radius, turn, 'case'), `${point} ${direction}`).toEqual(centre);
    }
  });

  it('turns a corner on a kerb piece over a kilometre long', () => {
    const into: Plan = [900_001, -1_700_003];
    const out: Plan = [1_700_003, 900_001];
    const p: Space = [5_000_000, 7_000_000, 0];
    const centre = cornerCentre([p[0], p[1]], into, 50_000, 1, 'case');
    const back = alongByCornerRule([-out[1], out[0]], 50_000, 'case');
    const q: Space = [centre[0] - back[0], centre[1] - back[1], 0];
    const arc = filletArc(p, into, q, out, 50_000, 4, 'case');
    const found = filletCentre(p, into, q, out, 50_000, 'case');
    for (const point of arc) {
      expect(Math.abs(Math.hypot(point[0] - found[0], point[1] - found[1]) - 50_000)).toBeLessThanOrEqual(2);
    }
    expect(arc).toEqual(ARC_OVER_A_KILOMETRE);
  });

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
