/**
 * Where plants may hang over a terrace's edge: the edge and face finder over a site's land, read
 * side by side of a zone's ground plane, station by station.
 *
 * The land is synthetic, a real chunk on the 1 m lattice read by the page's own interpolation
 * (`chunkHeightMm`), from a formula per case: a level pad 10 m above the datum under a zone 16 m by
 * 12 m, with a drop, a bank or a rise past its sides. The slots are drawn as a site drawing on land
 * draws them: draped, each a few millimetres above the land by its layer.
 */
import { chunkHeightMm, type LandChunk } from '@exulanica/atlas-core';
import { describe, expect, it } from 'vitest';
import {
  TRAIL_DROP_LEAST_MM, TRAIL_SLOPE_LEAST_PERMILLE, findTrailEdges,
  type TrailLand, type TrailSide, type TrailSlot, type TrailStation,
} from '../src/playcanvas/style-pack/trailers.js';

const LEVEL = 10_000;
const SAMPLES = 129;

/** Land from a lattice formula over the chunk at the origin, dry everywhere `wet` does not say. */
function landOf(lattice: (east: number, north: number) => number, wet: (east: number, north: number) => boolean = () => false): TrailLand {
  const heightMm = new Int32Array(SAMPLES * SAMPLES);
  for (let j = 0; j < SAMPLES; j += 1) for (let i = 0; i < SAMPLES; i += 1) heightMm[j * SAMPLES + i] = Math.round(lattice(i * 1000, j * 1000));
  const chunk: LandChunk = { chunkX: 0, chunkY: 0, cellMm: 1000, samplesPerSide: SAMPLES, heightMm, sha256: '' };
  return { groundMm: (east, north) => chunkHeightMm(chunk, east, north) ?? 0, dryAt: (east, north) => !wet(east, north) };
}

