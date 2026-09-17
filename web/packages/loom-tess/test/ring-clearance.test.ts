/**
 * The ring clearance rule, held to its two claims by arithmetic of this test's own:
 *
 *   - NOTHING LEFT OUT: every point within the radius of the ring lies in one of the pieces: on the
 *     half-millimetre lattice of a small ring, at seeded points round a large one, and every
 *     sixteenth of a millimetre round each band's far corners, where the thinnest gap would be;
 *   - LITTLE TAKEN BEYOND: every corner of every piece is within five millimetres past the radius of
 *     the ring, whatever the radius, so a carve by them loses almost nothing a capsule could stand
 *     on: at the capsule's own radius that is under two parts in a hundred.
 *
 * Distances are compared as squares, in BigInt, against the ring's own segments; nothing here takes
 * a root or an angle.
 */
import { describe, expect, it } from 'vitest';
import type { Plan } from '../src/core/integer-math.js';
import { GeometryError } from '../src/core/integer-math.js';
import { ringClearance } from '../src/core/ring-clearance.js';
import type { ClearancePiece } from '../src/core/ring-clearance.js';
import { fixtureObject, recordsOf } from './support.js';

/** A small deterministic generator, for property cases: never a source of shipped geometry. */
function sequence(seed: number): () => number {
  let state = BigInt(seed);
  return () => {
    state = (state * 6364136223846793005n + 1442695040888963407n) % 18446744073709551616n;
    return Number(state >> 33n);
  };
}

const big = (value: number): bigint => BigInt(value);

/**
 * The square of the distance from the point `(x / scale, y / scale)` to a segment, as
 * `numerator / denominator` with both positive.
 */
function distanceSquared(x: bigint, y: bigint, scale: bigint, from: Plan, to: Plan): { numerator: bigint; denominator: bigint } {
  const [ax, ay] = [big(from[0]) * scale, big(from[1]) * scale];
  const [bx, by] = [big(to[0]) * scale, big(to[1]) * scale];
  const [ex, ey] = [bx - ax, by - ay];
  const [px, py] = [x - ax, y - ay];
  const along = px * ex + py * ey;
  const length = ex * ex + ey * ey;
  if (along <= 0n) return { numerator: px * px + py * py, denominator: scale * scale };
  if (along >= length) {
    const [qx, qy] = [x - bx, y - by];
    return { numerator: qx * qx + qy * qy, denominator: scale * scale };
  }
  const across = px * ey - py * ex;
  return { numerator: across * across, denominator: length * scale * scale };
}

/** Whether the point `(x / scale, y / scale)` is within `radius` of a closed ring's boundary or inside it. */
function withinOfRing(x: bigint, y: bigint, scale: bigint, ring: readonly Plan[], radius: number): boolean {
  const inside = insideRing(x, y, scale, ring);
  if (inside) return true;
  return ring.some((from, index) => {
    const { numerator, denominator } = distanceSquared(x, y, scale, from, ring[(index + 1) % ring.length]!);
    return numerator <= big(radius) * big(radius) * denominator;
  });
}

/** Whether the point `(x / scale, y / scale)` is inside a closed counter-clockwise ring. */
function insideRing(x: bigint, y: bigint, scale: bigint, ring: readonly Plan[]): boolean {
  return ring.every((from, index) => {
    const to = ring[(index + 1) % ring.length]!;
    const side = (big(to[0]) - big(from[0])) * (y - big(from[1]) * scale) - (big(to[1]) - big(from[1])) * (x - big(from[0]) * scale);
    return side >= 0n;
  });
}

/** Whether the point `(x / scale, y / scale)` is in a closed convex piece, whichever way it turns. */
function inPiece(x: bigint, y: bigint, scale: bigint, piece: ClearancePiece): boolean {
  const sides = piece.map((from, index) => {
    const to = piece[(index + 1) % piece.length]!;
    return (big(to[0]) - big(from[0])) * (y - big(from[1]) * scale) - (big(to[1]) - big(from[1])) * (x - big(from[0]) * scale);
  });
  return sides.every((side) => side >= 0n) || sides.every((side) => side <= 0n);
}

