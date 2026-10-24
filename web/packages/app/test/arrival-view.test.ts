import { describe, expect, it } from 'vitest';
import {
  arrivalView, crosses, frontsInView, lowOf, nearFaceShare, nearestInWedge, nearestSeatInFan, openDistance, parkedFootprint, seatsOf, viewLife, viewOpenness,
  waterInView, type LifeViewRule, type OpenViewRule, type SeaSight, type SightBlocker,
} from '../src/composition/arrival-view.js';
import { FIRST_VIEW_DEFAULTS } from '../src/town-first-view.js';

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

  it('keeps the served spot over one whose car in the way is only a little farther off', () => {
    // One spot a step east to stand on; the same car is in the way from both, 376 mm farther from it.
    const two = (east: number, south: number) => south === 0 && (east === 0 || east === 1_500);
    const kept = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [car], ground: two });
    expect(kept).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    // A rule that takes any farther car takes the step.
    const anyFarther = { ...RULE, placed: { ...FIRST_VIEW_DEFAULTS.placed, parkedFartherMm: 0 } };
    expect(arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [car], ground: two, open: anyFarther }))
      .toMatchObject({ eastMm: 1_500, southMm: 0, moved: true });
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

/*
 * A town with nothing placed in it. The street here runs east and west: the wall opposite stands
 * 16 m to the north of where a person arrives and the wall behind 3 m to the south, each a long
 * rectangle, and a person may stand on the footway band 2.5 m either side of the arrival's line.
 * The rule is written here, not read from the catalog, so each expectation is geometry on these
 * figures: a view turned 60 degrees from north looks (sin 60, -cos 60) or (-sin 60, -cos 60).
 */
const RULE: OpenViewRule = {
  slant: Math.PI / 3, fanHalf: (40 * Math.PI) / 180, sightLines: 9, reachMm: 40_000, faceMm: 4_000,
  backStepMm: 750, backMaximumMm: 2_250, alongStepMm: 1_500, alongMaximumMm: 6_000, tie: 0.02,
};
const opposite: SightBlocker = [[-200_000, -40_000], [200_000, -40_000], [200_000, -16_000], [-200_000, -16_000]];
const behind: SightBlocker = [[-200_000, 3_000], [200_000, 3_000], [200_000, 30_000], [-200_000, 30_000]];
const footway = (_east: number, south: number) => Math.abs(south) <= 2_500;
/** A square post of `side` millimetres centred on a plan point. */
const post = (east: number, south: number, side = 300): SightBlocker => [
  [east - side / 2, south - side / 2], [east + side / 2, south - side / 2],
  [east + side / 2, south + side / 2], [east - side / 2, south + side / 2],
];
/** Which way a view looks, east and south: forward is (-sin yaw, -cos yaw). */
const looks = (yaw: number) => [-Math.sin(yaw), -Math.cos(yaw)] as const;

describe('how far a sight line runs', () => {
  it('stops at the first edge in its way and runs its whole reach where nothing is', () => {
    // North from the arrival, the wall opposite is 16 m off; south, the wall behind 3 m.
    expect(openDistance([0, 0], [0, -1], [opposite, behind], 40_000)).toBeCloseTo(16_000, 6);
    expect(openDistance([0, 0], [0, 1], [opposite, behind], 40_000)).toBeCloseTo(3_000, 6);
    // East along the street nothing stands: the reach.
    expect(openDistance([0, 0], [1, 0], [opposite, behind], 40_000)).toBe(40_000);
    // A post 10 m east, 300 mm wide: its near face is 9.85 m away, and nothing lies behind the eye.
    expect(openDistance([0, 0], [1, 0], [post(10_000, 0)], 40_000)).toBeCloseTo(9_850, 6);
    expect(openDistance([0, 0], [-1, 0], [post(10_000, 0)], 40_000)).toBe(40_000);
  });

  it('judges a view by a fan of lines, and marks down one with something in its face', () => {
    const one: OpenViewRule = { ...RULE, sightLines: 1 };
    // One line straight at the wall opposite: 16 m of a 40 m reach.
    expect(viewOpenness([0, 0], [0, -1], [opposite], one)).toBeCloseTo(0.4, 9);
    // A post 2 m ahead is in the face (nearer than 4 m): a quarter of its 1.85 m of 40.
    expect(viewOpenness([0, 0], [0, -1], [post(0, -2_000)], one)).toBeCloseTo(1_850 / 40_000 / 4, 9);
    // A post 2 m off on the fan's outermost line (40 degrees from where the view looks) is at the
    // edge of the frame, not in the face: eight of the nine lines still run their whole reach.
    const aside = post(2_000 * Math.cos((40 * Math.PI) / 180), 2_000 * Math.sin((40 * Math.PI) / 180));
    expect(viewOpenness([0, 0], [1, 0], [aside], RULE)).toBeGreaterThan(8 / 9);
    expect(viewOpenness([0, 0], [1, 0], [aside], RULE)).toBeLessThan(1);
    // Looking along an empty street every line of the fan is open or long: more open than across.
    expect(viewOpenness([0, 0], [1, 0], [opposite, behind], RULE)).toBeGreaterThan(viewOpenness([0, 0], [0, -1], [opposite, behind], RULE));
  });
});

describe('the first view of a town with nothing placed', () => {
  const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };

  it('looks the way the entry says where no rule is handed, as before', () => {
    const view = arrivalView({ ...town, blockers: [opposite, behind] });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(view.yaw).toBeCloseTo(0, 9);
    // Even with a post 3 m dead ahead: with nothing placed there is no sight line to keep clear.
    const posted = arrivalView({ ...town, ground: everywhere, blockers: [opposite, behind, post(0, -3_000)] });
    expect(posted).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(posted.yaw).toBeCloseTo(0, 9);
  });

  it('looks along the street at a slant, never straight across at the wall opposite', () => {
    const view = arrivalView({ ...town, blockers: [opposite, behind], open: RULE });
    const [east, south] = looks(view.yaw);
    // Turned 60 degrees from north, one way or the other: half its look is still across the road.
    expect(Math.abs(east)).toBeCloseTo(Math.sin(Math.PI / 3), 9);
    expect(south).toBeCloseTo(-Math.cos(Math.PI / 3), 9);
  });

  it('stands one step back from the kerb, off the line people walk, and no farther for a hair more view', () => {
    const view = arrivalView({ ...town, blockers: [opposite, behind], open: RULE });
    expect(view.moved).toBe(true);
    expect(view.eastMm).toBeCloseTo(0, 6);
    expect(view.southMm).toBeCloseTo(750, 6);
    // Where there is no ground behind the line, it stays on it.
    const kerbOnly = arrivalView({ ...town, ground: (_east, south) => south <= 0 && south >= -2_500, blockers: [opposite, behind], open: RULE });
    expect(kerbOnly.southMm).toBeLessThanOrEqual(0);
    // With no worth stated for standing off the line, nothing takes it off the line.
    expect(arrivalView({ ...town, blockers: [opposite, behind], open: { ...RULE, offLineBonus: 0 } })).toMatchObject({ southMm: 0, moved: false });
  });

  it('turns the other way along the street from a lamp post in its face', () => {
    // A post 2.5 m along the eastward slant from the spot one step back: dead ahead that way.
    const lamp = post(2_500 * Math.sin(Math.PI / 3), 750 - 2_500 * Math.cos(Math.PI / 3));
    const view = arrivalView({ ...town, blockers: [opposite, behind, lamp], open: RULE });
    const forward = looks(view.yaw);
    // Whatever it chose, nothing stands within 4 m dead ahead of it.
    expect(openDistance([view.eastMm, view.southMm], forward, [opposite, behind, lamp], 40_000)).toBeGreaterThan(4_000);
    // And it did not have to move along the footway for that: the other way was open.
    expect(forward[0]).toBeLessThan(0);
  });

  it('steps along the footway either way from a spot with a post in its face both ways', () => {
    // A post 2.5 m along each slant from the served spot, and a footway that runs west only, no
    // wider than the kerb line: the one open view is from a step or more to the west.
    const posts = [1, -1].map((way) => post(way * 2_500 * Math.sin(Math.PI / 3), -2_500 * Math.cos(Math.PI / 3)));
    const westward = (east: number, south: number): boolean => Math.abs(south) < 100 && east <= 0 && east >= -6_000;
    const blockers = [opposite, behind, ...posts];
    // Positive control: from the served spot each way has its post within 4 m dead ahead.
    for (const way of [1, -1]) {
      expect(openDistance([0, 0], [way * Math.sin(Math.PI / 3), -Math.cos(Math.PI / 3)], blockers, 40_000)).toBeLessThan(4_000);
    }
    const view = arrivalView({ ...town, ground: westward, blockers, open: RULE });
    expect(view.moved).toBe(true);
    expect(view.eastMm).toBeLessThan(0);
    expect(view.southMm).toBeCloseTo(0, 6);
    expect(openDistance([view.eastMm, view.southMm], looks(view.yaw), blockers, 40_000)).toBeGreaterThan(4_000);
  });

  it('looks past a parked car as it looks past a post', () => {
    // Parked at the far kerb, 6 m along the eastward slant: in the middle of that view, nearer than
    // anything the westward view holds.
    const parked = parkedFootprint({
      frontAxleMm: [3_000 + 1_400, 1_500], rearAxleMm: [3_000 - 1_400, 1_500],
      dimensionsMm: { width: 1_800, frontOverhang: 800, rearOverhang: 900 },
    })!;
    const view = arrivalView({ ...town, parked: [parked], blockers: [opposite, behind], open: RULE });
    expect(looks(view.yaw)[0]).toBeLessThan(0);
  });
});

