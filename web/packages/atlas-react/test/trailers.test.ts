// @vitest-environment happy-dom
/**
 * Where plants may hang over a terrace's edge: the edge and face finder over a site's land, read
 * side by side of a zone's ground plane, station by station, and the dresser drawing what it finds.
 *
 * The land is synthetic, a real chunk on the 1 m lattice read by the page's own interpolation
 * (`chunkHeightMm`), from a formula per case: a level pad 10 m above the datum under a zone 16 m by
 * 12 m, with a drop, a bank or a rise past its sides. The slots are drawn as a site drawing on land
 * draws them: draped, each a few millimetres above the land by its layer. The plants are stood in
 * for by their authored sizes alone, and in the dresser's case by one card each.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { canonicalJson, chunkHeightMm, readStylePackManifest, resolveStylePack, type LandChunk, type LookFamily, type StylePackManifest } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { parseStructuredSiteDrawing, readSiteLand, siteMount } from '../src/playcanvas/generated-site/index.js';
import { CLIMB_STANDOFF_M } from '../src/playcanvas/style-pack/climbers.js';
import { packSiteDresser, renderLookOfPreset, type FetchedPieces, type SiteDressingSummary } from '../src/playcanvas/style-pack/index.js';
import {
  TRAIL_DROP_LEAST_MM, TRAIL_SLOPE_LEAST_PERMILLE, findTrailEdges, growTrailers, trailMatrix, trailRuns,
  type TrailKept, type TrailLand, type TrailPoint, type TrailRule, type TrailSide, type TrailSlot, type TrailStation,
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

  it('hangs from a flush parapet at its top down its outer face, and a wall set back from the side or buried below the lip blocks', () => {
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
      // A plant hangs down the wall's outer face to the land at its foot, not out over the fall below it.
      expect(found.footMm).toEqual([36_000, along, LEVEL]);
      // The wall's own height does not count toward the drop, which is still the land's.
      expect(found.dropMm).toBe(2000);
    }
    for (const along of [27_250, 29_750, 31_750]) expect(at(east, along).leftOut).toBe('box');
    // A wall on the side whose top stands below the land at its outer face hangs nothing: it is a box in the way.
    const buried = slotOf(land, 'zone:terrace:wall:2', 'boundary', [35_800, 20_000, 36_000, 26_000], { primitive: 'box', heightMm: 1100, standMm: LEVEL - 2000 });
    const under = sideOf(findTrailEdges(zone, land, [baseOf(land), zone, buried]), 'east');
    for (const along of [20_250, 23_250, 25_750]) expect(at(under, along).leftOut).toBe('box');
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

const RULE: TrailRule = { pieces: ['plant.ivy', 'plant.fern'], share_permille: 500, hang_permille: [400, 800], seed: 7 };
const SIZES: Readonly<Record<string, readonly [number, number, number]>> = { 'plant.ivy': [400, 100, 800], 'plant.fern': [600, 150, 600] };
const sizeOf = (piece: string): readonly [number, number, number] | null => SIZES[piece] ?? null;
/** A face 1 m out and 2 m down, top to foot. */
const STEEP_FACE_MM = Math.hypot(1000, 2000);

/** The east side's plants over the steep cell, in order along it. */
function grownEast(rule: TrailRule = RULE, identity = 'zone:terrace'): readonly TrailPoint[] {
  const land = landOf((east) => LEVEL + eastFall(2000)(east));
  const zone = { ...zoneOf(land), identity };
  return growTrailers([{ slot: zone, rule }], land, [baseOf(land), zone], { sizeOf }).points;
}

