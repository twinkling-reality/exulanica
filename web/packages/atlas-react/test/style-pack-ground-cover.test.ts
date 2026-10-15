// @vitest-environment happy-dom
/**
 * What grows on a site's grounds: a pack's cover, scattered from its seed over the slots of the look
 * roles it names, never where anything stands on them or lies over them, held to its guard, and drawn
 * by the dresser as instanced textured pieces that sway in the look's wind.
 *
 * The pack is the shared case that states cover and a wind (`assets/style-packs/manifest-cases.v1.json`);
 * its two plant pieces are stood in for by one card each, handed to the dresser as fetched pieces.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily, type StylePackCover, type StylePackManifest } from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing, siteMount } from '../src/playcanvas/generated-site/index.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import {
  COVER_PLACEMENTS_MAX, coverMatrix, growCover, packSiteDresser, scatterCover,
  type CoverSlot, type FetchedPieces, type SiteDressingSummary,
} from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const MANIFEST = CASES.cases.find((one) => one.name === 'a pack growing grass and flowers on its lawns in a wind')!.manifest;
const pack = resolveStylePack([readStylePackManifest(MANIFEST, { families, textureSets: new Set(CASES.context.texture_sets) })]);
const RULE: StylePackCover = pack.cover['ground.lawn']!;

const slot = (identity: string, lookRole: string, positionMm: number[], boxMm: number[], primitive = 'plane', yawQuarterTurns = 0): CoverSlot =>
  ({ identity, lookRole, positionMm, boxMm, yawQuarterTurns, primitive });
const LAWN = slot('lawn', 'ground.lawn', [10_000, 10_000, 0], [20_000, 20_000, 0]);
/** A path across the lawn's middle, laid over it, and a house standing on it. */
const PATH = slot('path', 'path.footway', [10_000, 10_000, 6], [4000, 20_000, 0]);
const HOUSE = slot('house', 'wall.default', [4000, 15_000, 0], [4000, 4000, 3000], 'box');
const BED = slot('bed', 'ground.lawn', [16_000, 4000, 0], [2000, 2000, 0], 'none');
/** What the dresser grows on the site below: the lawn's cover off its path and its bed, and none on the bed itself. */
const SITE_COVER = (): number => growCover([LAWN, PATH, BED], pack.cover, { grows: (one) => one.primitive === 'plane' }).points.length;
const inside = (point: { eastM: number; northM: number }, [west, south, east, north]: readonly number[]): boolean =>
  point.eastM * 1000 >= west! && point.eastM * 1000 <= east! && point.northM * 1000 >= south! && point.northM * 1000 <= north!;

describe('a basin\'s water', () => {
  it('lies over the lawn only where it stands above the land, so a lawn rising out of a basin grows to the water\'s edge', () => {
    // A bowl 500 mm deep at the lawn's middle, meeting the water's level 7.071 m out.
    const bowl = (east: number, north: number): number => ((east - 10_000) ** 2 + (north - 10_000) ** 2) / 100_000 - 500;
    const land = { groundMm: bowl, waters: [] };
    const lawn: CoverSlot = { ...slot('lawn', 'ground.lawn', [10_000, 10_000, -500], [20_000, 20_000, 0]), drape: true };
    const pond = slot('pond', 'water.pond', [10_000, 10_000, 0], [20_000, 20_000, 0]);
    const grown = growCover([lawn, pond], pack.cover, { land });
    expect(grown.points.every((point) => Math.hypot(point.eastM - 10, point.northM - 10) >= 7.07)).toBe(true);
    // The lawn's area less the water's disc: about 2400 less two fifths of it.
    expect(grown.points.length).toBeGreaterThan(1350);
    expect(grown.points.length).toBeLessThan(1560);
    expect(grown.points.every((point) => Math.abs(point.upM * 1000 - bowl(point.eastM * 1000, point.northM * 1000)) < 1e-6)).toBe(true);
  });
});