describe('the first view of a dressed town, with what else stands at eye height', () => {
  it('steps along the footway past a trunk between the arrival and the scene', () => {
    const trunk = post(0, -6_000);
    const served = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [], ground: everywhere });
    expect(served.moved).toBe(false);
    // The rule for a town with nothing placed changes nothing where things are placed.
    expect(arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [], ground: everywhere, open: RULE })).toEqual(served);
    const view = arrivalView({ eastMm: 0, southMm: 0, facing: [0, -1], targets: scene, parked: [], ground: everywhere, blockers: [trunk] });
    expect(view.moved).toBe(true);
    // From where it stands, the line to the scene's middle (0, -12 m) runs clear of the trunk.
    const reach = Math.hypot(0 - view.eastMm, -12_000 - view.southMm);
    const toward: [number, number] = [(0 - view.eastMm) / reach, (-12_000 - view.southMm) / reach];
    expect(openDistance([view.eastMm, view.southMm], toward, [trunk], reach)).toBe(reach);
  });

  it('never stands on a placed thing to see it, nor nearer than the rule keeps a thing from the feet', () => {
    // A well placed on the footway 6 m east of the arrival, on a spot the view would try, with a post
    // just this side of it: every nearer spot along the footway sees the post, not the well. A spot
    // on the well itself sees nothing of it, and would face nowhere.
    const well: [number, number][] = [[6_000, 0]];
    const footwayOnly = (_east: number, south: number) => south === 0;
    const view = arrivalView({
      eastMm: 0, southMm: 0, facing: [0, -1], targets: well, parked: [], ground: footwayOnly, blockers: [post(5_000, 0)],
    });
    expect(view.moved).toBe(true);
    expect(Number.isFinite(view.yaw)).toBe(true);
    expect(view).toMatchObject({ eastMm: 7_500, southMm: 0 });
    // Under a rule that keeps a seat or a door from counting nearer than 6 m, a thing is not seen
    // from nearer either: the view stands back along the footway until the well is 6 m off or more
    // (with nothing kept clear dead ahead, so that rule alone decides).
    const kept = arrivalView({
      eastMm: 0, southMm: 0, facing: [0, -1], targets: well, parked: [], ground: footwayOnly, blockers: [post(5_000, 0)],
      open: { ...LIVELY, life: { ...LIFE, leastMm: 6_000, centreFloorMm: 0 } },
    });
    expect(Math.hypot(kept.eastMm - 6_000, kept.southMm)).toBeGreaterThanOrEqual(6_000);
    expect(Number.isFinite(kept.yaw)).toBe(true);
  });
});

/*
 * The same street under a rule that judges a view by the town's life (version 2 of the catalog),
 * written here and not read from the catalog: a seat is worth four doors, each counts whole to 25 m
 * and fades to nothing at 60 m, dead ahead is 12 degrees either side, and nothing may stand in it
 * nearer than 10 m.
 */
const DEGREE = Math.PI / 180;
const LIFE: LifeViewRule = {
  nearMm: 25_000, farMm: 60_000, leastMm: 0, seatWeight: 4, tie: 0.5, sightMarginMm: 500,
  centreHalf: 12 * DEGREE, centreFloorMm: 10_000, seatTopMinimumMm: 350, seatTopMaximumMm: 600, seatSpanMinimumMm: 400,
};
const LIVELY = { ...RULE, faceMm: 0, life: LIFE };
/** The street closed 30 m to the west by a building across it: the west is the less open way. */
const westEnd: SightBlocker = [[-31_000, -16_000], [-30_000, -16_000], [-30_000, 3_000], [-31_000, 3_000]];
/**
 * A wing 20 m to the east that juts 10 m into the street from the far frontage: the east is the less
 * open way, and a sight line along the near frontage still runs past it.
 */
const eastWing: SightBlocker = [[20_000, -16_000], [21_000, -16_000], [21_000, -6_000], [20_000, -6_000]];

describe('what stands dead ahead', () => {
  it('is the nearest part of anything inside the wedge, however thin, and nothing outside it', () => {
    // A post 300 mm wide 6 m north: its near face is 5.85 m off.
    expect(nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [post(0, -6_000)])).toBeCloseTo(5_850, 6);
    // A signpost 60 mm wide, 8 m off and 5 degrees from where the view looks, lies between the sight
    // lines a fan ten degrees apart casts (positive control: the middle line runs past it), and is found.
    const sign = post(8_000 * Math.sin(5 * DEGREE), -8_000 * Math.cos(5 * DEGREE), 60);
    expect(openDistance([0, 0], [0, -1], [sign], 40_000)).toBe(40_000);
    const found = nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [sign]);
    expect(found).toBeGreaterThan(8_000 - 43);
    expect(found).toBeLessThan(8_000);
    // The same post 20 degrees off either way is at the side of the frame, and one behind the eye is not ahead.
    for (const side of [1, -1]) {
      const aside = post(side * 8_000 * Math.sin(20 * DEGREE), -8_000 * Math.cos(20 * DEGREE), 60);
      expect(nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [aside])).toBe(Infinity);
      // And 5 degrees off either way it is found.
      const near = post(side * 8_000 * Math.sin(5 * DEGREE), -8_000 * Math.cos(5 * DEGREE), 60);
      expect(nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [near])).toBeLessThan(8_000);
    }
    expect(nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [post(0, 6_000)])).toBe(Infinity);
  });

  it('is where a wall first enters the wedge, not where the middle line meets it', () => {
    // Straight at the wall opposite: 16 m.
    expect(nearestInWedge([0, 0], [0, -1], 12 * DEGREE, [opposite])).toBeCloseTo(16_000, 6);
    // Turned 60 degrees from it, the wedge spans 48 to 72 degrees from north: the wall is nearest
    // along its 48 degree edge, 16 m / cos 48, nearer than along the middle line (16 m / cos 60).
    const slanted = nearestInWedge([0, 0], [Math.sin(60 * DEGREE), -Math.cos(60 * DEGREE)], 12 * DEGREE, [opposite]);
    expect(slanted).toBeCloseTo(16_000 / Math.cos(48 * DEGREE), 6);
    expect(slanted).toBeLessThan(32_000);
  });
});

