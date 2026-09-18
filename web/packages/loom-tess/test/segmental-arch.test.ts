/**
 * The segmental arch rule, held to the three points a record states and to a circle this test
 * derives for itself.
 *
 * WHY THE CIRCLE IS RE-DERIVED HERE RATHER THAN READ FROM THE RULE. The rule finds its circle by an
 * integer identity, that `(4 * rise * w)^2 + (w^2 - 4 * rise^2)^2` is `(w^2 + 4 * rise^2)^2`, and
 * checking its points against a radius taken from that same identity would be one derivation
 * compared with itself. So the test solves the ordinary school formula for a circular segment,
 * `r = (h^2 + rise^2) / (2 * rise)` over the half span `h`, in floating point, and asks whether the
 * rule's integer points sit on THAT circle. Different algebra, different arithmetic, one answer.
 *
 * The tolerance is 2 mm and it is the flooring rather than a fudge: every point is floored onto the
 * millimetre lattice on each axis, so it may sit up to the diagonal of one millimetre, 1.415 mm,
 * inside its circle, and nothing here is allowed to be further out than that.
 */
import { describe, expect, it } from 'vitest';
import {
  archCircle,
  archHead,
  archPoints,
  archRadiusMm,
  archSegmentBound,
  archSegmentsWithin,
} from '../src/core/segmental-arch.js';
import type { Plan } from '../src/core/integer-math.js';

/** How far a point may sit off its circle: the diagonal of the millimetre it was floored onto. */
const FLOORING_MM = 2;
/** What the city's projections state, in `city.v2.json`, for every one of the four. */
const RESOLUTION_MM = 1;

/** The circle through an arched head's three points, by the school formula, in floating point. */
function circleOf(uLeft: number, uRight: number, headZ: number, rise: number): { u: number; z: number; r: number } {
  const half = (uRight - uLeft) / 2;
  const r = (half * half + rise * rise) / (2 * rise);
  return { u: (uLeft + uRight) / 2, z: headZ + rise - r, r };
}

const distance = (circle: { u: number; z: number }, point: Plan): number =>
  Math.hypot(point[0] - circle.u, point[1] - circle.z);

/** The worst a chord of these points strays from the circle, measured at its own midpoint. */
function worstSagitta(circle: { u: number; z: number; r: number }, points: readonly Plan[]): number {
  let worst = 0;
  points.forEach((point, index) => {
    if (index === 0) return;
    const before = points[index - 1]!;
    const middle: Plan = [(before[0] + point[0]) / 2, (before[1] + point[1]) / 2];
    worst = Math.max(worst, circle.r - distance(circle, middle));
  });
  return worst;
}

/** Heads taken from the corridor city's own records, from its shallowest rise to its steepest. */
const HEADS: readonly { readonly name: string; readonly width: number; readonly rise: number }[] = [
  { name: 'the shallowest rise in the corridor city', width: 758, rise: 5 },
  { name: 'the conformance fixture\'s head', width: 1200, rise: 250 },
  { name: 'the steepest rise in the corridor city', width: 1056, rise: 516 },
  { name: 'a half round head, whose springings are opposite points', width: 1200, rise: 600 },
];