describe('hanging plants over a terrace edge', () => {
  it('covers the rule\'s share of a run with plants spaced evenly along it, each hanging its share of the face', () => {
    const points = [...grownEast()].sort((a, b) => a.alongMm - b.alongMm);
    expect(points.length).toBeGreaterThan(3);
    const widths = points.reduce((sum, one) => sum + one.widthMm, 0);
    // The run is the whole east side, 12 m: plants are chosen until they cover half of it.
    expect(widths).toBeGreaterThanOrEqual(6000);
    expect(widths).toBeLessThan(6000 + Math.max(...points.map((one) => one.widthMm)));
    const edges = [20_000, ...points.flatMap((one) => [one.alongMm - one.widthMm / 2, one.alongMm + one.widthMm / 2]), 32_000];
    const gaps = edges.flatMap((edge, k) => (k % 2 === 0 ? [edges[k + 1]! - edge] : []));
    for (const gap of gaps) expect(gap).toBeCloseTo(gaps[0]!, 6);
    for (const one of points) {
      expect(one.side).toBe('east');
      expect(one.topM).toEqual([36, one.alongMm / 1000, LEVEL / 1000]);
      expect(one.hangM * 1000).toBeGreaterThanOrEqual(0.4 * STEEP_FACE_MM - 1e-6);
      expect(one.hangM * 1000).toBeLessThanOrEqual(0.8 * STEEP_FACE_MM + 1e-6);
      expect(one.wall).toBeNull();
    }
  });

  it('grows the same plants for the same seed and slot, and others for another slot', () => {
    expect(grownEast()).toEqual(grownEast());
    const picks = (points: readonly TrailPoint[]): number[] => points.map((one) => one.pick);
    expect(picks(grownEast(RULE, 'zone:other'))).not.toEqual(picks(grownEast()));
    expect(picks(grownEast({ ...RULE, seed: 8 }))).not.toEqual(picks(grownEast()));
  });

  it('counts the plants its guard leaves out and the stations its bound never reads', () => {
    const land = landOf((east) => LEVEL + eastFall(2000)(east));
    const zone = zoneOf(land);
    const north = slotOf(land, 'zone:upper', 'ground', [20_000, 40_000, 36_000, 52_000]);
    const ruled = [{ slot: zone, rule: RULE }, { slot: north, rule: RULE }];
    const all = growTrailers(ruled, land, [baseOf(land), zone, north], { sizeOf });
    expect(all.terraces).toBe(2);
    expect(all.leftOut).toBe(0);
    expect(all.untried).toBe(0);
    const guarded = growTrailers(ruled, land, [baseOf(land), zone, north], { sizeOf, most: 3 });
    expect(guarded.points).toEqual(all.points.slice(0, 3));
    expect(guarded.leftOut).toBe(all.points.length - 3);
    // Each zone's four sides take 24 + 32 + 24 + 32 stations; a bound of 150 reads the first alone.
    const bounded = growTrailers(ruled, land, [baseOf(land), zone, north], { sizeOf, stations: 150 });
    expect(bounded.untried).toBe(112);
    expect(bounded.terraces).toBe(1);
    expect(bounded.points).toEqual(all.points.filter((one) => one.topM[1] < 32));
  });

  it('hangs a plant turned, never mirrored: +Y down the face, +Z away from the land, its back proud of the face', () => {
    const point = grownEast()[0]!;
    const bounds = [-0.2, 0, -0.05, 0.2, 0.8, 0.05];
    const m = trailMatrix(point, bounds);
    const scale = point.hangM / 0.8;
    const column = (k: number): number[] => [m[4 * k]! / scale, m[4 * k + 1]! / scale, m[4 * k + 2]! / scale];
    const [x, y, z] = [column(0), column(1), column(2)];
    const det = x[0]! * (y[1]! * z[2]! - y[2]! * z[1]!) - y[0]! * (x[1]! * z[2]! - x[2]! * z[1]!) + z[0]! * (x[1]! * y[2]! - x[2]! * y[1]!);
    expect(det).toBeCloseTo(1, 5);
    // Renderer frame (east, up, south): down the face is 1 east for 2 down; away from the land is 2 east for 1 up.
    const root5 = Math.sqrt(5);
    [1 / root5, -2 / root5, 0].forEach((value, k) => expect(y[k]).toBeCloseTo(value, 5));
    [2 / root5, 1 / root5, 0].forEach((value, k) => expect(z[k]).toBeCloseTo(value, 5));
    [0, 0, 1].forEach((value, k) => expect(x[k]).toBeCloseTo(value, 5));
    const out = CLIMB_STANDOFF_M + 0.05 * scale;
    [36 + (2 / root5) * out, LEVEL / 1000 + (1 / root5) * out, -point.topM[1] + 0].forEach((value, k) => expect(m[12 + k]).toBeCloseTo(value, 5));
    expect(m[15]).toBe(1);
  });

  it('hangs a plant over a parapet straight down its outer face, facing out, no longer than the wall stands above the land', () => {
    const land = landOf((east) => LEVEL + eastFall(2000, 500, 8000)(east));
    const zone = zoneOf(land);
    const parapet = slotOf(land, 'zone:terrace:wall:0', 'boundary', [35_800, 20_000, 36_000, 32_000], { primitive: 'box', heightMm: 1100 });
    const points = growTrailers([{ slot: zone, rule: RULE }], land, [baseOf(land), zone, parapet], { sizeOf }).points;
    expect(points.length).toBeGreaterThan(0);
    for (const one of points) {
      expect(one.wall).toBe('zone:terrace:wall:0');
      expect(one.topM).toEqual([36, one.alongMm / 1000, (LEVEL + 6 + 1100) / 1000]);
      expect(one.down).toEqual([0, 0, -1]);
      expect(one.normal).toEqual([1, 0, 0]);
      expect(one.hangM * 1000).toBeLessThanOrEqual(0.8 * 1106 + 1e-6);
    }
  });

  it('hangs no plant past the foot of any face it spans', () => {
    // The drop past the east side grows from 1.5 m at its south end to 2 m at its north end.
    const drop = (north: number): number => 1500 + (500 * Math.min(12_000, Math.max(0, north - 20_000))) / 12_000;
    const land = landOf((east, north) => LEVEL + (east <= 36_000 ? 0 : -(drop(north) * Math.min(1000, east - 36_000)) / 1000));
    const zone = zoneOf(land);
    const rule: TrailRule = { ...RULE, hang_permille: [1000, 1000] };
    const side = sideOf(findTrailEdges(zone, land, [zone], rule), 'east');
    expect(trailRuns(side)).toHaveLength(1);
    const faces = side.stations.map((one) => {
      const kept = one as TrailKept;
      return { from: one.alongMm - side.stepMm / 2, to: one.alongMm + side.stepMm / 2, lengthMm: Math.hypot(...[0, 1, 2].map((k) => kept.footMm[k]! - kept.topMm[k]!)) };
    });
    const points = growTrailers([{ slot: zone, rule }], land, [zone], { sizeOf }).points;
    expect(points.length).toBeGreaterThan(0);
    for (const one of points) {
      const spanned = faces.filter((face) => face.to > one.alongMm - one.widthMm / 2 && face.from < one.alongMm + one.widthMm / 2);
      expect(one.hangM * 1000).toBeLessThanOrEqual(Math.min(...spanned.map((face) => face.lengthMm)) + 1e-6);
    }
  });
});

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const WINDY = CASES.cases.find((one) => one.name === 'a pack growing grass and flowers on its lawns in a wind')!.manifest;
/** The windy pack drawing its grounds as plain surfaces, hanging its grass tufts over the edges of whatever is drawn as one. */
const TRAILING: StylePackManifest = {
  ...WINDY,
  surfaces: { ...WINDY.surfaces, 'ground.default': WINDY.surfaces!['wall.default']! },
  trail: { 'ground.default': { pieces: ['plant.grass_tuft'], share_permille: 500, hang_permille: [500, 500], seed: 3 } },
};
const trailingPack = resolveStylePack([readStylePackManifest(TRAILING, { families, textureSets: new Set(CASES.context.texture_sets) })]);

