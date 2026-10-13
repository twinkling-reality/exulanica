import { describe, expect, it } from 'vitest';
import { TriangleQuery, TRIANGLE_QUERY_LIMITS, type TriangleQueryPoint as Point } from '../src/triangle-query.js';

// Independent plane/barycentric oracle: it shares neither the BVH nor its intersection routine.
function triangleHit(origin: Point, direction: Point, a: Point, b: Point, c: Point): number | null {
  const sub = (u: Point, v: Point): Point => [u[0] - v[0], u[1] - v[1], u[2] - v[2]];
  const dot = (u: Point, v: Point) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const cross = (u: Point, v: Point): Point => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const e = sub(b, a); const f = sub(c, a); const n = cross(e, f); const denominator = dot(n, direction);
  if (denominator === 0) return null;
  const t = dot(n, sub(a, origin)) / denominator;
  if (t < 0) return null;
  const p: Point = [origin[0] + direction[0] * t, origin[1] + direction[1] * t, origin[2] + direction[2] * t];
  for (const [u, v] of [[a, b], [b, c], [c, a]] as const) if (dot(cross(sub(v, u), sub(p, u)), n) < 0) return null;
  return t;
}

function linear(positions: ArrayLike<number>, indices: ArrayLike<number>, origin: Point, direction: Point, maximum = Infinity) {
  let result: { distance: number; triangleIndex: number } | null = null;
  const point = (v: number): Point => [positions[v * 3]!, positions[v * 3 + 1]!, positions[v * 3 + 2]!];
  for (let i = 0; i < indices.length; i += 3) {
    const distance = triangleHit(origin, direction, point(indices[i]!), point(indices[i + 1]!), point(indices[i + 2]!));
    if (distance !== null && distance <= maximum && (result === null || distance < result.distance)) result = { distance, triangleIndex: i / 3 };
  }
  return result;
}

function random(seed = 41) {
  return () => { seed = (Math.imul(seed, 1664525) + 1013904223) | 0; return (seed >>> 0) / 4294967296; };
}

