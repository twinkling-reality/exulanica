import { describe, expect, it } from 'vitest';
import {
  arrivalView, crosses, openDistance, parkedFootprint, viewOpenness, type OpenViewRule, type SightBlocker,
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