/** The dresser's land, east: level at 10 m to 20 m, falling 2 m across the next cell, then level at 8 m. */
const stepEast = (east: number): number => (east <= 20_000 ? 10_000 : east >= 21_000 ? 8000 : 10_000 - 2 * (east - 20_000));
function stepChunk(chunkX: number, chunkY: number): Record<string, unknown> {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(stepEast(chunkX * 128_000 + i * 1000));
  return { profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height };
}
const XS = [-400_000, -128_000, 0, 128_000, 400_000], YS = [-400_000, 0, 128_000, 400_000];
const stepBackdrop = (): Record<string, unknown> => ({
  profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, 0, 128_000, 128_000], x_mm: XS, y_mm: YS,
  height_mm: YS.flatMap((y) => XS.map((x) => (y < 0 ? -20_000 : stepEast(x)))),
  water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
});
const digestOf = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const named = (document: Record<string, unknown>): string => digestOf(new TextEncoder().encode(canonicalJson(document)));

/**
 * A site 40 m by 30 m on that land: its base ground over it all, an upper terrace on the level west of
 * the fall, its east side on the fall's lip, and a lower one on the level east of it, each 6 mm above
 * the land. Only the upper terrace's east side looks over a drop; neither terrace states a look role
 * with a trail rule of its own, so each takes the rule of the role its surface is drawn in.
 */