describe('a town\'s seats, found by shape', () => {
  const part = (alongMm: number, leftMm: number, bottomMm: number, sizeAlongMm: number, sizeLeftMm: number, heightMm: number) =>
    ({ alongMm, leftMm, bottomMm, sizeAlongMm, sizeLeftMm, heightMm });

  it('are the parts at sitting height that are wide and deep enough, and no leg, back, bin or cap', () => {
    const bench = {
      eastMm: 5_000, southMm: -2_000, facing: [1, 0] as const,
      // A board with its top at 480 mm, a back above it, and two legs under it whose tops are at 420 mm.
      parts: [part(0, 0, 420, 1_800, 450, 60), part(0, -200, 480, 1_800, 60, 420), part(-800, 0, 0, 60, 450, 420), part(800, 0, 0, 60, 450, 420)],
    };
    const bin = { eastMm: 9_000, southMm: -2_000, facing: [1, 0] as const, parts: [part(0, 0, 0, 520, 520, 1_000)] };
    const bollard = { eastMm: 11_000, southMm: -2_000, facing: [1, 0] as const, parts: [part(0, 0, 0, 160, 160, 450)] };
    // A plinth 150 mm high is wide and deep enough, and too low to be a seat.
    const plinth = { eastMm: 13_000, southMm: -2_000, facing: [1, 0] as const, parts: [part(0, 0, 0, 800, 800, 150)] };
    expect(seatsOf([bench, bin, bollard, plinth], LIFE)).toEqual([[5_000, -2_000]]);
  });

  it('are placed where their furniture faces: ahead is its direction, left is to its left', () => {
    // Facing south, a seat 1 m ahead of the base and 0.5 m to its left is 1 m south and 0.5 m east.
    const ledge = { eastMm: 10_000, southMm: 20_000, facing: [0, 3] as const, parts: [part(1_000, 500, 0, 600, 600, 450)] };
    const [seat] = seatsOf([ledge], LIFE);
    expect(seat![0]).toBeCloseTo(10_500, 9);
    expect(seat![1]).toBeCloseTo(21_000, 9);
  });
});

describe('how alive a view is', () => {
  const east = [1, 0] as const;
  const alive = (life: { seats?: [number, number][]; doors?: [number, number][] }, rings: SightBlocker[] = []) =>
    viewLife([0, 0], east, { seats: life.seats ?? [], doors: life.doors ?? [] }, rings, LIVELY);

  it('counts a near door as one and a near seat as the rule\'s many, and fades each with distance', () => {
    expect(alive({ doors: [[10_000, 0]] })).toBe(1);
    expect(alive({ seats: [[10_000, 0]] })).toBe(4);
    expect(alive({ doors: [[25_000, 0]] })).toBe(1);
    // Half way from 25 m to 60 m counts half; at and beyond 60 m, nothing.
    expect(alive({ doors: [[42_500, 0]] })).toBeCloseTo(0.5, 9);
    expect(alive({ seats: [[42_500, 0]] })).toBeCloseTo(2, 9);
    expect(alive({ doors: [[61_000, 0]] })).toBe(0);
    expect(alive({ doors: [[10_000, 0]], seats: [[12_000, 1_000]] })).toBe(5);
  });

  it('counts what lies inside the fan and nothing beside or behind it', () => {
    const at = (degrees: number): [number, number] => [10_000 * Math.cos(degrees * DEGREE), 10_000 * Math.sin(degrees * DEGREE)];
    expect(alive({ doors: [at(35)] })).toBe(1);
    expect(alive({ doors: [at(-35)] })).toBe(1);
    expect(alive({ doors: [at(45)] })).toBe(0);
    expect(alive({ doors: [at(180)] })).toBe(0);
  });

  it('counts a door on its own wall and not one hidden behind another', () => {
    const front: SightBlocker = [[10_000, -5_000], [12_000, -5_000], [12_000, 5_000], [10_000, 5_000]];
    // The door's threshold is in the face of the building it belongs to, here 100 mm behind the
    // base ring's line: the sight line ends on its own building within the margin, and it counts.
    expect(alive({ doors: [[10_100, 0]] }, [front])).toBe(1);
    // A door a metre inside that building is behind its wall, not in it.
    expect(alive({ doors: [[11_000, 0]] }, [front])).toBe(0);
    // A wall a metre nearer hides the door; it does not hide a seat on the near side of it.
    const screen: SightBlocker = [[9_000, -5_000], [9_100, -5_000], [9_100, 5_000], [9_000, 5_000]];
    expect(alive({ doors: [[10_100, 0]] }, [front, screen])).toBe(0);
    expect(alive({ seats: [[8_000, 0]] }, [front, screen])).toBe(4);
  });
});

