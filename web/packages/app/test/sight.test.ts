import { describe, expect, it } from 'vitest';
import { holdSight, openFacing, planSight, siteSightRings, type Sight } from '../src/composition/sight.js';
import { seenThrough } from '../src/surface-materials.js';
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

  it('reads a made place\'s plan from the boxes its drawing draws across eye height, turned as they are drawn', () => {
    // Site millimetres are x east and y north. A shed's west wall in two pieces with a door between
    // (each 2.4 m long, 20 cm thick, 3 m high, laid north to south by a quarter turn), the lintel
    // over the door, a north wall laid east to west, a crate 1.2 m high, the ground, a roof and the
    // shed's own outline.
    const slot = (primitive: string, positionMm: [number, number, number], yawQuarterTurns: number, boxMm: [number, number, number]) =>
      ({ primitive, positionMm, yawQuarterTurns, boxMm });
    const drawing = { slots: [
      slot('box', [35_400, 14_700, 0], 1, [2400, 200, 3000]),
      slot('box', [35_400, 18_300, 0], 1, [2400, 200, 3000]),
      slot('box', [35_400, 16_500, 2100], 1, [1200, 200, 900]),
      slot('box', [37_400, 19_400, 0], 0, [4000, 200, 3000]),
      slot('box', [30_000, 16_500, 0], 0, [1000, 1000, 1200]),
      slot('plane', [40_000, 30_000, 0], 0, [80_000, 60_000, 0]),
      slot('gable', [37_400, 16_500, 3000], 0, [4200, 6200, 1500]),
      slot('none', [37_400, 16_500, 0], 0, [4000, 6000, 3000]),
    ] };
    const rings = siteSightRings(drawing, 1600);
    // The three walls: east and south, so north 13,500 to 15,900 is south -15,900 to -13,500.
    expect(rings).toEqual([
      [[35_300, -15_900], [35_500, -15_900], [35_500, -13_500], [35_300, -13_500]],
      [[35_300, -19_500], [35_500, -19_500], [35_500, -17_100], [35_300, -17_100]],
      [[35_400, -19_500], [39_400, -19_500], [39_400, -19_300], [35_400, -19_300]],
    ]);
    // A box that only reaches the height, or only starts at it, stands across it.
    expect(siteSightRings({ slots: [slot('box', [0, 0, 0], 0, [100, 100, 1600]), slot('box', [0, 0, 1600], 0, [100, 100, 10])] }, 1600)).toHaveLength(2);
    // From 5 m west of the shed, in the world's metres (z is south): someone inside is seen through
    // the door, between the two pieces, and not through the wall beside it.
    const sight = planSight(rings, 500);
    const eye = { x: 30.4, z: -16.5 };
    expect(sight.sees(eye, { x: 37.4, z: -16.5 })).toBe(true);
    expect(sight.sees({ x: 30.4, z: -14.7 }, { x: 37.4, z: -14.7 })).toBe(false);
    // The crate, 1.2 m high, hides nobody behind it.
    expect(sight.sees({ x: 28, z: -16.5 }, { x: 32, z: -16.5 })).toBe(true);
  });

  it('leaves out a wall the eye sees through: someone behind a pavilion\'s glass is seen and can be clicked', () => {
    // A pavilion's glass wall laid north to south (12 m long, 20 cm thick, 4 m high) with a brick wall
    // beside it, and someone 10 m east of an eye 5 m west of them.
    const slot = (lookRole: string, positionMm: [number, number, number]) =>
      ({ primitive: 'box', lookRole, positionMm, yawQuarterTurns: 1, boxMm: [12_000, 200, 4000] as [number, number, number] });
    const drawing = { slots: [slot('wall.glass', [20_000, 0, 0]), slot('wall.brick', [20_000, 20_000, 0])] };
    // The catalog in the page says glass is seen through, brick and a family's default are not.
    expect(['wall.glass', 'wall.brick', 'wall.default'].map(seenThrough)).toEqual([true, false, false]);
    expect(siteSightRings(drawing, 1600)).toHaveLength(2);
    const sight = planSight(siteSightRings(drawing, 1600, undefined, seenThrough), 500);
    expect(sight.sees({ x: 15, z: 0 }, { x: 25, z: 0 })).toBe(true);
    expect(sight.reach([15, 1.6, 0], [1, 0, 0])).toBe(Number.POSITIVE_INFINITY);
    // The brick wall still hides the one behind it.
    expect(sight.sees({ x: 15, z: -20 }, { x: 25, z: -20 })).toBe(false);
    expect(sight.reach([15, 1.6, -20], [1, 0, 0])).toBeCloseTo(4.9);
  });

  it('keeps a wall the eye sees through a wall to stand facing: someone by a glass wall faces as by any wall', () => {
    // A glass wall north to south 1 m east of where someone stands, and the same plan with it as an ordinary wall.
    const glass: [number, number][][] = [[[1000, -6000], [1200, -6000], [1200, 6000], [1000, 6000]]];
    const seenThrough = planSight([], 500, glass);
    const walled = planSight(glass, 500);
    // The eye and a click pass it; a body faces and stands by it as by a wall.
    expect(seenThrough.reach([0, 1.6, 0], [1, 0, 0])).toBe(Number.POSITIVE_INFINITY);
    expect(seenThrough.wallReach!([0, 1.6, 0], [1, 0, 0])).toBeCloseTo(walled.reach([0, 1.6, 0], [1, 0, 0]));
    expect(seenThrough.sees({ x: 0, z: 0 }, { x: 3, z: 0 })).toBe(true);
    for (const [x, z] of [[0, 0], [0.5, 2], [0.2, -3], [0.8, 5]] as const) {
      for (const key of ['a', 'resident-7', 'b']) expect(openFacing(seenThrough, { x, z }, key)).toBe(openFacing(walled, { x, z }, key));
    }
    // A plan with nothing seen through answers facing by its own reach.
    expect(planSight(glass, 500).wallReach).toBeUndefined();
    // Held on the session, both parts go to the world's sight.
    const session = { worldSight: null as Sight | null };
    holdSight(session, 500)([], glass);
    expect(session.worldSight!.wallReach!([0, 1.6, 0], [1, 0, 0])).toBeCloseTo(1);
  });

  it('holds no sight for a world about to be mounted, and the world\'s own once it states its plan', () => {
    const before: Sight = { sees: () => false, reach: () => 0 };
    const session: { worldSight: Sight | null } = { worldSight: before };
    const standing = holdSight(session, 500);
    // The world before is not this one's answer.
    expect(session.worldSight).toBeNull();
    standing([HOUSE]);
    expect(session.worldSight!.sees(eye, { x: 0, z: 40 })).toBe(false);
    expect(session.worldSight!.sees(eye, { x: 0, z: 20.3 })).toBe(true);
    expect(session.worldSight!.reach([0, 1.6, 0], [0, 0, 1])).toBeCloseTo(20, 9);
  });

  it('hides nothing where the plan is empty', () => {
    const open = planSight([], MARGIN_MM);
    expect(open.sees(eye, { x: 0, z: 40 })).toBe(true);
    expect(open.reach([0, 1.6, 0], [0, 0, 1])).toBe(Number.POSITIVE_INFINITY);
  });
});