/** A slot over a rectangle (west, south, east, north), draped `layerMm` above the land at its centre, or standing at `standMm`. */
function slotOf(
  land: TrailLand, identity: string, family: string, rect: readonly [number, number, number, number],
  { primitive = 'plane', heightMm = 0, layerMm = 6, standMm, structure }: { primitive?: string; heightMm?: number; layerMm?: number; standMm?: number; structure?: string } = {},
): TrailSlot {
  const [x, y] = [(rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2];
  return {
    identity, family, lookRole: `${family}.default`, primitive, yawQuarterTurns: 0,
    positionMm: [x, y, standMm ?? land.groundMm(x, y) + layerMm], boxMm: [rect[2] - rect[0], rect[3] - rect[1], heightMm],
    ...(standMm === undefined ? { drape: true as const } : {}),
    ...(structure === undefined ? {} : { structure }),
  };
}

/** The zone: 16 m by 12 m, its east side at `east`. */
const zoneOf = (land: TrailLand, east = 36_000): TrailSlot => slotOf(land, 'zone:terrace', 'ground', [20_000, 20_000, east, 32_000]);
/** The site's base ground under everything, at the land. */
const baseOf = (land: TrailLand): TrailSlot => slotOf(land, 'site:ground', 'ground', [0, 0, 64_000, 64_000], { layerMm: 0 });

/** Past the zone's east side, x at 36 m: one cell falling `drop`, then `bank` per mille for `bankMm`, then level. */
const eastFall = (drop: number, bank = 0, bankMm = 0) => (east: number): number => {
  if (east <= 36_000) return 0;
  if (east <= 37_000) return -(drop * (east - 36_000)) / 1000;
  return -drop - (bank * Math.min(east - 37_000, bankMm)) / 1000;
};

const sideOf = (sides: readonly TrailSide[], name: TrailSide['side']): TrailSide => sides.find((one) => one.side === name)!;
const at = (side: TrailSide, alongMm: number): TrailStation => side.stations.find((one) => one.alongMm === alongMm)!;
const reasons = (side: TrailSide): (string | null)[] => side.stations.map((one) => one.leftOut);
const kept = (station: TrailStation): Extract<TrailStation, { leftOut: null }> => {
  expect(station.leftOut).toBeNull();
  return station as Extract<TrailStation, { leftOut: null }>;
};

describe('finding a terrace edge', () => {
  it('names its figures with their defaults', () => {
    expect(TRAIL_DROP_LEAST_MM).toBe(600);
    expect(TRAIL_SLOPE_LEAST_PERMILLE).toBe(400);
  });

  it('finds an edge only where the land falls: a drop east, a rise north, level south, a gentle bank west', () => {
    const land = landOf((east, north) => LEVEL + eastFall(2000)(east)
      + (north > 32_000 ? (300 * (north - 32_000)) / 1000 : 0)
      + (east < 20_000 ? -(300 * (20_000 - east)) / 1000 : 0));
    const zone = zoneOf(land);
    const sides = findTrailEdges(zone, land, [baseOf(land), zone]);
    expect(sides.map((one) => one.side)).toEqual(['south', 'east', 'north', 'west']);
    const east = sideOf(sides, 'east');
    expect(east.outward).toEqual([1, 0]);
    expect(east.stations).toHaveLength(24);
    expect(east.stations[0]!.alongMm).toBe(20_250);
    for (const station of east.stations) {
      const found = kept(station);
      expect(found.levelMm).toBe(LEVEL);
      expect(found.lipMm[0]).toBe(36_000);
      expect(found.footMm[0]).toBe(37_000);
      expect(found.dropMm).toBe(2000);
      expect(found.topMm).toEqual(found.lipMm);
      expect(found.wall).toBeNull();
    }
    expect(new Set(reasons(sideOf(sides, 'north')))).toEqual(new Set(['no fall']));
    expect(new Set(reasons(sideOf(sides, 'south')))).toEqual(new Set(['no fall']));
    // A 300 per mille bank is gentler than the least slope: the land falls, but there is no face.
    expect(new Set(reasons(sideOf(sides, 'west')))).toEqual(new Set(['no face']));
  });

  it('finds the lip where the land breaks when the side lies off the lattice', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east));
    const zone = zoneOf(land, 36_300);
    const found = kept(sideOf(findTrailEdges(zone, land, [zone]), 'east').stations[5]!);
    expect(Math.abs(found.lipMm[0] - 36_000)).toBeLessThanOrEqual(10);
    expect(Math.abs(found.footMm[0] - 37_000)).toBeLessThanOrEqual(10);
    expect(found.dropMm).toBe(2000);
  });

  it('cuts a steep cell from the bank below it: the face is its straight run', () => {
    const land = landOf((east) => LEVEL + eastFall(2000, 500, 6000)(east));
    const zone = zoneOf(land);
    const found = kept(sideOf(findTrailEdges(zone, land, [zone]), 'east').stations[0]!);
    expect(found.footMm[0]).toBe(37_000);
    expect(found.dropMm).toBe(2000);
  });

  it('grows nothing from a 500 mm drop by default, and does where the rule asks for 400', () => {
    const land = landOf((east) => LEVEL + eastFall(500)(east));
    const zone = zoneOf(land);
    expect(new Set(reasons(sideOf(findTrailEdges(zone, land, [zone]), 'east')))).toEqual(new Set(['shallow']));
    const found = kept(sideOf(findTrailEdges(zone, land, [zone], { drop_mm: 400 }), 'east').stations[0]!);
    expect(found.dropMm).toBe(500);
  });

  it('keeps out a path at the foot, a gate path over the lip, a building on the lip, water and wet land at the foot', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east), (east, north) => east >= 36_500 && north >= 31_000);
    const zone = zoneOf(land);
    const slots = [
      baseOf(land), zone,
      // A path along the foot, its near side 200 mm past it: within a walker's reach.
      slotOf(land, 'path:foot', 'path', [37_200, 20_000, 39_200, 22_000], { layerMm: 12 }),
      // A gate path from the zone over its lip and down.
      slotOf(land, 'path:gate', 'path', [34_000, 23_500, 38_000, 24_500], { layerMm: 12 }),
      slotOf(land, 'shed', 'structure', [36_000, 26_000, 40_000, 27_500], { primitive: 'none', heightMm: 2400 }),
      slotOf(land, 'pond', 'water', [37_000, 29_000, 40_000, 30_000], { standMm: 8100 }),
    ];
    const east = sideOf(findTrailEdges(zone, land, slots), 'east');
    expect(at(east, 21_250).leftOut).toBe('path');
    expect(at(east, 24_250).leftOut).toBe('covered');
    expect(at(east, 26_750).leftOut).toBe('box');
    expect(at(east, 29_250).leftOut).toBe('water');
    expect(at(east, 31_750).leftOut).toBe('wet foot');
    // Clear of all of them by more than a walker's reach.
    expect(kept(at(east, 25_250)).dropMm).toBe(2000);
    expect(kept(at(east, 28_250)).dropMm).toBe(2000);
  });

  it('takes the edge from where an overlaid area is the top', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east));
    const zone = zoneOf(land);
    const bed = slotOf(land, 'bed', 'ground', [33_000, 20_000, 36_000, 24_000], { layerMm: 9 });
    const east = sideOf(findTrailEdges(zone, land, [baseOf(land), zone, bed]), 'east');
    expect(at(east, 21_250).leftOut).toBe('covered');
    expect(at(east, 24_750).leftOut).toBeNull();
  });

  it('hangs from a flush parapet at its top, and a wall set back from the side blocks', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east));
    const zone = zoneOf(land);
    const parapet = slotOf(land, 'zone:terrace:wall:0', 'boundary', [35_800, 20_000, 36_000, 26_000], { primitive: 'box', heightMm: 1100 });
    const setBack = slotOf(land, 'zone:terrace:wall:1', 'boundary', [35_200, 27_000, 35_400, 32_000], { primitive: 'box', heightMm: 1100 });
    const east = sideOf(findTrailEdges(zone, land, [baseOf(land), zone, parapet, setBack]), 'east');
    for (const along of [20_250, 23_250, 25_750]) {
      const found = kept(at(east, along));
      expect(found.wall).toBe('zone:terrace:wall:0');
      expect(found.topMm).toEqual([36_000, along, LEVEL + 6 + 1100]);
      expect(found.lipMm).toEqual([36_000, along, LEVEL]);
      // The wall's own height does not count toward the drop.
      expect(found.dropMm).toBe(2000);
    }
    for (const along of [27_250, 29_750, 31_750]) expect(at(east, along).leftOut).toBe('box');
  });

  it('grows only on a side within the rule\'s reach of the sun', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east));
    const zone = zoneOf(land);
    const facing = sideOf(findTrailEdges(zone, land, [zone], { sun_within_mdeg: 45_000 }, { sunAzimuthDeg: 90 }), 'east');
    expect(kept(facing.stations[0]!).dropMm).toBe(2000);
    const away = sideOf(findTrailEdges(zone, land, [zone], { sun_within_mdeg: 45_000 }, { sunAzimuthDeg: 270 }), 'east');
    expect(new Set(reasons(away))).toEqual(new Set(['sun']));
    // With no sun drawn, the test passes every side.
    expect(kept(sideOf(findTrailEdges(zone, land, [zone], { sun_within_mdeg: 45_000 }), 'east').stations[0]!).dropMm).toBe(2000);
  });
});