describe('a cover rule\'s scatter', () => {
  it('grows as many pieces as its density gives the slot\'s area, inside it, the same for the same seed and slot', () => {
    const points = scatterCover(LAWN, RULE, Number.MAX_SAFE_INTEGER);
    // 400 square metres at 600 a hundred.
    expect(points.length).toBe(2400);
    expect(points.every((point) => inside(point, [0, 0, 20_000, 20_000]))).toBe(true);
    expect(points.every((point) => point.scale >= 0.8 && point.scale <= 1.2 && RULE.pieces.includes(point.piece))).toBe(true);
    expect(new Set(points.map((point) => point.piece))).toEqual(new Set(RULE.pieces));
    expect(scatterCover(LAWN, RULE, Number.MAX_SAFE_INTEGER)).toEqual(points);
    expect(scatterCover({ ...LAWN, identity: 'lawn-2' }, RULE, 10)).not.toEqual(points.slice(0, 10));
    expect(scatterCover(LAWN, { ...RULE, seed: 8 }, 10)).not.toEqual(points.slice(0, 10));
    // Fewer room keeps the same first pieces.
    expect(scatterCover(LAWN, RULE, 10)).toEqual(points.slice(0, 10));
  });

  it('reads a turned slot\'s box across its turn', () => {
    const turned = slot('strip', 'ground.lawn', [0, 0, 0], [10_000, 2000, 0], 'plane', 1);
    const points = scatterCover(turned, RULE, Number.MAX_SAFE_INTEGER);
    expect(points.every((point) => inside(point, [-1000, -5000, 1000, 5000]))).toBe(true);
  });

  it('stands a piece upright, turned about up and scaled, at its point in renderer metres', () => {
    const matrix = coverMatrix({ piece: 'plant.grass_tuft', eastM: 3, northM: 4, yaw: Math.PI / 2, scale: 2, pick: 0 }, 1.5);
    expect([...matrix].map((n) => Number(n.toFixed(6)) + 0)).toEqual([0, 0, -2, 0, 0, 2, 0, 0, 2, 0, 0, 0, 3, 1.5, -4, 1]);
  });
});

describe('a site\'s cover', () => {
  it('grows nowhere a slot stands on its ground or another lies over it', () => {
    const grown = growCover([LAWN, PATH, HOUSE], pack.cover);
    expect(grown.slots).toBe(1);
    expect(grown.leftOut).toBe(0);
    expect(grown.points.some((point) => inside(point, [8000, 0, 12_000, 20_000]))).toBe(false);
    expect(grown.points.some((point) => inside(point, [2000, 13_000, 6000, 17_000]))).toBe(false);
    // About the lawn's area less the path's and the house's: 400 less 80 less 16 square metres.
    expect(grown.points.length).toBeGreaterThan(1700);
    expect(grown.points.length).toBeLessThan(1950);
    expect(grown.points.every((point) => point.upM === 0)).toBe(true);
  });

  it('takes the rule of the role a slot is drawn in where its own role has none, and no other', () => {
    const meadow = slot('meadow', 'ground.meadow', [10_000, 10_000, 0], [20_000, 20_000, 0]);
    expect(growCover([meadow], pack.cover).points.length).toBe(0);
    expect(growCover([meadow], pack.cover, { drawnAs: () => 'ground.lawn' }).points.length).toBe(2400);
    expect(growCover([meadow], pack.cover, { drawnAs: () => 'ground.default' }).points.length).toBe(0);
  });

  it('grows under a plane laid beneath its ground, but not on a slot that grows none or that a caller says draws no surface', () => {
    const under = slot('under', 'ground.default', [10_000, 10_000, -6], [20_000, 20_000, 0]);
    expect(growCover([under, LAWN], pack.cover).points.length).toBe(2400);
    expect(growCover([PATH], pack.cover).points.length).toBe(0);
    expect(growCover([LAWN], pack.cover, { grows: () => false }).points.length).toBe(0);
  });

  it('is held to its guard: the first slots keep theirs and the rest are counted as left out', () => {
    const other = slot('lawn-far', 'ground.lawn', [50_000, 10_000, 0], [20_000, 20_000, 0]);
    const grown = growCover([LAWN, other], pack.cover, { most: 3000 });
    expect(grown.points.length).toBe(3000);
    expect(grown.leftOut).toBe(1800);
    expect(grown.points.filter((point) => point.eastM < 30).length).toBe(2400);
    expect(COVER_PLACEMENTS_MAX).toBe(40_000);
  });

  it('on land, stands each piece of a draped ground on the land under it, and grows none where the land\'s water stands above it', () => {
    // Land rising one metre in ten east, under a sea 200 mm up: wet west of 2 m.
    const land = { groundMm: (east: number) => east / 10, waters: [{ id: 'sea', kind: 'sea' as const, levelMm: 200, side: 'west' }] };
    const draped: CoverSlot = { ...slot('slope', 'ground.lawn', [10_000, 10_000, 1000], [20_000, 20_000, 0]), drape: true };
    const grown = growCover([draped], pack.cover, { land });
    expect(grown.points.length).toBeGreaterThan(2000);
    expect(grown.points.every((point) => point.eastM >= 2)).toBe(true);
    expect(grown.points.every((point) => Math.abs(point.upM - point.eastM / 10) < 1e-9)).toBe(true);
  });
});