/** Twice the signed area of a walk. */
const twiceArea = (walk: readonly Plan[]): bigint => walk.reduce((total, here, index) => {
  const next = walk[(index + 1) % walk.length]!;
  return total + (big(here[0]) * big(next[1]) - big(here[1]) * big(next[0]));
}, 0n);

/** Both claims, for one ring and radius, over the points `sample` gives. */
function holdsTheRule(ring: readonly Plan[], radius: number, samples: readonly [bigint, bigint, bigint][]): ClearancePiece[] {
  const pieces = ringClearance(ring, radius, 'case');
  for (const piece of pieces) {
    expect(twiceArea(piece) !== 0n, `${JSON.stringify(piece)} has area`).toBe(true);
    // Nothing is taken more than five millimetres past the radius: every corner is that close.
    for (const point of piece) {
      const reach = radius + 5;
      const close = ring.some((from, index) => {
        const { numerator, denominator } = distanceSquared(big(point[0]), big(point[1]), 1n, from, ring[(index + 1) % ring.length]!);
        return numerator <= big(reach) * big(reach) * denominator;
      });
      expect(close || insideRing(big(point[0]), big(point[1]), 1n, ring), `${JSON.stringify(point)} is within ${String(reach)} of the ring`).toBe(true);
    }
  }
  for (const [x, y, scale] of samples) {
    if (!withinOfRing(x, y, scale, ring, radius)) continue;
    const held = pieces.some((piece) => inPiece(x, y, scale, piece));
    if (!held) throw new Error(`(${x}/${scale}, ${y}/${scale}) is within ${String(radius)} of ${JSON.stringify(ring)} and in no piece`);
  }
  return pieces;
}

/** Every point of the ring's box grown by `radius + 4`, on the half-millimetre lattice. */
function everyHalfMillimetre(ring: readonly Plan[], radius: number): [bigint, bigint, bigint][] {
  const xs = ring.map((point) => point[0]);
  const ys = ring.map((point) => point[1]);
  const [west, east] = [Math.min(...xs) - radius - 4, Math.max(...xs) + radius + 4];
  const [south, north] = [Math.min(...ys) - radius - 4, Math.max(...ys) + radius + 4];
  const out: [bigint, bigint, bigint][] = [];
  for (let y = 2 * south; y <= 2 * north; y += 1) {
    for (let x = 2 * west; x <= 2 * east; x += 1) out.push([big(x), big(y), 2n]);
  }
  return out;
}

/**
 * Every sixteenth of a millimetre in a four millimetre box round each corner of each band: where a
 * band's outward step leans along its edge it leaves a lens there, no wider than that lean and no
 * taller than about one over the radius, which coarser sampling walks straight past.
 */
function roundBandCorners(ring: readonly Plan[], radius: number): [bigint, bigint, bigint][] {
  const out: [bigint, bigint, bigint][] = [];
  const scale = 16n;
  const reach = 2n * scale;
  ring.forEach((from, index) => {
    const to = ring[(index + 1) % ring.length]!;
    // The true outward step, at the radius across the edge, as sixteenths: the band's far corners
    // lie within a millimetre of these, whichever integer step the rule takes.
    const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
    const length = Math.hypot(dx, dy);
    const [nx, ny] = [(dy / length) * radius, (-dx / length) * radius];
    for (const corner of [from, to]) {
      const [cx, cy] = [BigInt(Math.round((corner[0] + nx) * 16)), BigInt(Math.round((corner[1] + ny) * 16))];
      for (let y = -reach; y <= reach; y += 1n) {
        for (let x = -reach; x <= reach; x += 1n) out.push([cx + x, cy + y, scale]);
      }
    }
  });
  return out;
}