function terracesDrawing() {
  const ground = (identity: string, lookRole: string, rect: readonly [number, number, number, number], upMm: number) => ({
    identity, part: identity.split(':')[0]!, label: identity, lookRole,
    positionMm: [(rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2, upMm], yawQuarterTurns: 0,
    boxMm: [rect[2] - rect[0], rect[3] - rect[1], 0], front: '+y', fit: 'surface', primitive: 'plane', drape: true,
  });
  return parseStructuredSiteDrawing({
    profile: 'exulanica.site-drawing/v5', world_id: 'world:generated:terraces-fixture', receipt_sha256: 'c'.repeat(64),
    kind: { kind: 'fixture_yard', version: 1, label: 'Terraces' },
    extent: { widthMm: 40_000, depthMm: 30_000, enclosure: 'open' },
    arrival: { positionMm: [10_000, 6000, 10_006], facingMm: [0, 1] },
    slots: [
      ground('site:ground', 'ground.default', [0, 0, 40_000, 30_000], 10_000),
      ground('zone:upper', 'ground.terrace', [2000, 5000, 20_000, 25_000], 10_006),
      ground('zone:lower', 'ground.terrace', [24_000, 5000, 38_000, 25_000], 8006),
    ],
    walk: { floorMm: [0, 0, 40_000, 30_000], blockersMm: [], keepOutMm: [] },
    seats: [],
    land: {
      land_sha256: 'd'.repeat(64), chunk_mm: 128_000,
      chunks: [{ chunk: [-1, 0], sha256: named(stepChunk(-1, 0)) }, { chunk: [0, 0], sha256: named(stepChunk(0, 0)) }],
      backdrop_sha256: named(stepBackdrop()),
      water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
    },
  });
}

/** One upright card for each plant piece, its back 20 mm in front of its foot, handed to the dresser as fetched pieces. */
function trailingCards(): FetchedPieces {
  const card = (digest: string) => {
    const lod0 = {
      primitives: [{
        material: 0,
        positions: new Float32Array([-0.25, 0, 0.02, 0.25, 0, 0.02, 0.25, 0.35, 0.06, -0.25, 0.35, 0.06]),
        normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1]),
        uvs: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]),
        indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
      }],
      materials: [{
        baseColour: { image: 0, wrapS: 'clamp' as const, wrapT: 'clamp' as const }, normal: null, baseColourFactor: [1, 1, 1, 1] as const,
        metalness: 0, roughness: 1, alphaCutoff: 0.5, doubleSided: true,
      }],
      images: [{ bytes: new Uint8Array(4), mediaType: 'image/png' as const }],
      triangles: 2,
      bounds: [-0.25, 0, 0.02, 0.25, 0.35, 0.06] as const,
    };
    return { groups: [], triangles: 2, bounds: lod0.bounds, textured: { lod0, lod1: null, lod0Images: [digest], lod1Images: [] } };
  };
  const pieces = new Map<string, ReturnType<typeof card>>();
  for (const role of ['plant.grass_tuft', 'plant.wildflowers']) {
    const module = trailingPack.modules[role]!;
    const file = module.files.get(module.variants[0]!.file)!;
    pieces.set(`${String(module.stated)}:${file.sha256}`, card(file.sha256));
  }
  const picture = { width: 2, height: 2, rgba: new Uint8Array(16).fill(200) };
  return { pieces, pictures: new Map([...pieces.values()].map((piece) => [piece.textured.lod0Images[0]!, picture])) } as unknown as FetchedPieces;
}

