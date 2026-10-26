import { describe, expect, it } from 'vitest';
import { nearFaceShare, type SightBlocker } from '../src/composition/arrival-view.js';
import { PLACE_FIRST_VIEW, buildingsSeen, placeFirstView, placeViewRule, type PlaceSight } from '../src/composition/place-first-view.js';
import { TOWN_FIRST_VIEW } from '../src/town-first-view.js';

/** A plan rectangle as a sight ring, millimetres east and south. */
const box = (west: number, east: number, north: number, south: number): SightBlocker => [[west, north], [east, north], [east, south], [west, south]];
const inside = (rings: readonly SightBlocker[], east: number, south: number): boolean => rings.some((ring) =>
  east >= ring[0]![0] && east <= ring[1]![0] && south >= ring[0]![1] && south <= ring[2]![1]);

// A place 20 m wide and 30 m deep, its south-west corner the origin: it spans south -30 m to 0.
const PLACE = { widthMm: 20_000, depthMm: 30_000 } as const;
const NORTH = [0, -1] as const;
/**
 * A coast's heights by distance south: rising north of the place toward a hill, 6 m at its south edge,
 * falling to the sea's level 40 m south of it, and the sea beyond.
 */
const coast = (south: number): number => (south > 40_000 ? -5_000 : south > 0 ? 6_000 - south * 0.15 : 6_000 + Math.max(0, -south - 20_000) / 2);

