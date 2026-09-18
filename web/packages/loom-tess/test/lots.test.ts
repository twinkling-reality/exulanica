/**
 * The lot rule, held to what the records state by arithmetic of this test's own:
 *
 *   - A RING IS ITS OWN AREA: a lot drawn from a ring covers that ring's area exactly, at the
 *     height it states, with `s` and `t` its own plan coordinates.
 *   - A BLOCK GIVES UP WHAT ITS PARCELS TAKE: a block carved by parcels that tile it draws nothing,
 *     and one carved by parcels that tile part of it draws the rest, to the square millimetre.
 *   - A RING THAT TURNS IN IS STILL ITS OWN AREA: a lot is not required to be convex.
 */
import { describe, expect, it } from 'vitest';
import { groundPieces } from '../src/core/lots.js';
import type { Plan } from '../src/core/integer-math.js';
import type { Piece } from '../src/core/pieces.js';

const area = (pieces: readonly Piece[]): number => {
  let total = 0;
  for (const piece of pieces) {
    for (let triangle = 0; triangle + 2 < piece.triangles.length; triangle += 3) {
      const corner = (at: number): [number, number] => {
        const vertex = piece.triangles[triangle + at]!;
        return [piece.vertices[vertex * 3]!, piece.vertices[vertex * 3 + 1]!];
      };
      const [a, b, c] = [corner(0), corner(1), corner(2)];
      total += Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2;
    }
  }
  return total;
};

const ringArea = (ring: readonly Plan[]): number => Math.abs(ring.reduce((total, here, index) => {
  const next = ring[(index + 1) % ring.length]!;
  return total + (here[0] * next[1] - here[1] * next[0]);
}, 0)) / 2;

describe('the lot rule', () => {
  it('draws a ring as its own area, at the height it states', () => {
    const ring: Plan[] = [[0, 0], [20000, 0], [20000, 12000], [0, 12000]];
    const pieces = groundPieces(ring, 135, 'lot', [], 'case');
    expect(area(pieces)).toBe(ringArea(ring));
    const [piece] = pieces as [Piece];
    expect(piece.surface).toMatchObject({ role: 'lot', orientation: 'horizontal' });
    for (let vertex = 0; vertex < piece.vertices.length / 3; vertex += 1) {
      // Every corner is at the stated grade, and its surface coordinates are its own plan point.
      expect(piece.vertices[vertex * 3 + 2]).toBe(135);
      expect(piece.surface!.coordinates[vertex * 2]).toBe(piece.vertices[vertex * 3]);
      expect(piece.surface!.coordinates[vertex * 2 + 1]).toBe(piece.vertices[vertex * 3 + 1]);
    }
  });

  it('draws what its parcels leave, and nothing when they tile it', () => {
    const block: Plan[] = [[0, 0], [20000, 0], [20000, 12000], [0, 12000]];
    const west: Plan[] = [[0, 0], [8000, 0], [8000, 12000], [0, 12000]];
    const east: Plan[] = [[8000, 0], [20000, 0], [20000, 12000], [8000, 12000]];
    expect(area(groundPieces(block, 0, 'lot', [west], 'case'))).toBe(ringArea(east));
    expect(groundPieces(block, 0, 'lot', [west, east], 'case')).toEqual([]);
    // A parcel that reaches past its block takes only what lies inside it.
    const over: Plan[] = [[8000, -5000], [30000, -5000], [30000, 20000], [8000, 20000]];
    expect(area(groundPieces(block, 0, 'lot', [over], 'case'))).toBe(ringArea(west));
  });

  it('draws a ring that turns in as its own area', () => {
    // An L, whose reflex corner the carve has to cut round rather than hull over.
    const ring: Plan[] = [[0, 0], [20000, 0], [20000, 6000], [8000, 6000], [8000, 12000], [0, 12000]];
    expect(area(groundPieces(ring, 0, 'lot', [], 'case'))).toBe(ringArea(ring));
    const notch: Plan[] = [[0, 0], [8000, 0], [8000, 6000], [0, 6000]];
    expect(area(groundPieces(ring, 0, 'lot', [notch], 'case'))).toBe(ringArea(ring) - ringArea(notch));
  });
});