/** Dress the terraces in the trailing pack under its windy look, and say what hung, where, and what was left after. */
function dressedTerraces() {
  const drawing = terracesDrawing();
  const land = readSiteLand(drawing, new Map([['-1,0', stepChunk(-1, 0)], ['0,0', stepChunk(0, 0)]]), stepBackdrop(), digestOf, 1234);
  const summaries: SiteDressingSummary[] = [];
  const preset = TRAILING.light!.presets[TRAILING.light!.default_preset]!;
  const look = renderLookOfPreset(preset, TRAILING.shading!, TRAILING.edge, 1, TRAILING.water);
  const dresser = packSiteDresser({ pack: trailingPack, families, pieces: trailingCards(), shading: { model: 'pbr', toon: null, ink: null }, look, told: (summary) => summaries.push(summary) });
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const environmentRoot = new pc.Entity('environment');
  app.root.addChild(environmentRoot);
  let during: { trail: string | undefined; instanced: string | undefined; translations: number[][]; casting: boolean[]; sways: boolean[]; buffers: pc.VertexBuffer[] } | null = null;
  siteMount(drawing, {
    servedBytes: 1, land,
    dress: (host, drawn, dressing, scenery, environment, siteLand) => {
      const undress = dresser(host, drawn, dressing, scenery, environment, siteLand);
      const instances = (drawn.root.find((node) => node.name.startsWith('style-pack:instanced:trail:')) as pc.Entity[])
        .flatMap((cell) => cell.render?.meshInstances ?? []);
      const translations = instances.filter((instance) => instance.instancingData !== null).flatMap((instance) => {
        const matrices = new Float32Array(instance.instancingData!.vertexBuffer!.lock());
        const out: number[][] = [];
        for (let at = 0; at < instance.instancingCount * 16; at += 16) out.push([matrices[at + 12]!, matrices[at + 13]!, matrices[at + 14]!]);
        return out;
      });
      during = {
        trail: canvas.dataset['siteTrail'],
        instanced: canvas.dataset['sitePieceInstances'],
        translations,
        // Whether each trailing cell's first level casts a shadow, as the drawing chose at creation.
        casting: instances.filter((instance) => instance.visible).map((instance) => instance.castShadow),
        // Whether each trailing cell's material is the wind's.
        sways: instances.map((instance) => String(instance.material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('transformCoreVS') ?? '').includes('exuWindRestPosition')),
        buffers: instances.flatMap((instance) => { const buffer = instance.instancingData?.vertexBuffer; return buffer === undefined || buffer === null ? [] : [buffer]; }),
      };
      return undress;
    },
  }).attach({ app, camera, environmentRoot }).dispose();
  // The trailing cells' instance buffers still held by the device once the site is taken back.
  const held = during!.buffers.filter((buffer) => app.graphicsDevice.buffers.has(buffer)).length;
  return { drawing, land, summary: summaries[0]!, during: during!, after: { trail: canvas.dataset['siteTrail'], held } };
}

describe('a site on land dressed in a pack with trailing plants', () => {
  it('hangs them over the upper terrace\'s edge down the fall as instanced pieces just proud of its face, swaying, and takes them back', () => {
    const { drawing, land, summary, during, after } = dressedTerraces();
    const upper = drawing.slots.find((slot) => slot.identity === 'zone:upper')!;
    const lower = drawing.slots.find((slot) => slot.identity === 'zone:lower')!;
    const sizeOfPiece = (role: string, pick: number) => {
      const module = trailingPack.modules[role]!;
      return module.variants[Math.floor(pick * module.variants.length)]!.size_mm;
    };
    const rule = trailingPack.trail['ground.default']!;
    const expected = growTrailers([{ slot: upper, rule }, { slot: lower, rule }], land, drawing.slots, { sizeOf: sizeOfPiece }).points;
    // Half the 20 m run in tufts 500 mm wide and 350 mm tall, each hanging half the 2.24 m face: seven of them.
    expect(expected).toHaveLength(7);
    const said = { pieces: 7, terraces: 1, walled: 0, leftOut: 0, untried: 0 };
    expect(summary.trail).toEqual(said);
    expect(JSON.parse(during.trail!)).toEqual(said);
    expect(JSON.parse(during.instanced!).instances).toBe(7);
    expect(after).toEqual({ trail: undefined, held: 0 });
    expect(during.buffers.length).toBeGreaterThan(0);
    // The face falls 2 m over 1 m east from the lip at 20 m: its normal away from the land is (2, 0, 1) over root 5, east and up.
    // Each tuft is scaled whole from the card's 0.35 m to its hang, its back (0.02 m out) 30 mm in front of the face at its top.
    const root5 = Math.sqrt(5);
    const want = expected.map((point) => {
      const out = CLIMB_STANDOFF_M - 0.02 * (point.hangM / 0.35);
      return [20 + (2 / root5) * out, 10 + (1 / root5) * out, -point.alongMm / 1000].map((value) => value.toFixed(3)).join(',');
    }).sort();
    expect(during.translations.map((one) => one.map((value) => value.toFixed(3)).join(',')).sort()).toEqual(want);
    // A plant lying on its face casts no shadow within the trees' reach: it takes the climbers' reach, by default none.
    expect(during.casting.length).toBeGreaterThan(0);
    expect(during.casting.every((cast) => !cast)).toBe(true);
    // The look's wind sways the plant family, and the trailing cells draw with the pieces' own swaying materials.
    expect(during.sways.length).toBeGreaterThan(0);
    expect(during.sways.every(Boolean)).toBe(true);
  });
});
