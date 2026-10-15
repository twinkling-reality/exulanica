// @vitest-environment happy-dom
/**
 * What grows on the land itself: a look's land cover, scattered over the near land by the surface
 * role the land is drawn in at each point (`landBandAt`), within each rule's slope, height and reach,
 * never under the place's slots, on wet land or by a fall, held to its guard, and drawn by the
 * dresser as instanced textured pieces.
 *
 * The land in the scatter's tests is a function written here; the dresser's is the synthetic site on
 * land of `fixtures/site-land.v5.json`, rebuilt as `site-land.test.ts` rebuilds it.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  LAND_SURFACE_GROUND, readLandSurfaces, readStylePackManifest, resolveStylePack,
  type LandChunk, type LandWater, type LookFamily, type StylePackLandCover, type StylePackManifest,
} from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing, readSiteLand, siteMount, type StructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';
import { FALL_CLEAR_MM, LAND_COVER_PLACEMENTS_MAX, LAND_COVER_TRIES_MAX, growLandCover, landCoverGroves, landSlopePermille, type LandCoverLand } from '../src/playcanvas/style-pack/land-cover.js';
import { packSiteDresser, type FetchedPieces, type SiteDressingSummary } from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const SURFACES = readLandSurfaces(readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8'));
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const MANIFEST = CASES.cases.find((one) => one.name === 'a pack growing grass near the place and flowers on planted slopes of its land')!.manifest;
const pack = resolveStylePack([readStylePackManifest(MANIFEST, { families, textureSets: new Set(CASES.context.texture_sets) })]);

const rule = (role: string, over: Partial<StylePackLandCover> = {}): StylePackLandCover =>
  ({ role, pieces: ['plant.grass_tuft'], density_per_ha: 400, scale_permille: [800, 1200], seed: 3, ...over });
const chunk = (chunkX: number, chunkY: number): LandChunk =>
  ({ chunkX, chunkY, cellMm: 1000, samplesPerSide: 129, heightMm: new Int32Array(129 * 129), sha256: '' });
/** Two chunks east of each other: the west one level at 20 m, the east one rising 1,500 per mille east, as steep as rock. */
const steepEast = (eastMm: number): number => 20_000 + (eastMm >= 128_000 ? 1.5 * (eastMm - 128_000) : 0);
const LAND: LandCoverLand = {
  // Listed farthest first: the scatter takes the chunks nearest the place first whatever their order.
  chunks: [chunk(1, 0), chunk(0, 0)], groundMm: (east) => steepEast(east), dryAt: () => true, waters: [], surfaces: SURFACES,
};
const PLACE = { placeMm: [0, 0, 20_000, 20_000] as const, keepOutMm: [] };
/** How many pieces a rule's density gives one 128 m chunk. */
const perChunk = (density: number) => Math.round(1.6384 * density);

describe('the land\'s slope', () => {
  it('is rise per run in per mille, over one cell each way, in any direction', () => {
    expect(landSlopePermille((east) => east / 10, 50_000, 50_000)).toBeCloseTo(100, 9);
    expect(landSlopePermille((east, north) => (east + north) / 10, 50_000, 50_000)).toBeCloseTo(100 * Math.SQRT2, 9);
    expect(landSlopePermille(() => 7000, 50_000, 50_000)).toBe(0);
  });
});

