/**
 * The terrain yield rule's cases, each held to the rule's four claims (`terrain-yield-claims.ts`):
 * no gap at all, bounded entry, watertight between cells and exact heights. The two regression
 * cases are the smallest seed a rule cutting one row at a time failed, and a channel no terrain
 * with area fits inside.
 */
import { describe, expect, it } from 'vitest';
import { metCells } from '../src/core/terrain-yield.js';
import type { TerrainPatch } from '../src/core/terrain-yield.js';
import { flat, holdsTheRule, quad, seededCoverings, sequence, twice } from './terrain-yield-claims.js';

describe('the terrain yield rule', () => {
  it('leaves a patch no covering meets as the grid', () => {
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 16, side: 5, heights: flat(5) };
    expect(metCells(patch, [], 'case').size).toBe(0);
    expect(metCells(patch, [[[100, 100], [120, 100], [110, 120]]], 'case').size).toBe(0);
  });

  it('cuts a strip out of flat terrain exactly where its edges run on integer points', () => {
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 16, side: 5, heights: flat(5) };
    // A carriageway and a gutter strip sharing an edge, running east across three cells.
    const { triangles } = holdsTheRule(patch, [...quad([5, 20], [59, 20], [59, 27], [5, 27]), ...quad([5, 27], [59, 27], [59, 29], [5, 29])], 200);
    const area = triangles.reduce((sum, t) => sum + twice(...t), 0) / 2;
    expect(area).toBe(64 * 64 - 54 * 9);
  });

  it('yields to sloping strips, a covering wholly inside a cell, and one touching a corner', () => {
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 16, side: 5, heights: flat(5) };
    holdsTheRule(patch, quad([3, 10], [61, 29], [58, 38], [0, 19]), 400);
    holdsTheRule(patch, quad([7, 60], [60, 3], [63, 7], [10, 64]), 400);
    holdsTheRule(patch, quad([20, 20], [27, 21], [26, 28], [19, 27]), 400);
    holdsTheRule(patch, [[[16, 16], [24, 18], [20, 25]]], 400);
  });

  it('keeps every height on a twisted surface, cutting twisted cells along their diagonal', () => {
    const heights = [0, 9, 3, 12, 5, 7, 1, 14, 2, 8, 11, 4, 6, 13, 0, 10, 3, 9, 12, 1, 7, 5, 15, 2, 8];
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 16, side: 5, heights };
    holdsTheRule(patch, quad([3, 10], [61, 29], [58, 38], [0, 19]), 400);
    holdsTheRule(patch, quad([7, 60], [60, 3], [63, 7], [10, 64]), 400);
  });

  it('yields to coverings whose outlines cross', () => {
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 16, side: 5, heights: flat(5) };
    holdsTheRule(patch, [[[2, 2], [40, 9], [5, 30]], [[10, 25], [30, 3], [37, 33]]], 400);
  });

  it('draws the channel between two coverings that a rule cutting one row at a time lost (regression)', () => {
    // The channel from y 0 to 6 holds (1, 0) and (2, 0) to (2, 6); one row at a time held only
    // collinear points, and a millimetre square round (2, 2) was left uncovered.
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 8, side: 2, heights: flat(2) };
    holdsTheRule(patch, [[[2, 6], [-1, 4], [1, 0]], [[3, -1], [8, 2], [2, 7]]], 2000);
  });

  it('leaves no gap in a channel whose uncovered integer points all lie on one line (regression)', () => {
    // Uncovered from x = 1 + (y + 1000) / 6000 to x = 2 + (y + 8000) / 17000: the only integer points
    // are (2, 0) to (2, 8), and a millimetre square fits. No terrain with area fits inside, so the
    // terrain enters the coverings, by less than a millimetre, and leaves no gap.
    const patch: TerrainPatch = { originX: 0, originY: 0, cell: 8, side: 2, heights: flat(2) };
    holdsTheRule(patch, [[[1, -1000], [2, 5000], [-1000, 0]], [[2, -8000], [3, 9000], [1000, 0]]], 2000);
  });

  it('holds its claims for seeded strips that meet but do not overlap, on flat and twisted terrain', () => {
    const next = sequence(11);
    const within = (range: number): number => next() % range;
    for (let trial = 0; trial < 20; trial += 1) {
      const heights = trial % 2 === 0 ? flat(5) : Array.from({ length: 25 }, () => within(40) - 20);
      holdsTheRule({ originX: 0, originY: 0, cell: 8, side: 5, heights }, seededCoverings(within, false), 50);
    }
  });

  it('holds its claims for seeded overlapping strips and loose triangles', () => {
    const next = sequence(7);
    const within = (range: number): number => next() % range;
    for (let trial = 0; trial < 20; trial += 1) {
      const heights = trial % 2 === 0 ? flat(5) : Array.from({ length: 25 }, () => within(40) - 20);
      holdsTheRule({ originX: 0, originY: 0, cell: 8, side: 5, heights }, seededCoverings(within, true), 50);
    }
  });
});