/** Seeded points round a ring: at its corners, along its edges, and out to a little past the radius. */
function seededRound(ring: readonly Plan[], radius: number, seed: number, count: number): [bigint, bigint, bigint][] {
  const next = sequence(seed);
  const out: [bigint, bigint, bigint][] = [];
  for (let sample = 0; sample < count; sample += 1) {
    const index = next() % ring.length;
    const [from, to] = [ring[index]!, ring[(index + 1) % ring.length]!];
    const steps = 1 + (next() % 64);
    const scale = 64n;
    const x = big(from[0]) * scale + (big(to[0] - from[0]) * big(steps));
    const y = big(from[1]) * scale + (big(to[1] - from[1]) * big(steps));
    const away = (next() % (2 * radius + 8)) - radius - 4;
    const side = next() % 2 === 0 ? 1 : -1;
    out.push([x + big(side * away) * scale, y + big(side * (next() % (2 * radius + 8)) - side * (radius + 4)) * scale, scale]);
  }
  return out;
}

describe('the ring clearance rule', () => {
  it('holds every point within the radius of a square, to the half millimetre', () => {
    const square: Plan[] = [[0, 0], [12, 0], [12, 9], [0, 9]];
    holdsTheRule(square, 5, [...everyHalfMillimetre(square, 5), ...roundBandCorners(square, 5)]);
  });

  it('holds every point within the radius of a ring with a reflex corner and a slanted edge', () => {
    const shape: Plan[] = [[0, 0], [14, 0], [14, 6], [7, 6], [9, 13], [0, 11]];
    holdsTheRule(shape, 4, [...everyHalfMillimetre(shape, 4), ...roundBandCorners(shape, 4)]);
    holdsTheRule(shape, 7, [...everyHalfMillimetre(shape, 7), ...roundBandCorners(shape, 7)]);
  });

  it('holds every point within a radius of one, where a corner hull is only a few millimetres across', () => {
    const shape: Plan[] = [[0, 0], [9, 2], [5, 8]];
    holdsTheRule(shape, 1, [...everyHalfMillimetre(shape, 1), ...roundBandCorners(shape, 1)]);
    holdsTheRule(shape, 2, [...everyHalfMillimetre(shape, 2), ...roundBandCorners(shape, 2)]);
  });

  it('holds seeded points round the conformance tile\'s building at the capsule radius', () => {
    const building = recordsOf(fixtureObject(), 'city.massing')[0].fields;
    const ring = building.tiers[0].ring_mm as Plan[];
    const pieces = holdsTheRule(ring, 340, [...seededRound(ring, 340, 20260917, 4000), ...roundBandCorners(ring, 340)]);
    // The building's base ring is chamfered, which is what a plan box would have closed a footway for.
    expect(ring.length).toBeGreaterThan(4);
    expect(pieces.length).toBeGreaterThan(ring.length);
  });

  it('holds seeded points round seeded rings at several radii', () => {
    const next = sequence(11);
    for (const radius of [1, 3, 17, 340]) {
      for (let trial = 0; trial < 4; trial += 1) {
        const size = 40 + (next() % 400);
        const ring: Plan[] = [
          [0, 0],
          [size, next() % 20],
          [size + (next() % 30), size],
          [next() % 15, size + (next() % 10)],
        ];
        holdsTheRule(ring, radius, [...seededRound(ring, radius, 7 + trial, 1500), ...roundBandCorners(ring, radius)]);
      }
    }
  });

  it('refuses a radius that is not positive, and a ring the grammar refuses', () => {
    const square: Plan[] = [[0, 0], [10, 0], [10, 10], [0, 10]];
    expect(() => ringClearance(square, 0, 'case')).toThrow(GeometryError);
    expect(() => ringClearance(square, -5, 'case')).toThrow(/not positive/);
    expect(() => ringClearance([[0, 0], [10, 0]], 5, 'case')).toThrow(/fewer than three/);
    expect(() => ringClearance([[0, 0], [0, 10], [10, 10], [10, 0]], 5, 'case')).toThrow(/counter-clockwise/);
  });
});
