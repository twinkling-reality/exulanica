import { describe, expect, it } from 'vitest';
import { planSight } from '../src/composition/sight.js';
import type { SightBlocker } from '../src/composition/arrival-view.js';

/*
 * What hides a being, by arithmetic on a plan a test states: a house 10 m square whose near wall is
 * 20 m south of the origin, and a post 30 cm square 5 m east of it. Plan rings are millimetres east
 * and south; the sight is asked in metres, x east and z south.
 */
const HOUSE: SightBlocker = [[-5000, 20000], [5000, 20000], [5000, 30000], [-5000, 30000]];
const POST: SightBlocker = [[4850, -150], [5150, -150], [5150, 150], [4850, 150]];
const MARGIN_MM = 500;
const sight = planSight([HOUSE, POST], MARGIN_MM);
const eye = { x: 0, z: 0 };

describe('what hides a being, from a plan of what stands at eye height', () => {
  it('sees a point with nothing between, and not one behind a house or a post', () => {
    // In front of the house, beside it, and past its corner with the line clear of it.
    expect(sight.sees(eye, { x: 0, z: 15 })).toBe(true);
    expect(sight.sees(eye, { x: 12, z: 25 })).toBe(true);
    // Behind the house: the line crosses its near wall at 20 m and its far wall at 30 m.
    expect(sight.sees(eye, { x: 0, z: 40 })).toBe(false);
    // The line to (12, 40) crosses the plane of the near wall at x = 6, a metre past the corner: clear.
    expect(sight.sees(eye, { x: 12, z: 40 })).toBe(true);
    // The line to (9, 40) crosses it at x = 4.5, inside the wall.
    expect(sight.sees(eye, { x: 9, z: 40 })).toBe(false);
    // A post 30 cm across hides the point straight behind it and not one a metre to its side.
    expect(sight.sees(eye, { x: 10, z: 0 })).toBe(false);
    expect(sight.sees(eye, { x: 10, z: 1 })).toBe(true);
    // The same from the other side: what hides one from the other hides the other from the one.
    expect(sight.sees({ x: 0, z: 40 }, eye)).toBe(false);
    expect(sight.sees({ x: 10, z: 0 }, eye)).toBe(false);
  });

  it('sees someone standing in a wall\'s own depth from in front, and not from behind the house', () => {
    // 30 cm inside the near wall, in a doorway: the wall is crossed 30 cm short of them, within the
    // half metre a thing may stand in front of the point it is at.
    expect(sight.sees(eye, { x: 0, z: 20.3 })).toBe(true);
    // 60 cm inside is past it.
    expect(sight.sees(eye, { x: 0, z: 20.6 })).toBe(false);
    // From behind the house the far wall is crossed 9.7 m short of them.
    expect(sight.sees({ x: 0, z: 50 }, { x: 0, z: 20.3 })).toBe(false);
    // A point nearer than the margin is seen: nothing can stand between.
    expect(sight.sees(eye, { x: 0.2, z: 0.2 })).toBe(true);
  });

  it('says how far a ray runs before the plan stands in it, along the ray as it leans', () => {
    // Level and due south: the near wall, 20 m.
    expect(sight.reach([0, 1.6, 0], [0, 0, 1])).toBeCloseTo(20, 9);
    // The direction's length does not matter.
    expect(sight.reach([0, 1.6, 0], [0, 0, 250])).toBeCloseTo(20, 9);
    // Leaning down 3 in 4: 20 m of plan is 25 m of ray.
    expect(sight.reach([0, 1.6, 0], [0, -3, 4])).toBeCloseTo(25, 9);
    // East to the post's near face, 4.85 m.
    expect(sight.reach([0, 1.6, 0], [1, 0, 0])).toBeCloseTo(4.85, 9);
    // Nothing stands north, and a ray straight down meets nothing of a plan.
    expect(sight.reach([0, 1.6, 0], [0, 0, -1])).toBe(Number.POSITIVE_INFINITY);
    expect(sight.reach([0, 1.6, 0], [0, -1, 0])).toBe(Number.POSITIVE_INFINITY);
  });

  it('answers the same far from the origin, across many squares of its index, and west and north of it', () => {
    // The same house 1.2 km east and 0.9 km north, and a wall 300 m long.
    const far: SightBlocker = HOUSE.map(([x, y]) => [x + 1_200_000, y - 900_000] as const);
    const wall: SightBlocker = [[-400_000, -50_000], [-100_000, -50_000], [-100_000, -49_800], [-400_000, -49_800]];
    const wide = planSight([far, wall], MARGIN_MM);
    const from = { x: 1200, z: -900 };
    expect(wide.sees(from, { x: 1200, z: -860 })).toBe(false);
    expect(wide.sees(from, { x: 1212, z: -860 })).toBe(true);
    // Seen from 800 m off, through every square between: hidden behind the far house, seen beside it.
    expect(wide.sees({ x: 1200, z: -1700 }, { x: 1200, z: -865 })).toBe(false);
    expect(wide.sees({ x: 1230, z: -1700 }, { x: 1230, z: -865 })).toBe(true);
    // The long wall hides along its whole length, and not past its end.
    for (const x of [-390, -250, -110]) expect(wide.sees({ x, z: -60 }, { x, z: -40 })).toBe(false);
    expect(wide.sees({ x: -90, z: -60 }, { x: -90, z: -40 })).toBe(true);
    expect(wide.reach([-250, 1.6, -60], [0, 0, 1])).toBeCloseTo(10, 9);
  });

  it('hides nothing where the plan is empty', () => {
    const open = planSight([], MARGIN_MM);
    expect(open.sees(eye, { x: 0, z: 40 })).toBe(true);
    expect(open.reach([0, 1.6, 0], [0, 0, 1])).toBe(Number.POSITIVE_INFINITY);
  });
});