/** One upright card 0.5 m wide and 0.35 m tall, its picture two warm texels a side. */
function card(digest: string): FetchedPieces['pieces'] extends ReadonlyMap<string, infer P> ? P : never {
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
}

function fetchedCover(): FetchedPieces {
  const pieces = new Map<string, ReturnType<typeof card>>();
  for (const role of ['plant.grass_tuft', 'plant.wildflowers']) {
    const module = pack.modules[role]!;
    const file = module.files.get(module.variants[0]!.file)!;
    pieces.set(`${String(module.stated)}:${file.sha256}`, card(file.sha256));
  }
  const picture = { width: 2, height: 2, rgba: new Uint8Array(16).fill(200) };
  return { pieces, pictures: new Map([...pieces.values()].map((piece) => [piece.textured!.lod0Images[0]!, picture])) };
}

/** A small site's drawing of `slots`, 20 m square and open. */
const drawingOf = (slots: readonly Record<string, unknown>[]) => parseStructuredSiteDrawing({
  profile: 'exulanica.site-drawing/v1', world_id: 'world-lawn', receipt_sha256: 'a'.repeat(64),
  kind: { kind: 'fixture_path', version: 1, label: 'Lawn' },
  extent: { widthMm: 20_000, depthMm: 20_000, enclosure: 'open' },
  arrival: { positionMm: [10_000, 2000, 0], facingMm: [0, 1] },
  slots,
  walk: { floorMm: [0, 0, 20_000, 20_000], blockersMm: [], keepOutMm: [] },
  seats: [],
});
const plane = (identity: string, lookRole: string, positionMm: number[], boxMm: number[]) =>
  ({ identity, part: identity, label: identity, lookRole, positionMm, yawQuarterTurns: 0, boxMm, front: '+y', fit: 'surface', primitive: 'plane' });

/** Dress `drawing` in `dressedPack` on a null device and say what its cover grew. */
function grownOn(drawing: ReturnType<typeof drawingOf>, dressedPack: typeof pack): SiteDressingSummary['cover'] {
  const summaries: SiteDressingSummary[] = [];
  const dresser = packSiteDresser({ pack: dressedPack, families, pieces: fetchedCover(), shading: { model: 'pbr', toon: null, ink: null }, told: (summary) => summaries.push(summary) });
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
  siteMount(drawing, { servedBytes: 1, dress: dresser }).attach({ app, camera, environmentRoot }).dispose();
  return summaries[0]!.cover;
}