describe('static triangle query acceleration', () => {
  it('retains exact primitive and vertex provenance, nearest hit and inclusive ray limit', () => {
    const positions = [0, 0, 8, 2, 0, 8, 0, 2, 8, 0, 0, 3, 2, 0, 3, 0, 2, 3];
    const query = new TriangleQuery({ positions, indices: [5, 5, 5, 0, 1, 2, 3, 4, 5], base: 3, count: 6 });
    expect(query.nearest([0.25, 0.25, 0], [0, 0, 1], 3)).toEqual({ distance: 3, triangleIndex: 1, primitiveOffset: 6, vertexIndices: [3, 4, 5] });
    expect(query.nearest([0.25, 0.25, 0], [0, 0, 1], 2.999)).toBeNull();
    expect(query.nearest([0.25, 0.25, 10], [0, 0, -2])?.distance).toBe(1);
    expect(query.nearest([1.8, 1.8, 0], [0, 0, 1])).toBeNull();
  });

  it('supports nonindexed ranges and snapshots input instead of silently following mutation', () => {
    const positions = new Float32Array([9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 1, 1, 0, 1, 0, 1, 1]);
    const query = new TriangleQuery({ positions, base: 3, count: 3 });
    positions.fill(0);
    expect(query.nearest([0.2, 0.2, 0], [0, 0, 1])).toEqual({ distance: 1, triangleIndex: 0, primitiveOffset: 3, vertexIndices: [3, 4, 5] });
  });

  it('keeps original source order for coincident triangles, shared edges and coplanar bounds', () => {
    const positions = [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0];
    const indices = Array.from({ length: 40 }, () => [0, 1, 2, 1, 3, 2]).flat();
    const query = new TriangleQuery({ positions, indices });
    expect(query.nearest([0.5, 0.5, 2], [0, 0, -1])?.triangleIndex).toBe(0);
    expect(query.nearest([0, 0, 0], [0, 0, 1])?.distance === 0).toBe(true);
    expect(query.nearest([0, 0, 2], [-0, 0, -1])?.triangleIndex).toBe(0);
    expect(query.nearest([0, 0, 0], [1, 0, 0])).toBeNull();
    // The first source triangle lives in the right subtree; the left subtree is visited first.
    const reordered = new TriangleQuery({
      positions: [0, 0, 0, 10, 0, 0, 0, 10, 0, -10, -10, 0, 1, -10, 0, 1, 10, 0],
      indices: [0, 1, 2, ...Array.from({ length: 20 }, () => [3, 4, 5]).flat()],
    });
    expect(reordered.nearest([0.1, 0.1, 1], [0, 0, -1])?.triangleIndex).toBe(0);
  });

  it('handles empty and degenerate geometry without phantom hits', () => {
    const empty = new TriangleQuery({ positions: [] });
    expect(empty.nodeCount).toBe(0);
    expect(empty.nearest([0, 0, 0], [0, 0, 1])).toBeNull();
    const degenerate = new TriangleQuery({ positions: [0, 0, 0, 1, 0, 0, 2, 0, 0] });
    expect(degenerate.nearest([0, 0, 1], [0, 0, -1])).toBeNull();
  });

  it('refuses malformed or excessive geometry before allocating or reading oversized inputs', () => {
    for (const geometry of [
      { positions: [0, 1] }, { positions: [0, 0, NaN] }, { positions: [0, 0, Infinity] },
      { positions: [0, 0, 1e16] }, { positions: [0, 0, 0], indices: [0, 0, 1] },
      { positions: [0, 0, 0], indices: [0, 0, -1] }, { positions: [0, 0, 0], indices: [0, 0, 0.5] },
      { positions: [0, 0, 0], count: 2 }, { positions: [], base: -1 },
      { positions: [], indices: { length: TRIANGLE_QUERY_LIMITS.sourceComponents + 1 } },
      { positions: { length: TRIANGLE_QUERY_LIMITS.vertices * 3 + 3 } },
      { positions: [0, 0, 0], indices: { length: (TRIANGLE_QUERY_LIMITS.triangles + 1) * 3 } },
    ]) expect(() => new TriangleQuery(geometry)).toThrow(RangeError);
    const query = new TriangleQuery({ positions: [] });
    expect(() => query.nearest([0, 0, 0], [0, 0, 0])).toThrow(RangeError);
    expect(() => query.nearest([NaN, 0, 0], [0, 0, 1])).toThrow(RangeError);
    expect(() => query.nearest([0, 0, 0], [0, 0, 1], -1)).toThrow(RangeError);
  });

  it('agrees with the independent linear oracle over distributed geometry and oblique rays', () => {
    const rng = random(); const positions: number[] = []; const indices: number[] = [];
    for (let i = 0; i < 1800; i++) {
      const x = rng() * 40 - 20; const y = rng() * 40 - 20; const z = rng() * 20 - 10;
      const at = positions.length / 3;
      positions.push(x, y, z, x + rng() * 3, y - rng(), z + rng(), x - rng(), y + rng() * 3, z - rng());
      indices.push(at, at + 1, at + 2);
    }
    const query = new TriangleQuery({ positions, indices });
    let actualHits = 0; let tested = 0;
    for (let i = 0; i < 150; i++) {
      const origin: Point = [rng() * 40 - 20, rng() * 40 - 20, 30];
      const direction: Point = [(rng() - 0.5) * 0.2, (rng() - 0.5) * 0.2, -1];
      const maximum = i % 3 === 0 ? 25 : Infinity;
      const expected = linear(positions, indices, origin, direction, maximum);
      const work = { boxes: 0, triangles: 0 };
      const actual = query.nearest(origin, direction, maximum, work); tested += work.triangles;
      expect(actual?.triangleIndex ?? null).toBe(expected?.triangleIndex ?? null);
      if (expected !== null) { actualHits++; expect(actual!.distance).toBeCloseTo(expected.distance, 10); }
    }
    expect(actualHits).toBeGreaterThan(20);
    expect(tested).toBeLessThan(1800 * 150 / 10);
  });

  it('preserves the world ray parameter through rotation, mirrored nonuniform scale and translation', () => {
    const positions = [-1, -1, 0, 1, -1, 0, 0, 1, 0];
    const query = new TriangleQuery({ positions });
    // Rz(90deg) * scale(-2,3,4), then translation(10,20,30).
    const toWorld = (p: Point): Point => [10 - 3 * p[1], 20 - 2 * p[0], 30 + 4 * p[2]];
    const toLocal = (p: Point): Point => [-(p[1] - 20) / 2, -(p[0] - 10) / 3, (p[2] - 30) / 4];
    const worldVertices = [toWorld([-1, -1, 0]), toWorld([1, -1, 0]), toWorld([0, 1, 0])].flat();
    const origin: Point = [10, 20, 6]; const direction: Point = [0, 0, 2];
    const localDirection: Point = [-direction[1] / 2, -direction[0] / 3, direction[2] / 4];
    const expected = linear(worldVertices, [0, 1, 2], origin, direction);
    const actual = query.nearest(toLocal(origin), localDirection);
    expect(actual?.distance).toBe(12);
    expect(actual?.distance).toBe(expected?.distance);
    expect(query.nearest(toLocal(origin), localDirection, 11.99)).toBeNull();
    expect(actual?.vertexIndices).toEqual([0, 1, 2]);
  });
});