describe('the first view of a town with nothing placed, chosen by its life', () => {
  const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
  const street = [opposite, behind];

  it('looks the way along the street its seats are', () => {
    for (const side of [1, -1]) {
      const view = arrivalView({ ...town, blockers: street, open: LIVELY, life: { seats: [[side * 12_000, -1_500]], doors: [] } });
      expect(Math.sign(looks(view.yaw)[0])).toBe(side);
      // Still a slant of 60 degrees from straight across, never straight at the wall or the seat.
      expect(looks(view.yaw)[1]).toBeCloseTo(-Math.cos(Math.PI / 3), 9);
    }
  });

  it('keeps its middle third clear under version 5, not dead ahead alone', () => {
    const life = { seats: [[12_000, -1_500]] as [number, number][], doors: [] };
    // A post on the footway 6 m off, 17 degrees from the middle of the view the seat turns it to: outside
    // dead ahead (12 degrees), inside the middle third (23).
    const blockers = [...street, post(5_846, -1_350)];
    const third = (view: { eastMm: number; southMm: number; yaw: number }) =>
      nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), 23 * DEGREE, blockers);
    // Positive control: tested dead ahead alone, the view keeps the post under 10 m off in its middle third.
    expect(third(arrivalView({ ...town, blockers, open: LIVELY, life }))).toBeLessThan(LIFE.centreFloorMm);
    const view = arrivalView({ ...town, blockers, open: { ...LIVELY, middleThirdHalf: 23 * DEGREE }, life });
    expect(third(view)).toBeGreaterThanOrEqual(LIFE.centreFloorMm);
  });

  it('takes the livelier way even where the other is more open', () => {
    const blockers = [...street, westEnd];
    const life = { seats: [[-12_000, -1_500]] as [number, number][], doors: [] };
    // Positive control: by openness alone (version 1) this street is looked along eastward.
    expect(looks(arrivalView({ ...town, blockers, open: RULE }).yaw)[0]).toBeGreaterThan(0);
    expect(looks(arrivalView({ ...town, blockers, open: LIVELY, life }).yaw)[0]).toBeLessThan(0);
  });

  it('takes the more open of two equally alive ways', () => {
    // A door either way on the far frontage, mirrored: the same life both ways; the east is the less open.
    const life = { seats: [], doors: [[-10_000, -16_000], [10_000, -16_000]] as [number, number][] };
    const blockers = [...street, eastWing];
    // Positive control: the wing costs the eastward view more openness than the rule's tie.
    const eastward = [Math.sin(Math.PI / 3), -Math.cos(Math.PI / 3)] as const;
    const westward = [-Math.sin(Math.PI / 3), -Math.cos(Math.PI / 3)] as const;
    expect(viewOpenness([0, 0], westward, blockers, LIVELY) - viewOpenness([0, 0], eastward, blockers, LIVELY)).toBeGreaterThan(LIVELY.tie);
    expect(looks(arrivalView({ ...town, blockers, open: LIVELY, life }).yaw)[0]).toBeLessThan(0);
    // A door at the far edge of sight to the east, 52 m along the near frontage, makes the east the
    // livelier way by less than the tie's half a door (positive control), and does not outweigh that.
    const faint = { seats: [], doors: [...life.doors, [52_000, 3_000]] as [number, number][] };
    const more = viewLife([0, 0], eastward, faint, blockers, LIVELY) - viewLife([0, 0], westward, faint, blockers, LIVELY);
    expect(more).toBeGreaterThan(0.1);
    expect(more).toBeLessThan(LIFE.tie);
    expect(looks(arrivalView({ ...town, blockers, open: LIVELY, life: faint }).yaw)[0]).toBeLessThan(0);
  });

  it('opens as version 1 does where the town states no life and nothing stands near', () => {
    expect(arrivalView({ ...town, blockers: street, open: LIVELY })).toEqual(arrivalView({ ...town, blockers: street, open: RULE }));
  });

  it('never has a thin post dead ahead nearer than the floor where another spot or way has none', () => {
    // The seats are to the west. A signpost 60 mm wide stands 6 m from the spot one step back, 3
    // degrees off the westward slant: between the fan's sight lines, so openness does not see it.
    const life = { seats: [[-14_000, -1_500]] as [number, number][], doors: [] };
    const west = [-Math.sin(Math.PI / 3), -Math.cos(Math.PI / 3)] as const;
    const bearing = Math.PI / 3 + 3 * DEGREE;
    const sign = post(-6_000 * Math.sin(bearing), 750 - 6_000 * Math.cos(bearing), 60);
    const blockers = [...street, sign];
    // Positive controls: from that spot the post is dead ahead and near, and no sampled line meets it.
    expect(nearestInWedge([0, 750], west, LIFE.centreHalf, blockers)).toBeLessThan(6_100);
    expect(viewOpenness([0, 750], west, blockers, LIVELY)).toBe(viewOpenness([0, 750], west, street, LIVELY));
    const view = arrivalView({ ...town, blockers, open: LIVELY, life });
    expect(nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), LIFE.centreHalf, blockers)).toBeGreaterThanOrEqual(LIFE.centreFloorMm);
    // It still looks toward the seats: a step along the footway clears the post.
    expect(looks(view.yaw)[0]).toBeLessThan(0);
    expect([view.eastMm, view.southMm]).not.toEqual([0, 750]);
  });

  it('takes the view whose nearest thing dead ahead is farthest where every view has one', () => {
    // One spot to stand on, a post 5 m along the westward slant and one 7 m along the eastward.
    const posts = [post(-5_000 * Math.sin(Math.PI / 3), -5_000 * Math.cos(Math.PI / 3)), post(7_000 * Math.sin(Math.PI / 3), -7_000 * Math.cos(Math.PI / 3))];
    const view = arrivalView({
      ...town, ground: () => false, blockers: [...street, ...posts], open: LIVELY, life: { seats: [[-12_000, -1_500]], doors: [] },
    });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    // Eastward, though the seats are to the west: the nearer post is the worse.
    expect(looks(view.yaw)[0]).toBeGreaterThan(0);
  });

  it('is the same whatever is parked: parked vehicles do not enter the choice', () => {
    const life = { seats: [[12_000, -1_500]] as [number, number][], doors: [] };
    const bare = arrivalView({ ...town, blockers: street, open: LIVELY, life });
    // Parked at the kerb 6 m along the eastward slant, in the middle of the view the seats call for.
    const parked = parkedFootprint({
      frontAxleMm: [3_000 + 1_400, 1_500], rearAxleMm: [3_000 - 1_400, 1_500],
      dimensionsMm: { width: 1_800, frontOverhang: 800, rearOverhang: 900 },
    })!;
    // Positive control: under version 1 that car turns the view the other way.
    expect(looks(arrivalView({ ...town, parked: [parked], blockers: street, open: RULE }).yaw)[0]).toBeLessThan(0);
    expect(arrivalView({ ...town, parked: [parked], blockers: street, open: LIVELY, life })).toEqual(bare);
    expect(looks(bare.yaw)[0]).toBeGreaterThan(0);
  });

  it('changes nothing where things are placed', () => {
    const dressed = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: scene, parked: [car], ground: everywhere };
    expect(arrivalView({ ...dressed, open: LIVELY, life: { seats: [[-12_000, -1_500]], doors: [] } })).toEqual(arrivalView(dressed));
  });
});

/*
 * The same street under version 3 of the rule: a seat or a door nearer than 6 m does not count, and
 * a view with a seat that near inside its fan is passed over.
 */
const NOT_AT_ITS_FEET = { ...LIVELY, life: { ...LIFE, leastMm: 6_000 } };

describe('a seat at the viewer\'s feet', () => {
  const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
  const street = [opposite, behind];
  const eastward = [Math.sin(Math.PI / 3), -Math.cos(Math.PI / 3)] as const;

  it('is the nearest seat inside the fan, and none beside or behind it', () => {
    const at = (metres: number, degrees: number): [number, number] =>
      [metres * 1000 * Math.cos(degrees * DEGREE), metres * 1000 * Math.sin(degrees * DEGREE)];
    expect(nearestSeatInFan([0, 0], [1, 0], 40 * DEGREE, [at(9, 10), at(4, -30), at(7, 0)])).toBeCloseTo(4_000, 6);
    expect(nearestSeatInFan([0, 0], [1, 0], 40 * DEGREE, [at(3, 50), at(2, 180)])).toBe(Infinity);
    expect(nearestSeatInFan([0, 0], [1, 0], 40 * DEGREE, [])).toBe(Infinity);
  });

  it('does not count as life, where one a little farther does', () => {
    const alive = (seats: [number, number][], doors: [number, number][] = []) =>
      viewLife([0, 0], [1, 0], { seats, doors }, [], NOT_AT_ITS_FEET);
    expect(alive([[3_400, 0]])).toBe(0);
    expect(alive([[6_500, 0]])).toBe(4);
    expect(alive([], [[3_400, 0]])).toBe(0);
    expect(alive([], [[6_500, 0]])).toBe(1);
    // Under version 2, which states no least distance, the near seat counts whole.
    expect(viewLife([0, 0], [1, 0], { seats: [[3_400, 0]], doors: [] }, [], LIVELY)).toBe(4);
  });

  it('is not stood behind where another spot or way has none', () => {
    // The eastward benches: one 3.4 m along the eastward slant from the spot one step back, and
    // three more beyond it, 14 to 30 m off. To the west, one bench 20 m off.
    const near: [number, number] = [3_400 * eastward[0], 750 + 3_400 * eastward[1]];
    const life = { seats: [near, [14_000, -1_500], [22_000, -1_500], [30_000, -1_500], [-20_000, -1_500]] as [number, number][], doors: [] };
    // Positive control: version 2 looks east from where that bench is at its feet.
    const before = arrivalView({ ...town, blockers: street, open: LIVELY, life });
    expect(looks(before.yaw)[0]).toBeGreaterThan(0);
    expect(nearestSeatInFan([before.eastMm, before.southMm], looks(before.yaw), LIVELY.fanHalf, life.seats)).toBeLessThan(6_000);
    const view = arrivalView({ ...town, blockers: street, open: NOT_AT_ITS_FEET, life });
    expect(nearestSeatInFan([view.eastMm, view.southMm], looks(view.yaw), LIVELY.fanHalf, life.seats)).toBeGreaterThanOrEqual(6_000);
    // It still looks toward the many benches, from a few steps along the footway: the near one is
    // then a bench in the street, 6 m or more off, or behind the viewer.
    expect(looks(view.yaw)[0]).toBeGreaterThan(0);
    expect([view.eastMm, view.southMm]).not.toEqual([before.eastMm, before.southMm]);
  });

  it('is stood behind only where every view has one, and then the one with the most room', () => {
    // One spot to stand on; a bench 2 m along the eastward slant and one 4 m along the westward.
    const life = { seats: [[2_000 * eastward[0], 2_000 * eastward[1]], [-4_000 * eastward[0], 4_000 * eastward[1]]] as [number, number][], doors: [] };
    const view = arrivalView({ ...town, ground: () => false, blockers: street, open: NOT_AT_ITS_FEET, life });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(looks(view.yaw)[0]).toBeLessThan(0);
    // A post 5 m dead ahead to the west (half the centre floor) is less room than a bench 4 m off
    // (two thirds of the least distance): the view turns east only when the west is the tighter.
    const post5 = post(-5_000 * eastward[0], 5_000 * eastward[1]);
    const tighter = arrivalView({ ...town, ground: () => false, blockers: [...street, post5], open: NOT_AT_ITS_FEET, life });
    expect(looks(tighter.yaw)[0]).toBeLessThan(0);
    const post2 = post(-2_000 * eastward[0], 2_000 * eastward[1]);
    const tightest = arrivalView({ ...town, ground: () => false, blockers: [...street, post2], open: NOT_AT_ITS_FEET, life });
    expect(looks(tightest.yaw)[0]).toBeGreaterThan(0);
  });
});