function site(windy: boolean) {
  const drawing = parseStructuredSiteDrawing({
    profile: 'exulanica.site-drawing/v1', world_id: 'world-lawn', receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_path', version: 1, label: 'Lawn' },
    extent: { widthMm: 20_000, depthMm: 20_000, enclosure: 'open' },
    arrival: { positionMm: [10_000, 2000, 0], facingMm: [0, 1] },
    slots: [
      { identity: 'lawn', part: 'lawn', label: 'lawn', lookRole: 'ground.lawn', positionMm: [10_000, 10_000, 0], yawQuarterTurns: 0, boxMm: [20_000, 20_000, 0], front: '+y', fit: 'surface', primitive: 'plane' },
      { identity: 'walk', part: 'walk', label: 'walk', lookRole: 'path.footway', positionMm: [10_000, 10_000, 6], yawQuarterTurns: 0, boxMm: [4000, 20_000, 0], front: '+y', fit: 'surface', primitive: 'plane' },
      // A hole only a pack fills, in the lawn's look role: the site draws no surface there, so nothing grows on it or under it.
      { identity: 'bed', part: 'bed', label: 'bed', lookRole: 'ground.lawn', positionMm: [16_000, 4000, 0], yawQuarterTurns: 0, boxMm: [2000, 2000, 0], front: '+y', fit: 'surface', primitive: 'none' },
    ],
    walk: { floorMm: [0, 0, 20_000, 20_000], blockersMm: [], keepOutMm: [] },
    seats: [],
  });
  const summaries: SiteDressingSummary[] = [];
  const preset = MANIFEST.light!.presets[MANIFEST.light!.default_preset]!;
  const still = { ...preset };
  delete (still as { wind?: unknown }).wind;
  const look = renderLookOfPreset(windy ? preset : still, MANIFEST.shading!, MANIFEST.edge, 1, MANIFEST.water);
  const dresser = packSiteDresser({ pack, families, pieces: fetchedCover(), shading: { model: 'pbr', toon: null, ink: null }, look, told: (summary) => summaries.push(summary) });
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
  let during: { instanced: string | undefined; cover: string | undefined; wind: string | undefined; animating: boolean } | null = null;
  const attached = siteMount(drawing, {
    servedBytes: 1,
    dress: (host, drawn, dressing) => {
      const undress = dresser(host, drawn, dressing);
      during = { instanced: canvas.dataset['sitePieceInstances'], cover: canvas.dataset['siteCover'], wind: canvas.dataset['siteWind'], animating: undress.animating === true };
      return undress;
    },
  }).attach({ app, camera, environmentRoot });
  attached.dispose();
  return { summaries, during: during!, after: { cover: canvas.dataset['siteCover'], wind: canvas.dataset['siteWind'] } };
}

describe('a site dressed in a pack with cover', () => {
  it('grows its lawn\'s cover off its path as instanced pieces, swaying both pieces\' materials, and takes it all back', () => {
    const { summaries, during, after } = site(true);
    const expected = SITE_COVER();
    expect(summaries[0]!.cover).toEqual({ pieces: expected, slots: 1, leftOut: 0 });
    expect(summaries[0]!.swaying).toBe(2);
    expect(JSON.parse(during.instanced!).instances).toBe(expected);
    expect(JSON.parse(during.cover!)).toEqual({ pieces: expected, slots: 1, leftOut: 0 });
    expect([during.wind, during.animating]).toEqual(['2', true]);
    expect(after).toEqual({ cover: undefined, wind: undefined });
  });

  it('grows a ground\'s cover by the surface it is drawn in: a paving in its own surface grows none, an unknown leaf drawn as the default grows the default\'s', () => {
    const dressed = {
      ...pack,
      surfaces: { ...pack.surfaces, 'ground.default': { swatch: 'cream', up: null }, 'ground.paving': { swatch: 'brick', up: null } },
      cover: { 'ground.default': RULE },
    };
    const drawing = drawingOf([
      plane('base', 'ground.default', [10_000, 10_000, 0], [20_000, 20_000, 0]),
      plane('square', 'ground.paving', [5000, 10_000, 6], [10_000, 20_000, 0]),
      plane('meadow', 'ground.meadow', [15_000, 10_000, 6], [10_000, 20_000, 0]),
    ]);
    // The base lies under both, so only the meadow grows: 200 square metres at 600 a hundred.
    expect(grownOn(drawing, dressed)).toEqual({ pieces: 1200, slots: 1, leftOut: 0 });
  });

  it('grows the same cover, still, in a look with no wind', () => {
    const { summaries, during } = site(false);
    expect(summaries[0]!.cover?.pieces).toBe(SITE_COVER());
    expect('swaying' in summaries[0]!).toBe(false);
    expect([during.wind, during.animating]).toEqual([undefined, false]);
  });
});