describe('land cover\'s scatter', () => {
  it('grows a role\'s rule only where the land is drawn in that role: its ground on the level, rock on the steep', () => {
    const level = growLandCover({ grass: rule('land') }, LAND, PLACE);
    // All of the level chunk but a point or two at its east edge, whose slope reads the steep land a cell away.
    expect(level.points.length).toBeLessThanOrEqual(perChunk(400));
    expect(level.points.length).toBeGreaterThan(perChunk(400) - 5);
    expect(level.points.every((point) => point.eastM < 128 && point.role === LAND_SURFACE_GROUND)).toBe(true);
    expect(level.byRole).toEqual({ land: level.points.length });
    const rock = growLandCover({ scree: rule('rock') }, LAND, PLACE);
    expect(rock.points.length).toBeGreaterThan(perChunk(400) - 5);
    expect(rock.points.every((point) => point.eastM >= 128 && point.role === 'rock')).toBe(true);
    // Each piece stands on the land under it.
    expect(rock.points.every((point) => Math.abs(point.upM * 1000 - steepEast(point.eastM * 1000)) < 1e-6)).toBe(true);
    // The same every time, and another seed grows elsewhere.
    expect(growLandCover({ grass: rule('land') }, LAND, PLACE)).toEqual(level);
    expect(growLandCover({ grass: rule('land', { seed: 4 }) }, LAND, PLACE).points[0]).not.toEqual(level.points[0]);
    // Two rules may grow in one role, each at its own density.
    expect(growLandCover({ grass: rule('land'), trees: rule('land', { density_per_ha: 20, seed: 8 }) }, LAND, PLACE).byRole['land']).toBeGreaterThan(level.points.length);
  });

  it('reads every point as the land\'s own ground where no surface catalog is handed over', () => {
    expect(growLandCover({ grass: rule('land') }, { ...LAND, surfaces: null }, PLACE).points.length).toBe(2 * perChunk(400));
  });

  it('grows sand only by a sea, low down', () => {
    const shore: LandCoverLand = { ...LAND, chunks: [chunk(0, 0)], groundMm: () => 800 };
    const sea: LandWater = { id: 'sea', kind: 'sea', levelMm: 0, side: 'south' };
    expect(growLandCover({ beach: rule('sand') }, { ...shore, waters: [sea] }, PLACE).points.length).toBe(perChunk(400));
    expect(growLandCover({ beach: rule('sand') }, shore, PLACE).points.length).toBe(0);
  });

  it('keeps within its slope, its height and its reach of the place', () => {
    // Rock wins only from about 750 per mille at the most the noise lowers it, so a window to 700 grows none.
    expect(growLandCover({ scree: rule('rock', { slope_permille: [0, 700] }) }, LAND, PLACE).points.length).toBe(0);
    expect(growLandCover({ grass: rule('land', { height_mm: [0, 10_000] }) }, LAND, PLACE).points.length).toBe(0);
    const near = growLandCover({ grass: rule('land', { within_mm: 30_000 }) }, LAND, PLACE);
    expect(near.points.length).toBeGreaterThan(0);
    expect(near.points.every((point) => point.eastM <= 50 && point.northM <= 50)).toBe(true);
  });

  it('grows nowhere a slot of the place lies, the land is wet, or within its clearance of a fall', () => {
    const fall: LandWater = { id: 'fall', kind: 'fall', levelMm: 21_000, bottomMm: 20_000, rectMm: [40_000, 60_000, 80_000, 60_000], side: 'south' };
    const kept = growLandCover({ grass: rule('land') }, { ...LAND, waters: [fall], dryAt: (east) => east > 10_000 }, {
      placeMm: PLACE.placeMm, keepOutMm: [[20_000, 20_000, 40_000, 40_000]],
    });
    expect(kept.points.length).toBeGreaterThan(0);
    expect(kept.points.some((point) => point.eastM * 1000 <= 10_000)).toBe(false);
    expect(kept.points.some((point) => point.eastM >= 20 && point.eastM <= 40 && point.northM >= 20 && point.northM <= 40)).toBe(false);
    const byFall = (point: { eastM: number; northM: number }) => point.eastM >= 40 && point.eastM <= 80 && Math.abs(point.northM * 1000 - 60_000) <= FALL_CLEAR_MM;
    expect(kept.points.some(byFall)).toBe(false);
  });

  it('is held to its guard, counting only pieces that grow, and to its bound on tries', () => {
    const all = growLandCover({ a_grass: rule('land'), b_scree: rule('rock') }, LAND, PLACE).points.length;
    const held = growLandCover({ a_grass: rule('land'), b_scree: rule('rock') }, LAND, { ...PLACE, most: 100 });
    expect(held.points.length).toBe(100);
    expect(held.leftOut).toBe(all - 100);
    // Rules in their keys' order: the grass before the scree, so the level chunk keeps its 100.
    expect(held.points.every((point) => point.role === LAND_SURFACE_GROUND)).toBe(true);
    const tried = growLandCover({ grass: rule('land') }, LAND, { ...PLACE, tries: 1000 });
    // Nearest chunk first: the level chunk's points are all tried, the steep chunk's partly.
    expect(tried.untried).toBe(2 * perChunk(400) - 1000);
    expect(tried.points).toEqual(growLandCover({ grass: rule('land') }, LAND, PLACE).points);
    expect([LAND_COVER_PLACEMENTS_MAX, LAND_COVER_TRIES_MAX]).toEqual([60_000, 240_000]);
  });
});