/*
 * A town with things placed, judged by what its records stand at eye height under a rule that states
 * how near something may stand dead ahead (10 m here): the same street, where a person may stand
 * anywhere between the two walls.
 */
describe('the first view of a town with things placed, by what its records stand', () => {
  const street = [opposite, behind];
  const between = (_east: number, south: number) => south > -16_000 && south < 3_000;
  const dressed = { eastMm: 0, southMm: 0, facing: [0, -1] as const, parked: [], ground: between, blockers: street, open: LIVELY };

  it('keeps the middle third of a view of placed things clear under version 5', () => {
    // A post 5 m off, 17 degrees from the line to the scene: outside dead ahead, inside the middle third.
    const blockers = [...street, post(1_462, -4_782)];
    const third = (view: { eastMm: number; southMm: number; yaw: number }) =>
      nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), 23 * DEGREE, blockers);
    // Positive control: tested dead ahead alone, the served spot sees the scene with the post in its middle third.
    const before = arrivalView({ ...dressed, blockers, targets: scene });
    expect(before).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(third(before)).toBeLessThan(LIFE.centreFloorMm);
    const view = arrivalView({ ...dressed, blockers, targets: scene, open: { ...LIVELY, middleThirdHalf: 23 * DEGREE } });
    expect(view.moved).toBe(true);
    expect(third(view)).toBeGreaterThanOrEqual(LIFE.centreFloorMm);
  });

  it('keeps the served spot facing a scene across the street, with room before it', () => {
    const view = arrivalView({ ...dressed, targets: scene });
    expect(view).toMatchObject({ eastMm: 0, southMm: 0, moved: false });
    expect(view.yaw).toBeCloseTo(0, 6);
  });

  it('steps out across the street from a thing placed against the wall behind, to where no wall is near ahead', () => {
    const against: [number, number][] = [[0, 2_500]];
    // Positive control: facing it from the arrival, the wall behind it is 3 m off, dead ahead.
    expect(nearestInWedge([0, 0], [0, 1], LIFE.centreHalf, street)).toBeCloseTo(3_000, 6);
    const view = arrivalView({ ...dressed, targets: against });
    // The nearest spot out toward the street from which that wall is at least 10 m off: 7.5 m out.
    expect(view).toMatchObject({ eastMm: 0, southMm: -7_500, moved: true });
    expect(looks(view.yaw)[1]).toBeCloseTo(1, 9);
    expect(nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), LIFE.centreHalf, street)).toBeGreaterThanOrEqual(LIFE.centreFloorMm);
  });

  it('steps by the figures its rule states', () => {
    const against: [number, number][] = [[0, 2_500]];
    const placed = { stepMm: 2_000, stepsAlong: 8, stepsBack: 3, outReachMm: 12_000, parkedClearanceMm: 300, parkedFartherMm: 500 };
    // Steps of 2 m: the first spot out with the wall at least 10 m off is 8 m out, not 7.5.
    expect(arrivalView({ ...dressed, targets: against, open: { ...LIVELY, placed } })).toMatchObject({ eastMm: 0, southMm: -8_000, moved: true });
    // A reach of one step out finds no such spot, however far along: the town's own first view.
    const short = { ...LIVELY, placed: { ...placed, stepMm: 1_500, outReachMm: 1_500 } };
    expect(arrivalView({ ...dressed, targets: against, open: short })).toEqual(arrivalView({ ...dressed, targets: [], open: short }));
  });

  it('takes the town\'s own first view where what is placed stands inside a building', () => {
    const inside: [number, number][] = [[0, 5_000]];
    const life = { seats: [[12_000, -1_500]] as [number, number][], doors: [] };
    const view = arrivalView({ ...dressed, targets: inside, life });
    expect(view).toEqual(arrivalView({ ...dressed, targets: [], life }));
    // The town's own view looks along the street, toward its seat, not at the wall.
    expect(looks(view.yaw)[0]).toBeGreaterThan(0);
  });
});