describe('place first view', () => {
  it('steps out of a lane walled close on both sides to a clear view across the place', () => {
    // The served arrival 1 m inside the south edge, facing north up a lane 3 m wide.
    const walls = [box(7_500, 8_500, -30_000, 0), box(11_500, 12_500, -30_000, 0)];
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: walls.map((wall) => [wall]), posts: [],
      standable: (east, south) => !inside(walls, east, south),
    };
    const near = TOWN_FIRST_VIEW.nearFace!;
    // As served, the lane's walls fill the frame's sides.
    expect(nearFaceShare(sight.arrivalMm, NORTH, walls, near.frameHalf, near.nearMm)).toBeGreaterThan(near.shareMost);
    const view = placeFirstView(sight, TOWN_FIRST_VIEW);
    expect(view.chosen).toBe('across');
    expect(view.moved).toBe(true);
    const toward = [-Math.sin(view.yaw), -Math.cos(view.yaw)] as const;
    expect(nearFaceShare([view.eastMm, view.southMm], toward, walls, near.frameHalf, near.nearMm)).toBeLessThanOrEqual(near.shareMost);
  });

  it('takes the land’s sea with the place in the frame, from beyond the place', () => {
    // The sea lies south of the place, the land falling to it from the place's south edge.
    const walls = [box(4_000, 6_000, -11_000, -9_000), box(14_000, 16_000, -11_000, -9_000)];
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: walls.map((wall) => [wall]), posts: [],
      standable: (east, south) => south < 38_000 && !inside(walls, east, south),
      sea: { groundMm: (_east, south) => coast(south), levelMm: 0, eyeMm: 1_600 },
    };
    const view = placeFirstView(sight, TOWN_FIRST_VIEW);
    expect(view.chosen).toBe('water');
    // Both of the place's buildings stand in the frame with the water.
    const toward = [-Math.sin(view.yaw), -Math.cos(view.yaw)] as const;
    const seen = buildingsSeen([view.eastMm, view.southMm], toward, sight.buildings, walls, TOWN_FIRST_VIEW.nearFace!.frameHalf,
      PLACE_FIRST_VIEW.structureLineStep, PLACE_FIRST_VIEW.structureReachMm, PLACE_FIRST_VIEW.structureLinesLeast);
    expect(seen).toBe(2);
  });

  it('never takes the water with the place behind', () => {
    // A person can stand only on the shore, from where the place's buildings and the water lie farther
    // apart than any frame is wide.
    const walls = [box(4_000, 6_000, -11_000, -9_000), box(14_000, 16_000, -11_000, -9_000)];
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: walls.map((wall) => [wall]), posts: [],
      standable: (_east, south) => south > 25_000 && south < 38_000,
      sea: { groundMm: (_east, south) => coast(south), levelMm: 0, eyeMm: 1_600 },
    };
    expect(placeFirstView(sight, TOWN_FIRST_VIEW).chosen).not.toBe('water');
  });

  it('passes over two blank walls a few metres either side, though beyond the towns’ near distance', () => {
    // A lane 12 m wide: its walls 6 m either side are past 4 m, but windowless within 15 m.
    const walls = [box(3_000, 4_000, -30_000, 0), box(16_000, 17_000, -30_000, 0)];
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: walls.map((wall) => [wall]), posts: [],
      standable: (east, south) => !inside(walls, east, south),
    };
    const near = TOWN_FIRST_VIEW.nearFace!;
    expect(nearFaceShare(sight.arrivalMm, NORTH, walls, near.frameHalf, near.nearMm)).toBe(0);
    expect(nearFaceShare(sight.arrivalMm, NORTH, walls, near.frameHalf, PLACE_FIRST_VIEW.wallNearMm)).toBeGreaterThan(PLACE_FIRST_VIEW.wallShareMost);
    expect(placeFirstView(sight, TOWN_FIRST_VIEW).moved).toBe(true);
  });

  it('counts the sides of a cut that rise above the eye as walls', () => {
    // No building near: the arrival's path runs 3 m wide between two yards graded 3 m above it.
    const cut = (east: number, south: number): number => (south < 0 && south > -20_000 && Math.abs(east - 10_000) > 1_500 ? 3_000 : 0);
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: [], posts: [],
      standable: () => true,
      ground: { groundMm: cut, eyeMm: 1_600 },
    };
    const view = placeFirstView(sight, TOWN_FIRST_VIEW);
    expect(view.chosen).toBe('across');
    expect(view.moved).toBe(true);
    // Level ground the same: the arrival's own view is clear.
    expect(placeFirstView({ ...sight, ground: { groundMm: () => 0, eyeMm: 1_600 } }, TOWN_FIRST_VIEW).moved).toBe(false);
  });

  it('counts a building only where its own sight lines meet it first', () => {
    // From the origin looking north, a long building stands 20 m ahead and a small one hides behind it.
    const front = [box(-10_000, 10_000, -21_000, -20_000)];
    const behind = [box(-2_000, 2_000, -32_000, -30_000)];
    const seen = (buildings: readonly (readonly SightBlocker[])[]): number => buildingsSeen([0, 0], NORTH, buildings, buildings.flat(),
      TOWN_FIRST_VIEW.nearFace!.frameHalf, PLACE_FIRST_VIEW.structureLineStep, PLACE_FIRST_VIEW.structureReachMm, PLACE_FIRST_VIEW.structureLinesLeast);
    expect(seen([front, behind])).toBe(1);
    expect(seen([behind])).toBe(1);
  });

  it('reads the place figures from their catalog and refuses one that leaves a figure out', () => {
    expect(PLACE_FIRST_VIEW.structuresLeast).toBe(2);
    expect(PLACE_FIRST_VIEW.structureReachMm).toBe(60_000);
    const stated = { profile: 'exulanica.place-first-view/v1', entries: [{ key: 'way_step_degrees', value: 5 }] };
    expect(() => placeViewRule(JSON.stringify(stated))).toThrow(/states no/);
  });

  it('keeps the served arrival where no view from anywhere is clear', () => {
    // Walled in a metre round, with nowhere else to stand.
    const walls = [box(9_000, 11_000, -2_000, -1_900), box(9_000, 11_000, -100, 0), box(9_000, 9_100, -2_000, 0), box(10_900, 11_000, -2_000, 0)];
    const sight: PlaceSight = {
      ...PLACE, arrivalMm: [10_000, -1_000], facing: NORTH, buildings: [walls], posts: [],
      standable: () => false,
    };
    expect(placeFirstView(sight, TOWN_FIRST_VIEW)).toEqual({
      eastMm: 10_000, southMm: -1_000, yaw: Math.atan2(-0, 1), moved: false, chosen: 'served',
    });
  });
});