describe('which way someone standing faces where nothing says', () => {
  // A crowd facing looks along (-sin, -cos), x east and z south.
  const reachAhead = (plan: Sight, at: { x: number; z: number }, facing: number) =>
    plan.reach([at.x, 1.6, at.z], [-Math.sin(facing), 0, -Math.cos(facing)]);

  it('never faces a wall close ahead, faces the same way on every load, and neighbours differ', () => {
    // 40 cm south of the house's far wall, so north (a crowd's facing 0) is into it, as a town's
    // footway line lies before a shopfront.
    const at = { x: 0, z: 30.4 };
    expect(reachAhead(sight, at, 0)).toBeCloseTo(0.4, 9);
    const ways = new Set<number>();
    for (let n = 0; n < 40; n += 1) {
      const facing = openFacing(sight, at, `resident-${n}`);
      expect(reachAhead(sight, at, facing)).toBeGreaterThanOrEqual(3);
      expect(openFacing(sight, at, `resident-${n}`)).toBe(facing);
      ways.add(Math.round(facing * 1000));
    }
    // Along the wall either way, away from it, and the slants away from it: never one heading for all.
    expect(ways.size).toBeGreaterThan(2);
  });

  it('stops a line from a point on a building\'s own line where it runs into the building, not out of it', () => {
    // On the house's far wall, as a town's walking line can lie on a frontage's ring.
    const at = { x: 0, z: 30 };
    // Its ring wound either way round, as a plan may state it.
    for (const plan of [sight, planSight([[...HOUSE].reverse(), POST], MARGIN_MM)]) {
      expect(reachAhead(plan, at, 0)).toBe(0);
      expect(reachAhead(plan, at, Math.PI)).toBe(Number.POSITIVE_INFINITY);
      // Along it, to the house's corner.
      expect(reachAhead(plan, at, Math.PI / 2)).toBeCloseTo(5, 9);
      expect(plan.sees(at, { x: 0, z: 24 })).toBe(false);
      expect(plan.sees(at, { x: 0, z: 36 })).toBe(true);
      // Never turned into the house, nor slanting into it.
      for (let n = 0; n < 40; n += 1) expect(Math.cos(openFacing(plan, at, `resident-${n}`))).toBeLessThan(1e-9);
    }
  });

  it('keeps a way it is handed while that way is open, and turns from it where a wall stands close ahead', () => {
    // 40 cm before the house's wall, as a walk up a footway to a shopfront ends: north is into it.
    const at = { x: 0, z: 30.4 };
    for (const key of ['a', 'resident-7', 'b']) {
      // Walked north into the wall: turned to the open way nearest north, along the wall one way or
      // the other, never out to the street behind them while a way along it is open.
      const turned = openFacing(sight, at, key, undefined, 0);
      expect(reachAhead(sight, at, turned)).toBeGreaterThanOrEqual(3);
      expect(Math.abs(Math.sin(turned))).toBeCloseTo(1, 9);
      // Walked a little east of north: the open way along the wall to the east side is the nearer.
      expect(Math.sin(openFacing(sight, at, key, undefined, -0.2))).toBeCloseTo(-1, 9);
      // Walked south, away from it, or a little off south, between the eight ways: kept exactly.
      expect(openFacing(sight, at, key, undefined, Math.PI)).toBe(Math.PI);
      expect(openFacing(sight, at, key, undefined, Math.PI - 0.3)).toBe(Math.PI - 0.3);
    }
  });

  it('faces the most open way where every way is closer than the rule', () => {
    // A booth 4 m east to west and 2 m north to south around the one standing in it.
    const booth = planSight([[[-2000, -1000], [2000, -1000], [2000, 1000], [-2000, 1000]]], MARGIN_MM);
    for (const key of ['a', 'b', 'c', 'd', 'e']) {
      expect(reachAhead(booth, { x: 0, z: 0 }, openFacing(booth, { x: 0, z: 0 }, key))).toBeCloseTo(2, 9);
    }
  });

  it('turns by the rule it is handed: its distance and how many ways', () => {
    const booth = planSight([[[-2000, -1000], [2000, -1000], [2000, 1000], [-2000, 1000]]], MARGIN_MM);
    // Four ways a quarter turn apart, any open a metre: each is, so the one each key draws stands.
    const facings = ['a', 'b', 'c', 'd', 'e', 'f'].map((key) => openFacing(booth, { x: 0, z: 0 }, key, { openMm: 1000, ways: 4 }));
    for (const facing of facings) expect(Math.abs(Math.sin(2 * facing))).toBeLessThan(1e-9);
    expect(new Set(facings.map((facing) => Math.round(facing * 1000))).size).toBeGreaterThan(1);
  });
});