describe('the first view of a town whose entry names a direction to look toward', () => {
  // Arriving on the seaward footway of a shore street, facing across it to the land side's fronts (north
  // here), the sea behind (south).
  const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
  const street = [opposite, behind];
  const SEAFRONT = {
    ...LIVELY,
    middleThirdHalf: 23 * DEGREE,
    seafront: {
      facingMost: Math.PI / 4, slant: 72 * DEGREE, frontHalf: 40 * DEGREE, frontStep: DEGREE,
      frontLinesLeast: 2, frontsLeast: 3, alongMaximumMm: 6_000,
      water: { band: 0.05, share: 1 / 3, halfHeight: 35 * DEGREE, stepMm: 500 },
    },
  };

  it('looks along the shore at the seafront slant where the arrival faces away from the sea, the way with a door in view', () => {
    for (const side of [1, -1]) {
      // A door on the land side's front across the street, one way along it.
      const life = { seats: [], doors: [[side * 20_000, -16_000]] as [number, number][] };
      const view = arrivalView({ ...town, blockers: street, open: SEAFRONT, life, toward: [0, 1_000] });
      expect(Math.sign(looks(view.yaw)[0])).toBe(side);
      // 72 degrees from straight across, not the rule's 60.
      expect(looks(view.yaw)[1]).toBeCloseTo(-Math.cos((72 * Math.PI) / 180), 9);
    }
  });

  it('turns the way with more of the town\'s doors in view, not toward a seat', () => {
    // A seat on the promenade 12 m east; two doors on the fronts across the street to the west.
    const life = { seats: [[12_000, 1_500]] as [number, number][], doors: [[-20_000, -16_000], [-24_000, -16_000]] as [number, number][] };
    // Positive control: version 4's view, by the town's life, turns east toward the seat (worth four doors).
    expect(looks(arrivalView({ ...town, blockers: street, open: LIVELY, life }).yaw)[0]).toBeGreaterThan(0);
    const view = arrivalView({ ...town, blockers: street, open: SEAFRONT, life, toward: [0, 1_000] });
    expect(looks(view.yaw)[0]).toBeLessThan(0);
    expect(looks(view.yaw)[1]).toBeCloseTo(-Math.cos(72 * DEGREE), 9);
  });

  it('takes the way with the most buildings\' fronts in view, before the town\'s doors', () => {
    // Across the street (16 m north): three narrow buildings to the east, one wide one to the west with two doors.
    const building = (west: number, east: number): SightBlocker => [[west, -16_000], [east, -16_000], [east, -30_000], [west, -30_000]];
    const fronts = [building(6_000, 14_000), building(14_000, 22_000), building(22_000, 30_000), building(-40_000, -6_000)];
    const life = { seats: [], doors: [[-10_000, -16_000], [-14_000, -16_000]] as [number, number][] };
    const seafront = { ...town, blockers: fronts, open: SEAFRONT, life, toward: [0, 1_000] as const };
    // Three fronts from the served spot looking east, one looking west.
    const east = [Math.sin(72 * DEGREE), -Math.cos(72 * DEGREE)] as const;
    const west = [-east[0], east[1]] as const;
    expect(frontsInView([0, 0], east, fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm)).toBe(3);
    expect(frontsInView([0, 0], west, fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm)).toBe(1);
    // Positive control: with no outlines handed, the doors choose: west.
    expect(looks(arrivalView(seafront).yaw)[0]).toBeLessThan(0);
    expect(looks(arrivalView({ ...seafront, fronts }).yaw)[0]).toBeGreaterThan(0);
  });

  it('counts a front only where enough sight lines meet it', () => {
    const building = (west: number, east: number): SightBlocker => [[west, -16_000], [east, -16_000], [east, -30_000], [west, -30_000]];
    // From the served spot looking east 18 degrees north, the sight lines a degree apart meet the fronts 16 m
    // north at whole degrees: a front 0.54 m wide between 45.5 and 46.5 degrees meets one, its neighbours many.
    const fronts = [building(-20_000, 15_180), building(15_180, 15_720), building(15_720, 60_000)];
    const east = [Math.sin(72 * DEGREE), -Math.cos(72 * DEGREE)] as const;
    expect(frontsInView([0, 0], east, fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm, 1)).toBe(3);
    expect(frontsInView([0, 0], east, fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm, 2)).toBe(2);
  });

  it('steps as far along the footway as its figure lets it to bring a third front into view', () => {
    // Across the street (16 m north), three buildings whose fronts meet at 2 m and 40 m east: from the served
    // spot the fan looking east reaches the fronts from 10 m along, so the first is out of it.
    const building = (west: number, east: number): SightBlocker => [[west, -16_000], [east, -16_000], [east, -30_000], [west, -30_000]];
    const fronts = [building(-20_000, 2_000), building(2_000, 40_000), building(40_000, 100_000)];
    const seafront = { ...town, blockers: fronts, fronts, life: { seats: [], doors: [] }, toward: [0, 1_000] as const };
    const count = (view: { eastMm: number; southMm: number; yaw: number }) =>
      frontsInView([view.eastMm, view.southMm], looks(view.yaw), fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm);
    // Positive control: within 6 m along no spot shows the third.
    expect(count(arrivalView({ ...seafront, open: SEAFRONT }))).toBe(2);
    const far = { ...SEAFRONT, seafront: { ...SEAFRONT.seafront, alongMaximumMm: 15_000 } };
    const view = arrivalView({ ...seafront, open: far });
    expect(count(view)).toBe(3);
    expect(view.eastMm).toBeLessThanOrEqual(-9_000);
  });

  it('is not moved for a fourth front where it shows three', () => {
    const building = (west: number, east: number): SightBlocker => [[west, -16_000], [east, -16_000], [east, -30_000], [west, -30_000]];
    // Three fronts in the fan from the served spot looking east; a fourth, ending 2 m east, from 9 m along.
    const fronts = [building(-20_000, 2_000), building(9_000, 20_000), building(20_000, 30_000), building(30_000, 100_000)];
    const far = { ...SEAFRONT, seafront: { ...SEAFRONT.seafront, alongMaximumMm: 15_000 } };
    const seafront = { ...town, blockers: fronts, fronts, life: { seats: [], doors: [] }, toward: [0, 1_000] as const, open: far };
    const count = (view: { eastMm: number; southMm: number; yaw: number }, least = 3) => Math.min(least,
      frontsInView([view.eastMm, view.southMm], looks(view.yaw), fronts, fronts, [1, 0], 40 * DEGREE, DEGREE, LIFE.farMm, 2));
    // Positive control: four fronts show from 9 m along.
    expect(count({ eastMm: -9_000, southMm: 0, yaw: Math.atan2(-Math.sin(72 * DEGREE), Math.cos(72 * DEGREE)) }, 4)).toBe(4);
    const view = arrivalView(seafront);
    expect(count(view)).toBe(3);
    expect(view.eastMm).toBeGreaterThan(-9_000);
  });

  it('passes over a view with a trunk or post nearer than the floor in its middle third, not dead ahead alone', () => {
    const life = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    // A lamp post on the footway 6 m east, on the line the arrival stands on: 18 degrees from the middle of
    // the view along the shore that way, outside dead ahead (12 degrees) and inside the middle third (23).
    const blockers = [...street, post(6_000, 0)];
    const third = (view: { eastMm: number; southMm: number; yaw: number }) =>
      nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), SEAFRONT.middleThirdHalf, blockers);
    // Positive control: tested dead ahead alone, the view taken looks east with the post under 10 m off in
    // its middle third (9 m, from 3 m west and a step back).
    const { middleThirdHalf: _third, ...sixth } = SEAFRONT;
    const before = arrivalView({ ...town, blockers, open: sixth, life, toward: [0, 1_000] });
    expect(looks(before.yaw)[0]).toBeGreaterThan(0);
    expect(third(before)).toBeLessThan(LIFE.centreFloorMm);
    const view = arrivalView({ ...town, blockers, open: SEAFRONT, life, toward: [0, 1_000] });
    expect(third(view)).toBeGreaterThanOrEqual(LIFE.centreFloorMm);
    // Still a seafront view: 72 degrees from straight across, one way or the other.
    expect(looks(view.yaw)[1]).toBeCloseTo(-Math.cos(72 * DEGREE), 9);
  });

  it('opens on version 4\'s view where the arrival does not face away from the named direction, or no seafront is stated', () => {
    const life = { seats: [[-12_000, -1_500]] as [number, number][], doors: [] };
    // Facing across the street with the sea to one side, or facing the sea: not a seafront arrival.
    for (const toward of [[1_000, 0], [0, -1_000]] as const) {
      expect(arrivalView({ ...town, blockers: street, open: SEAFRONT, life, toward }))
        .toEqual(arrivalView({ ...town, blockers: street, open: LIVELY, life }));
    }
    expect(arrivalView({ ...town, blockers: street, open: LIVELY, life, toward: [0, 1_000] }))
      .toEqual(arrivalView({ ...town, blockers: street, open: LIVELY, life }));
  });
});