describe('land cover gathered in groves', () => {
  /** Two level chunks, every point the land's own ground. */
  const LEVEL: LandCoverLand = { ...LAND, groundMm: () => 20_000, surfaces: null };
  const grove = { size_mm: [8000, 16_000] as const, cover_permille: 250, share_permille: 900 };
  const grown = (clump: StylePackLandCover['clump'], seed = 3) => growLandCover({ grass: rule('land', { density_per_ha: 2000, seed, ...(clump === undefined ? {} : { clump }) }) }, LEVEL, PLACE);
  const shareIn = (clump: NonNullable<StylePackLandCover['clump']>, seed = 3): number => {
    const groves = landCoverGroves('grass', rule('land', { seed, clump }))!;
    const points = grown(clump, seed).points;
    return points.filter((point) => groves.inside(point.eastM * 1000, point.northM * 1000)).length / points.length;
  };

  it('grows the share it states in groves that cover about the land it states, and keeps its density over the land', () => {
    const groves = landCoverGroves('grass', rule('land', { clump: grove }))!;
    let inside = 0;
    for (let east = 500; east < 256_000; east += 1000) for (let north = 500; north < 128_000; north += 1000) if (groves.inside(east, north)) inside += 1;
    // About a quarter of the land, over the few groves two chunks hold.
    expect(inside / (256 * 128)).toBeGreaterThan(0.215);
    expect(inside / (256 * 128)).toBeLessThan(0.3);
    expect(Math.abs(shareIn(grove) - 0.9)).toBeLessThan(0.02);
    const even = grown(undefined).points.length;
    expect(Math.abs(grown(grove).points.length - even) / even).toBeLessThan(0.02);
  });

  it('grows all in groves at a share of 1000 and none at 0, and lies evenly where it states no groves', () => {
    expect(shareIn({ ...grove, share_permille: 1000 })).toBe(1);
    expect(shareIn({ ...grove, share_permille: 0 })).toBe(0);
    expect(grown(undefined).points.length).toBe(2 * perChunk(2000));
  });

  it('stands its groves on one lattice over the whole land, the same every time, elsewhere for another seed', () => {
    // Groves cover nearly all the land where the rule says so, wider then than a lattice cell.
    const dense = landCoverGroves('grass', rule('land', { clump: { ...grove, cover_permille: 990 } }))!;
    expect(dense.spacingMm).toBeLessThan(16_000);
    let inside = 0;
    for (let east = 500; east < 128_000; east += 1000) for (let north = 500; north < 128_000; north += 1000) if (dense.inside(east, north)) inside += 1;
    expect(inside / (128 * 128)).toBeGreaterThan(0.97);
    expect(grown(grove)).toEqual(grown(grove));
    expect(grown(grove, 4).points[0]).not.toEqual(grown(grove).points[0]);
    expect(landCoverGroves('grass', rule('land'))).toBeNull();
  });
});

/** The fixture's site on land, its chunks and backdrop rebuilt as `site-land.test.ts` rebuilds them. */
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const lattice = (east: number, north: number): number => 6000 + (40 * north) / 1000 + (east >= 8000 ? 500 : 0);
function chunkDocument(chunkX: number, chunkY: number): Record<string, unknown> {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(lattice(chunkX * 128_000 + i * 1000, chunkY * 128_000 + j * 1000));
  return { profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height };
}
const xs = [-400_000, -128_000, 0, 128_000, 400_000], ys = [-400_000, 0, 128_000, 400_000];
const backdropDocument = (): Record<string, unknown> => ({
  profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, 0, 128_000, 128_000], x_mm: xs, y_mm: ys,
  height_mm: ys.flatMap((y) => xs.map((x) => (y < 0 ? -20_000 : y > 128_000 ? 150_000 : lattice(x, y)))),
  water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
});

/** One upright card for each plant piece, handed to the dresser as fetched pieces. */
function fetched(): FetchedPieces {
  const card = (digest: string) => {
    const lod0 = {
      primitives: [{
        material: 0,
        positions: new Float32Array([-0.25, 0, 0, 0.25, 0, 0, 0.25, 0.35, 0, -0.25, 0.35, 0]),
        normals: new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]),
        uvs: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]),
        indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
      }],
      materials: [{
        baseColour: { image: 0, wrapS: 'clamp' as const, wrapT: 'clamp' as const }, normal: null, baseColourFactor: [1, 1, 1, 1] as const,
        metalness: 0, roughness: 1, alphaCutoff: 0.5, doubleSided: true,
      }],
      images: [{ bytes: new Uint8Array(4), mediaType: 'image/png' as const }],
      triangles: 2,
      bounds: [-0.25, 0, 0, 0.25, 0.35, 0] as const,
    };
    return { groups: [], triangles: 2, bounds: lod0.bounds, textured: { lod0, lod1: null, lod0Images: [digest], lod1Images: [] } };
  };
  const pieces = new Map<string, ReturnType<typeof card>>();
  for (const role of ['plant.grass_tuft', 'plant.wildflowers']) {
    const module = pack.modules[role]!;
    const file = module.files.get(module.variants[0]!.file)!;
    pieces.set(`${String(module.stated)}:${file.sha256}`, card(file.sha256));
  }
  const picture = { width: 2, height: 2, rgba: new Uint8Array(16).fill(200) };
  return { pieces, pictures: new Map([...pieces.values()].map((piece) => [piece.textured.lod0Images[0]!, picture])) } as unknown as FetchedPieces;
}

