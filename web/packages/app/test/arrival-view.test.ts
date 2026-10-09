import { describe, expect, it } from 'vitest';
import { arrivalView, crosses, parkedFootprint } from '../src/composition/arrival-view.js';

/*
 * A guest's first look at a dressed town (SERVER's first frame): the scene stands across the street
 * from the arrival, and a car parked at the kerb between them filled the view. The view keeps the
 * served spot when nothing parked is in the way, else steps along the footway to a clear one.
 * Plan frame: millimetres east and south; a person arriving faces north (south decreasing).
 */
const scene: [number, number][] = [[0, -12_000], [1_000, -12_500], [-1_000, -11_500]];
const car = parkedFootprint({
  // Road records' frame (east, north): parked along the kerb, 3 m ahead, nose to the east.
  frontAxleMm: [1_400, 3_000], rearAxleMm: [-1_400, 3_000],
  dimensionsMm: { width: 1_800, frontOverhang: 800, rearOverhang: 900 },
})!;
const everywhere = () => true;

describe('the first view of a dressed town', () => {
  it('reads a parked car\'s footprint across the kerb from its axles', () => {
    expect(car.southMm).toBe(-3_000);
    expect(car.halfLengthMm).toBeCloseTo(2_250, 0);
    expect(crosses([0, 0], [0, -12_000], car)).toBe(true);
    expect(crosses([6_000, 0], [0, -12_000], car)).toBe(false);
  });

  it('keeps the served spot when nothing parked is in the way, facing the middle of the scene', () => {
    const view = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [], ground: everywhere });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(view.yaw).toBeCloseTo(0, 6);
  });

  it('steps along the footway past a car parked in the way, onto drawn ground, and still faces the scene', () => {
    // No ground to the east of the arrival: the west side is the one to stand on.
    const view = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [car], ground: (east) => east <= 0 });
    expect(view.moved).toBe(true);
    expect(view.southMm).toBe(0);
    expect(view.eastMm).toBeLessThan(-3_000);
    expect(crosses([view.eastMm, view.southMm], [0, -12_000], car)).toBe(false);
    // Facing the scene's middle, which lies ahead and to the east of where it stands.
    expect(Math.sin(view.yaw)).toBeLessThan(0);
  });

  it('keeps the served spot where no clear spot is near', () => {
    const view = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [car], ground: () => false });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
  });

  it('stands back from a kerb lined with parked cars, where no spot near sees past them, so the nearest stands smaller', () => {
    const row = Array.from({ length: 11 }, (_, n) => parkedFootprint({
      frontAxleMm: [(n - 5) * 5_000 + 1_400, 3_000], rearAxleMm: [(n - 5) * 5_000 - 1_400, 3_000],
      dimensionsMm: { width: 1_800, frontOverhang: 800, rearOverhang: 900 },
    })!);
    const view = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: row, ground: everywhere });
    expect(view.moved).toBe(true);
    // Back from the kerb (south of the arrival), still facing the scene across the street.
    expect(view.southMm).toBeGreaterThan(0);
    expect(Math.cos(view.yaw)).toBeGreaterThan(Math.SQRT1_2);
  });
});
