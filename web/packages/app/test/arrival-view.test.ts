import { describe, expect, it } from 'vitest';
import {
  arrivalView, crosses, nearestInWedge, nearestSeatInFan, openDistance, parkedFootprint, seatsOf, viewLife, viewOpenness,
  type LifeViewRule, type OpenViewRule, type SightBlocker,
} from '../src/composition/arrival-view.js';

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