function dressed(drawing: StructuredSiteDrawing, dressedPack: typeof pack = pack, surfaces = SURFACES) {
  const land = readSiteLand(drawing, new Map([['-1,0', chunkDocument(-1, 0)], ['0,0', chunkDocument(0, 0)]]), backdropDocument(), sha256, 1234);
  const summaries: SiteDressingSummary[] = [];
  const dresser = packSiteDresser({ pack: dressedPack, families, pieces: fetched(), shading: { model: 'pbr', toon: null, ink: null }, landSurfaces: surfaces, told: (summary) => summaries.push(summary) });
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
  let during: { said: string | undefined; cells: number } | null = null;
  siteMount(drawing, {
    servedBytes: 1, land, landSurfaces: SURFACES,
    dress: (host, drawn, dressing, scenery, environment, siteLand) => {
      const undress = dresser(host, drawn, dressing, scenery, environment, siteLand);
      during = {
        said: canvas.dataset['siteLandCover'],
        cells: drawn.root.find((node) => node.name.startsWith('style-pack:instanced:land-cover:')).length,
      };
      return undress;
    },
  }).attach({ app, camera, environmentRoot }).dispose();
  return { summary: summaries[0]!, during: during!, after: canvas.dataset['siteLandCover'], land };
}

describe('a site on land dressed in a pack with land cover', () => {
  it('grows its grass on the land near the place as instanced pieces, off the place\'s slots, and takes it back', () => {
    const drawing = parseStructuredSiteDrawing(structuredClone(FIXTURE));
    const { summary, during, after } = dressed(drawing);
    const said = summary.landCover!;
    expect(said.pieces).toBeGreaterThan(0);
    // Gentle land, high above the sea: all of it is the land's own ground, so only that rule grows.
    expect(Object.keys(said.byRole)).toEqual(['land']);
    expect(said.byRole['land']).toBe(said.pieces);
    expect([said.leftOut, said.untried]).toEqual([0, 0]);
    expect(JSON.parse(during.said!)).toEqual(said);
    expect(during.cells).toBeGreaterThan(0);
    expect(after).toBeUndefined();
  });

  it('grows on the land under the place itself, its base ground, where nothing else of the place lies', () => {
    const drawing = parseStructuredSiteDrawing(structuredClone(FIXTURE));
    const inside = { ...pack, land_cover: { near_grass: { ...pack.land_cover['near_grass']!, within_mm: 0 } } };
    expect(dressed(drawing, inside).summary.landCover!.pieces).toBeGreaterThan(0);
  });

  it('grows by the land surface catalog it is handed: planting on the gentlest slope where a catalog says so', () => {
    const drawing = parseStructuredSiteDrawing(structuredClone(FIXTURE));
    const planted = { ...pack, land_cover: { flowers: pack.land_cover['flowers']! } };
    // The shipped catalog plants only mid slopes, and this land is gentle: nothing grows.
    expect(dressed(drawing, planted).summary.landCover!.pieces).toBe(0);
    const gentle = { ...SURFACES, bands: SURFACES.bands.map((band) => (band.key === 'planted' ? { ...band, slopePermille: [0, 1] as const } : band)) };
    expect(dressed(drawing, planted, gentle).summary.landCover!.byRole).toEqual({ planted: dressed(drawing, planted, gentle).summary.landCover!.pieces });
    expect(dressed(drawing, planted, gentle).summary.landCover!.pieces).toBeGreaterThan(0);
  });

  it('grows nothing on the land in a pack that states no land cover', () => {
    const plain = CASES.cases.find((one) => one.name === 'a pack growing grass and flowers on its lawns in a wind')!.manifest;
    const drawing = parseStructuredSiteDrawing(structuredClone(FIXTURE));
    const land = readSiteLand(drawing, new Map([['-1,0', chunkDocument(-1, 0)], ['0,0', chunkDocument(0, 0)]]), backdropDocument(), sha256, 1234);
    const summaries: SiteDressingSummary[] = [];
    const plainPack = resolveStylePack([readStylePackManifest(plain, { families, textureSets: new Set(CASES.context.texture_sets) })]);
    const dresser = packSiteDresser({ pack: plainPack, families, pieces: fetched(), shading: { model: 'pbr', toon: null, ink: null }, landSurfaces: SURFACES, told: (summary) => summaries.push(summary) });
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
    siteMount(drawing, { servedBytes: 1, land, dress: dresser }).attach({ app, camera, environmentRoot }).dispose();
    expect('landCover' in summaries[0]!).toBe(false);
  });
});