describe('the segmental arch rule', () => {
  it('puts the three points the record states exactly where it states them', () => {
    for (const head of HEADS) {
      const [uLeft, uRight, headZ] = [4000, 4000 + head.width, 9000];
      const points = archHead(uLeft, uRight, headZ, head.rise, RESOLUTION_MM, head.name);
      const crown = points[(points.length - 1) / 2]!;
      expect(points[0], head.name).toEqual([uRight, headZ]);
      expect(points[points.length - 1], head.name).toEqual([uLeft, headZ]);
      // The crown is the middle point because three points seed the bisection, and its height is
      // the rise exactly rather than the rise less a rounding.
      expect(crown[1], head.name).toBe(headZ + head.rise);
      expect(crown[0], head.name).toBe(Math.floor((uLeft + uRight) / 2));
    }
  });

  it('places every point on the circle a different arithmetic draws through those three', () => {
    for (const head of HEADS) {
      const [uLeft, uRight, headZ] = [4000, 4000 + head.width, 9000];
      const circle = circleOf(uLeft, uRight, headZ, head.rise);
      for (const point of archHead(uLeft, uRight, headZ, head.rise, RESOLUTION_MM, head.name)) {
        expect(Math.abs(distance(circle, point) - circle.r), `${head.name} at ${String(point)}`)
          .toBeLessThanOrEqual(FLOORING_MM);
      }
      // And the rule's own radius agrees with the school formula to the millimetre it reports in.
      const radius = archRadiusMm(archCircle(uLeft, uRight, headZ, head.rise, head.name), head.name);
      expect(radius, head.name).toBe(Math.floor(circle.r));
    }
  });

  it('cuts as finely as the resolution asks and no finer', () => {
    for (const head of HEADS) {
      const [uLeft, uRight, headZ] = [4000, 4000 + head.width, 9000];
      const circle = archCircle(uLeft, uRight, headZ, head.rise, head.name);
      const chosen = archSegmentsWithin(circle, RESOLUTION_MM, archSegmentBound(circle, head.name), head.name);
      const drawn = circleOf(uLeft, uRight, headZ, head.rise);
      // Within the resolution, allowing for the flooring the criterion allows for and no more.
      expect(worstSagitta(drawn, archPoints(circle, chosen, head.name)), head.name)
        .toBeLessThanOrEqual(RESOLUTION_MM + FLOORING_MM);
      // And one halving coarser is NOT within it, so the count is chosen rather than reached.
      if (chosen > 2) {
        expect(worstSagitta(drawn, archPoints(circle, chosen / 2, head.name)), head.name)
          .toBeGreaterThan(RESOLUTION_MM);
      }
    }
  });

  it('runs from the right springing to the left, rising to the crown and falling from it', () => {
    for (const head of HEADS) {
      const [uLeft, uRight, headZ] = [4000, 4000 + head.width, 9000];
      const points = archHead(uLeft, uRight, headZ, head.rise, RESOLUTION_MM, head.name);
      const crown = (points.length - 1) / 2;
      points.forEach((point, index) => {
        if (index === 0) return;
        const before = points[index - 1]!;
        expect(point[0], `${head.name} at ${String(index)}`).toBeLessThan(before[0]);
        if (index <= crown) expect(point[1], `${head.name} at ${String(index)}`).toBeGreaterThanOrEqual(before[1]);
        else expect(point[1], `${head.name} at ${String(index)}`).toBeLessThanOrEqual(before[1]);
      });
    }
  });

  it('draws a half round head rather than refusing its opposite springings', () => {
    // The fillet rule cannot halve a chord between opposite points and refuses one. Here the crown
    // is stated, so the first chord halved is a quarter of the circle and the case never arises.
    const points = archHead(0, 1200, 9000, 600, RESOLUTION_MM, 'half round');
    expect(points.length).toBeGreaterThan(3);
    expect(points[0]).toEqual([1200, 9000]);
    expect(points[points.length - 1]).toEqual([0, 9000]);
    expect(points[(points.length - 1) / 2]).toEqual([600, 9600]);
  });

  it('refuses a head that is not an arch, and one that passes half its width', () => {
    expect(() => archCircle(0, 1200, 9000, 600, 'case')).not.toThrow();
    expect(() => archCircle(0, 1200, 9000, 601, 'case')).toThrow(/passes half its width/);
    expect(() => archCircle(0, 1200, 9000, 0, 'case')).toThrow(/has no rise/);
    expect(() => archCircle(1200, 1200, 9000, 100, 'case')).toThrow(/which is no span/);
  });

  it('refuses a segment count that three points cannot seed', () => {
    const circle = archCircle(0, 1200, 9000, 250, 'case');
    expect(() => archPoints(circle, 1, 'case')).toThrow(/not a power of two of at least two/);
    expect(() => archPoints(circle, 6, 'case')).toThrow(/not a power of two of at least two/);
    expect(() => archPoints(circle, 4, 'case')).not.toThrow();
  });

  it('places a point from the two it halves and nothing else, so a finer cut keeps the coarser one', () => {
    const circle = archCircle(3000, 4200, 9000, 250, 'case');
    const coarse = archPoints(circle, 4, 'case');
    const fine = archPoints(circle, 8, 'case');
    // Every point of the four-segment arc is a point of the eight-segment one, at twice the index.
    coarse.forEach((point, index) => {
      expect(fine[index * 2], `point ${String(index)}`).toEqual(point);
    });
  });
});