describe('the open water a seafront view shows', () => {
  // Level land at the sea's level out to a straight shore `shoreMm` south of a person standing on it, the
  // sea's floor 1 m under its level beyond; an eye 1.6 m above the ground. At a 70 degree vertical field,
  // open water stands a twentieth of the frame's height below the horizon out to
  // 1.6 m / (2 tan 35 degrees x 0.05) = 22.85 m ahead.
  const WATER = { band: 0.05, halfHeight: 35 * DEGREE, stepMm: 500 };
  const coast = (shoreMm: number, ridge?: { fromMm: number; toMm: number; heightMm: number }): SeaSight => ({
    groundMm: (_east, south) => (ridge !== undefined && south >= ridge.fromMm && south <= ridge.toMm
      ? ridge.heightMm : south < shoreMm ? 0 : -1_000),
    levelMm: 0,
    eyeMm: 1_600,
  });
  const share = (sea: SeaSight, toward: readonly [number, number], rings: readonly SightBlocker[] = []) =>
    waterInView([0, 0], toward, sea, rings, 51 * DEGREE, DEGREE, WATER);

  it('is the share of the frame\'s width whose nearest open water stands far enough below the horizon', () => {
    expect(share(coast(4_000), [0, 1])).toBe(1);
    expect(share(coast(4_000), [0, -1])).toBe(0);
    // Along the shore, a column a degrees seaward of the middle meets the sea 4 m / sin a off, which stands
    // in the band while 4 m / sin a <= 22.85 m / cos a: from 9.93 degrees, so every column from 10 degrees out.
    expect(share(coast(4_000), [1, 0])).toBeCloseTo((Math.tan(51 * DEGREE) - Math.tan(10 * DEGREE)) / (2 * Math.tan(51 * DEGREE)), 9);
    // A sea beyond a wide field is a line at the foot of the sky: no column holds the band.
    expect(share(coast(60_000), [0, 1])).toBe(0);
    // Positive control for the next two: the sea 10 m off, looked straight at.
    expect(share(coast(10_000), [0, 1])).toBe(1);
  });

  it('counts no water the land nearer or a wall at eye height hides', () => {
    // A dune 6 m high from 2 m to 4 m out, the shore at 10 m.
    expect(share(coast(10_000, { fromMm: 2_000, toMm: 4_000, heightMm: 6_000 }), [0, 1])).toBe(0);
    const wall: SightBlocker = [[-200_000, 3_000], [200_000, 3_000], [200_000, 4_000], [-200_000, 4_000]];
    expect(share(coast(10_000), [0, 1], [wall])).toBe(0);
  });

  it('holds a seafront view to it, else opens on the town\'s own view', () => {
    // As above: arriving on the seaward footway facing north across the street, the sea to the south.
    const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
    const SEAFRONT = {
      ...LIVELY,
      middleThirdHalf: 23 * DEGREE,
      seafront: {
        facingMost: Math.PI / 4, slant: 86 * DEGREE, frontHalf: 51 * DEGREE, frontStep: DEGREE,
        frontLinesLeast: 2, frontsLeast: 3, alongMaximumMm: 6_000, water: { ...WATER, share: 1 / 3 },
      },
    };
    const life = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    const seafront = { ...town, blockers: [opposite], open: SEAFRONT, life, toward: [0, 1_000] as const };
    const own = arrivalView({ ...town, blockers: [opposite], open: SEAFRONT, life });
    // Positive control: with the sea 4 m off the view runs along the shore at the seafront slant, which the
    // town's own view (60 degrees) does not, and over a third of its width holds the band.
    const near = arrivalView({ ...seafront, sea: coast(4_000) });
    expect(looks(near.yaw)[1]).toBeCloseTo(-Math.cos(86 * DEGREE), 9);
    expect(looks(own.yaw)[1]).toBeCloseTo(-Math.cos(60 * DEGREE), 9);
    expect(waterInView([near.eastMm, near.southMm], looks(near.yaw), coast(4_000), [opposite], 51 * DEGREE, DEGREE, WATER))
      .toBeGreaterThanOrEqual(1 / 3);
    // The sea 60 m off: the town's own view, as for an arrival facing any other way.
    expect(arrivalView({ ...seafront, sea: coast(60_000) })).toEqual(own);
    // Handed no sea, a seafront view stands as chosen.
    expect(arrivalView(seafront)).toEqual(near);
  });
});

describe('the near faces at a first view\'s edges', () => {
  const FRAME = 51 * DEGREE;

  it('is the share of the frame\'s width in which something stands nearer than the near face', () => {
    // Facing north from the origin, a wall along the left 2 m off, running 10 m ahead. Within 4 m it reaches
    // from 30 degrees left of the middle (2 m across, 3.46 m ahead) out past the frame's edge.
    const wall: SightBlocker = [[-2_500, 1_000], [-2_000, 1_000], [-2_000, -10_000], [-2_500, -10_000]];
    expect(nearFaceShare([0, 0], [0, -1], [wall], FRAME, 4_000))
      .toBeCloseTo((Math.tan(FRAME) - Math.tan(30 * DEGREE)) / (2 * Math.tan(FRAME)), 9);
    // Five metres off it is nowhere nearer than 4 m; looking away from it, it is behind the viewer.
    const far: SightBlocker = [[-5_500, 1_000], [-5_000, 1_000], [-5_000, -10_000], [-5_500, -10_000]];
    expect(nearFaceShare([0, 0], [0, -1], [far], FRAME, 4_000)).toBe(0);
    expect(nearFaceShare([0, 4_000], [0, 1], [wall], FRAME, 4_000)).toBe(0);
    // Two walls covering the same columns count once.
    expect(nearFaceShare([0, 0], [0, -1], [wall, wall], FRAME, 4_000)).toBeCloseTo(nearFaceShare([0, 0], [0, -1], [wall], FRAME, 4_000), 12);
  });

  it('keeps a first view off the frontage behind its footway, where the rule states a near face', () => {
    // Arriving facing north across the street, the near frontage 1.6 m behind the line people walk. Standing
    // back from the kerb, off that line, is worth a little, so a view takes a step back toward the frontage.
    const frontage: SightBlocker = [[-200_000, 1_600], [200_000, 1_600], [200_000, 30_000], [-200_000, 30_000]];
    const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
    const life = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    const NEAR = { ...LIVELY, middleThirdHalf: 23 * DEGREE, nearFace: { nearMm: 4_000, shareMost: 0.1, frameHalf: FRAME, postMm: 4_000 } };
    const share = (view: { eastMm: number; southMm: number; yaw: number }) =>
      nearFaceShare([view.eastMm, view.southMm], looks(view.yaw), [opposite, frontage], FRAME, 4_000);
    // Positive control: without the near face, the view stands a step back, 0.85 m off the frontage, which
    // fills more than a tenth of the frame.
    const { nearFace: _near, ...without } = NEAR;
    const walls = { blockers: [opposite, frontage], fronts: [opposite, frontage] };
    const before = arrivalView({ ...town, ...walls, open: without, life });
    expect(before.southMm).toBeGreaterThan(0);
    expect(share(before)).toBeGreaterThan(0.1);
    const view = arrivalView({ ...town, ...walls, open: NEAR, life });
    expect(share(view)).toBeLessThanOrEqual(0.1);
    expect(view.southMm).toBeLessThan(before.southMm);
    // Still the town's view along the street at its slant.
    expect(Math.abs(looks(view.yaw)[1])).toBeCloseTo(Math.cos(60 * DEGREE), 9);
  });

  it('passes over a view with a trunk or post near anywhere in its frame, however little of it the post takes', () => {
    // Arriving facing north across the street, a view a step back looks east along it, from (0, 750) toward 30
    // degrees north of east. A lamp post 2 m off at 40 degrees from that view's middle: outside its middle third,
    // inside its frame.
    const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
    const life = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    const bearing = -70 * DEGREE;
    const lamp = post(Math.round(2_000 * Math.cos(bearing)), Math.round(750 + 2_000 * Math.sin(bearing)), 200);
    const NEAR = { ...LIVELY, middleThirdHalf: 23 * DEGREE, nearFace: { nearMm: 4_000, shareMost: 0.1, frameHalf: FRAME, postMm: 4_000 } };
    const scene = { blockers: [opposite, behind, lamp], fronts: [opposite, behind] };
    const nearestPost = (view: { eastMm: number; southMm: number; yaw: number }) =>
      nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), FRAME, [lamp]);
    // Positive control: as walls are judged, the post takes under a tenth of the frame, so without the near
    // post the view stands beside it.
    const asWall = arrivalView({ ...town, ...scene, open: { ...NEAR, nearFace: { ...NEAR.nearFace, postMm: 1 } }, life });
    expect(nearestPost(asWall)).toBeLessThan(4_000);
    expect(nearFaceShare([asWall.eastMm, asWall.southMm], looks(asWall.yaw), [lamp], FRAME, 4_000)).toBeLessThan(0.1);
    const view = arrivalView({ ...town, ...scene, open: NEAR, life });
    expect(nearestPost(view)).toBeGreaterThanOrEqual(4_000);
    // The same square as a building's corner is a wall, judged by its share: under a tenth, the view stands by it.
    const asBuilding = arrivalView({ ...town, blockers: [opposite, behind, lamp], fronts: [opposite, behind, lamp], open: NEAR, life });
    expect(asBuilding).toEqual(asWall);
  });
});

describe('a low thing in the near middle of a first view', () => {
  it('is a piece of street furniture standing wholly below eye height, as the footprint of each of its parts', () => {
    // Facing east; each part 400 mm along and 200 mm across, centred on its record.
    const at = (eastMm: number, ...tops: number[]) => ({
      eastMm, southMm: 0, facing: [1, 0] as const,
      parts: tops.map((top) => ({ alongMm: 0, leftMm: 0, bottomMm: 0, sizeAlongMm: 400, sizeLeftMm: 200, heightMm: top })),
    });
    // A bin (0.9 m), a bench (seat and back, 0.85 m), a lamp (4.5 m), a lamp on a low plinth (0.3 m and 4.5 m:
    // it reaches eye height, so it is a post), and a record with no parts.
    const rings = lowOf([at(1_000, 900), at(2_000, 450, 850), at(3_000, 4_500), at(5_000, 300, 4_500), at(4_000)], 1_600);
    expect(rings).toHaveLength(3);
    // Left of east is north, south decreasing: the bin's footprint runs 800 to 1,200 east, 100 either side.
    expect(rings[0]).toEqual([[800, 100], [1_200, 100], [1_200, -100], [800, -100]]);
  });

  it('passes over a view with a low thing nearer than its least distance in the middle third, or near in its frame', () => {
    // Arriving facing north across the street, a door one way along it.
    const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
    const street = [opposite, behind];
    const plain = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    const LOW = { ...LIVELY, middleThirdHalf: 23 * DEGREE, lowLeastMm: 6_000 };
    const { lowLeastMm: _low, ...without } = LOW;
    const before = arrivalView({ ...town, blockers: street, open: without, life: plain });
    // A bin 3 m ahead of that view, in the middle of its picture.
    const ahead = looks(before.yaw);
    const bin = post(before.eastMm + ahead[0] * 3_000, before.southMm + ahead[1] * 3_000, 500);
    const life = { ...plain, low: [bin] };
    // Positive control: without the least distance, the bin moves nothing.
    expect(arrivalView({ ...town, blockers: street, open: without, life })).toEqual(before);
    const view = arrivalView({ ...town, blockers: street, open: LOW, life });
    expect(nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), 23 * DEGREE, [bin])).toBeGreaterThanOrEqual(6_000);
    // Off the middle third: a bin 30 degrees off and 5 m away moves nothing, one 35 degrees off and 1 m away
    // stands at the viewer's feet and passes the view over, as a post beside it does.
    const FRAMED = { ...LOW, nearFace: { nearMm: 4_000, shareMost: 0.1, frameHalf: 51 * DEGREE, postMm: 4_000 } };
    const { lowLeastMm: _framedLow, ...framedWithout } = FRAMED;
    const plainView = arrivalView({ ...town, blockers: street, fronts: street, open: framedWithout, life: plain });
    const look = looks(plainView.yaw);
    const turn = (degrees: number, mm: number) => [
      plainView.eastMm + (look[0] * Math.cos(degrees * DEGREE) - look[1] * Math.sin(degrees * DEGREE)) * mm,
      plainView.southMm + (look[0] * Math.sin(degrees * DEGREE) + look[1] * Math.cos(degrees * DEGREE)) * mm,
    ] as const;
    const framed = (low: SightBlocker[]) => arrivalView({ ...town, blockers: street, fronts: street, open: FRAMED, life: { ...plain, low } });
    expect(framed([post(...turn(30, 5_000), 300)])).toEqual(plainView);
    const feet = post(...turn(-35, 1_000), 300);
    const stepped = framed([feet]);
    expect(nearestInWedge([stepped.eastMm, stepped.southMm], looks(stepped.yaw), 51 * DEGREE, [feet])).toBeGreaterThanOrEqual(4_000);
  });

  it('counts a low thing by its width, wherever any of it stands inside the frame', () => {
    // A bench 2.4 m long, 2.5 m off, its middle 56 degrees off the view's middle (outside the 51 degree
    // frame) and its near end inside it.
    const town = { eastMm: 0, southMm: 0, facing: [0, -1] as const, targets: [], parked: [], ground: footway };
    const street = [opposite, behind];
    const plain = { seats: [], doors: [[20_000, -16_000]] as [number, number][] };
    const FRAMED = {
      ...LIVELY, middleThirdHalf: 23 * DEGREE, lowLeastMm: 6_000,
      nearFace: { nearMm: 4_000, shareMost: 0.1, frameHalf: 51 * DEGREE, postMm: 4_000 },
    };
    const { lowLeastMm: _low, ...without } = FRAMED;
    const plainView = arrivalView({ ...town, blockers: street, fronts: street, open: without, life: plain });
    const look = looks(plainView.yaw);
    const angle = 56 * DEGREE;
    const way = [look[0] * Math.cos(angle) - look[1] * Math.sin(angle), look[0] * Math.sin(angle) + look[1] * Math.cos(angle)] as const;
    const middle = [plainView.eastMm + way[0] * 2_500, plainView.southMm + way[1] * 2_500] as const;
    // Laid across the line of sight, so its ends stand about 27 degrees either side of its middle.
    const across = [-way[1], way[0]] as const;
    const end = (sign: number, wide: number) => [middle[0] + across[0] * sign * 1_200 + way[0] * wide, middle[1] + across[1] * sign * 1_200 + way[1] * wide] as const;
    const bench: SightBlocker = [end(-1, -250), end(1, -250), end(1, 250), end(-1, 250)];
    // Positive control: its middle alone is outside the frame.
    expect(nearestSeatInFan([plainView.eastMm, plainView.southMm], look, 51 * DEGREE, [middle])).toBe(Number.POSITIVE_INFINITY);
    expect(nearestInWedge([plainView.eastMm, plainView.southMm], look, 51 * DEGREE, [bench])).toBeLessThan(4_000);
    const view = arrivalView({ ...town, blockers: street, fronts: street, open: FRAMED, life: { ...plain, low: [bench] } });
    expect(nearestInWedge([view.eastMm, view.southMm], looks(view.yaw), 51 * DEGREE, [bench])).toBeGreaterThanOrEqual(4_000);
  });
});
