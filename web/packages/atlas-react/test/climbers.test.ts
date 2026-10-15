// @vitest-environment happy-dom
/**
 * What climbs a site's buildings: a pack's `climb`, grown from its seed at the foot of the faces of
 * each building's box its rule lists (only those facing the sun, where it says so), spaced along each
 * face, held to its guard, and drawn by the dresser as instanced textured pieces set just proud of
 * their walls.
 *
 * The pack is the shared case that grows grass and flowers in a wind, with a climb rule added; its
 * plant pieces are stood in for by one card each, handed to the dresser as fetched pieces.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily, type StylePackClimb, type StylePackManifest } from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing, siteMount } from '../src/playcanvas/generated-site/index.js';
import { sunDirection } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import { packSiteDresser, type FetchedPieces, type SiteDressingSummary } from '../src/playcanvas/style-pack/index.js';
import { CLIMB_STANDOFF_M, boxFaces, climbRuleOf, growClimbers, towardSun, type ClimbSlot } from '../src/playcanvas/style-pack/climbers.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
families.set('structure', { fit: 'contain', dressing: 'both', fillMinimumPermille: 0, fillMaximumPermille: 0 });
const RULE: StylePackClimb = { pieces: ['plant.grass_tuft'], walls: ['back', 'left', 'right'], share_permille: 400, height_permille: [500, 500], seed: 3 };
const MANIFEST: StylePackManifest = {
  ...CASES.cases.find((one) => one.name === 'a pack growing grass and flowers on its lawns in a wind')!.manifest,
  climb: { 'structure.default': RULE },
};
const pack = resolveStylePack([readStylePackManifest(MANIFEST, { families, textureSets: new Set(CASES.context.texture_sets) })]);

/** A building 10 m wide, 6 m deep and 12 m tall at the origin, its front north. */
const HALL: ClimbSlot = { identity: 'hall', lookRole: 'structure.hall', family: 'structure', positionMm: [0, 0, 0], boxMm: [10_000, 6000, 12_000], yawQuarterTurns: 0 };
/** A plant 1 m wide and 2 m tall: at the rule's 6 m it is 3 m wide. */
const SIZE = (): readonly [number, number, number] => [1000, 400, 2000];

describe('a building\'s faces', () => {
  it('look out from its front, back and sides, the right as a viewer facing the front sees it', () => {
    const faces = boxFaces(HALL);
    expect(faces.front).toEqual({ outward: [0, 1], centreMm: [0, 3000], lengthMm: 10_000 });
    expect(faces.back).toEqual({ outward: [0, -1], centreMm: [0, -3000], lengthMm: 10_000 });
    expect(faces.right).toEqual({ outward: [-1, 0], centreMm: [-5000, 0], lengthMm: 6000 });
    expect(faces.left).toEqual({ outward: [1, 0], centreMm: [5000, 0], lengthMm: 6000 });
    // A quarter turn faces the front west; its right is then south.
    const turned = boxFaces({ ...HALL, yawQuarterTurns: 1 });
    expect(turned.front.outward).toEqual([-1, 0]);
    expect(turned.right.outward).toEqual([0, -1]);
  });

  it('meet the sun where the look\'s light comes from', () => {
    for (const azimuthDeg of [0, 90, 142, 230]) {
      const light = sunDirection({ sun: { elevationDeg: 35, azimuthDeg } });
      const length = Math.hypot(light[0], light[2]);
      const [east, north] = towardSun(azimuthDeg);
      expect(east).toBeCloseTo(-light[0] / length, 9);
      expect(north).toBeCloseTo(light[2] / length, 9);
    }
  });
});

describe('a building\'s climbing plants', () => {
  it('cover their share of each face listed, spaced evenly, rooted at its foot and facing out', () => {
    const grown = growClimbers([HALL], { 'structure.default': RULE }, { sizeOf: SIZE });
    // The back wants 4 m: two 3 m plants; each side wants 2.4 m: one.
    expect(grown.points).toHaveLength(4);
    expect([grown.buildings, grown.leftOut]).toEqual([1, 0]);
    const back = grown.points.filter((point) => point.outward[1] === -1);
    // 10 m less 6 m of plants, in three gaps of 1.33 m: their middles 2.17 m either side.
    expect(back.map((point) => point.footM[0]).sort((a, b) => a - b).map((east) => Number(east.toFixed(4)))).toEqual([-2.1667, 2.1667]);
    expect(back.every((point) => point.footM[1] === -3 && point.footM[2] === 0 && point.heightM === 6)).toBe(true);
    expect(grown.points.some((point) => point.outward[1] === 1)).toBe(false);
  });

  it('grow only on the faces within its angle of the sun, where it says so', () => {
    // A sun due east: only the left face (east) is within 60 degrees.
    const east = growClimbers([HALL], { 'structure.default': { ...RULE, sun_within_mdeg: 60_000 } }, { sizeOf: SIZE, sunAzimuthDeg: 90 });
    expect(east.points.map((point) => point.outward)).toEqual([[1, 0]]);
    // With no sun to test, every face listed grows.
    expect(growClimbers([HALL], { 'structure.default': { ...RULE, sun_within_mdeg: 60_000 } }, { sizeOf: SIZE }).points).toHaveLength(4);
  });

  it('take the building\'s own role\'s rule, else the family default, and nothing for another family', () => {
    const own = { ...RULE, walls: ['back'] as StylePackClimb['walls'] };
    expect(climbRuleOf({ 'structure.hall': own, 'structure.default': RULE }, 'structure.hall')).toBe(own);
    expect(climbRuleOf({ 'structure.default': RULE }, 'structure.hall')).toBe(RULE);
    expect(climbRuleOf({ 'structure.tower': RULE }, 'structure.hall')).toBeNull();
    expect(growClimbers([{ ...HALL, family: 'fixture', lookRole: 'fixture.default' }], { 'structure.default': RULE }, { sizeOf: SIZE }).points).toHaveLength(0);
  });

  it('grow the same plants every time from the same seed and building, and others for another building', () => {
    const varied = { ...RULE, height_permille: [200, 900] as const };
    const first = growClimbers([HALL], { 'structure.default': varied }, { sizeOf: SIZE });
    expect(growClimbers([HALL], { 'structure.default': varied }, { sizeOf: SIZE })).toEqual(first);
    const other = growClimbers([{ ...HALL, identity: 'other hall' }], { 'structure.default': varied }, { sizeOf: SIZE });
    expect(other.points.map((point) => point.heightM)).not.toEqual(first.points.map((point) => point.heightM));
  });

  it('are held to their guard: the plants met first keep their places and the rest are counted as left out', () => {
    const grown = growClimbers([HALL], { 'structure.default': RULE }, { sizeOf: SIZE, most: 3 });
    expect([grown.points.length, grown.leftOut]).toEqual([3, 1]);
  });
});

/** One upright card 0.5 m wide and 0.35 m tall, standing 0.02 to 0.06 m out from its wall, its picture two texels a side. */
function card(digest: string): FetchedPieces['pieces'] extends ReadonlyMap<string, infer P> ? P : never {
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
}

function fetched(): FetchedPieces {
  const pieces = new Map<string, ReturnType<typeof card>>();
  for (const role of ['plant.grass_tuft', 'plant.wildflowers']) {
    const module = pack.modules[role]!;
    const file = module.files.get(module.variants[0]!.file)!;
    pieces.set(`${String(module.stated)}:${file.sha256}`, card(file.sha256));
  }
  const picture = { width: 2, height: 2, rgba: new Uint8Array(16).fill(200) };
  return { pieces, pictures: new Map([...pieces.values()].map((piece) => [piece.textured!.lod0Images[0]!, picture])) };
}

/** Dress a site of one hall on a lawn in `pack`, and say what climbed and where the first plant's instance stands. */
function dressed() {
  const drawing = parseStructuredSiteDrawing({
    profile: 'exulanica.site-drawing/v1', world_id: 'world-hall', receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_path', version: 1, label: 'Hall' },
    extent: { widthMm: 40_000, depthMm: 40_000, enclosure: 'open' },
    arrival: { positionMm: [20_000, 2000, 0], facingMm: [0, 1] },
    slots: [
      { identity: 'lawn', part: 'lawn', label: 'lawn', lookRole: 'ground.lawn', positionMm: [20_000, 20_000, 0], yawQuarterTurns: 0, boxMm: [40_000, 40_000, 0], front: '+y', fit: 'surface', primitive: 'plane' },
      { identity: 'hall', part: 'hall', label: 'hall', lookRole: 'structure.hall', positionMm: [20_000, 20_000, 0], yawQuarterTurns: 0, boxMm: [10_000, 6000, 12_000], front: '+y', fit: 'contain', primitive: 'box' },
    ],
    walk: { floorMm: [0, 0, 40_000, 40_000], blockersMm: [], keepOutMm: [] },
    seats: [],
  });
  const summaries: SiteDressingSummary[] = [];
  const preset = MANIFEST.light!.presets[MANIFEST.light!.default_preset]!;
  const look = renderLookOfPreset(preset, MANIFEST.shading!, MANIFEST.edge, 1, MANIFEST.water);
  const dresser = packSiteDresser({ pack, families, pieces: fetched(), shading: { model: 'pbr', toon: null, ink: null }, look, told: (summary) => summaries.push(summary) });
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
  let during: { climb: string | undefined; translations: number[][]; casting: boolean[] } | null = null;
  const attached = siteMount(drawing, {
    servedBytes: 1,
    dress: (host, drawn, dressing) => {
      const undress = dresser(host, drawn, dressing);
      const translations = (drawn.root.find((node) => node.name.startsWith('style-pack:instanced:climb:')) as pc.Entity[])
        .flatMap((cell) => cell.render?.meshInstances ?? [])
        .filter((instance) => instance.instancingData !== null)
        .flatMap((instance) => {
          const matrices = new Float32Array(instance.instancingData!.vertexBuffer!.lock());
          const out: number[][] = [];
          for (let at = 0; at < instance.instancingCount * 16; at += 16) out.push([matrices[at + 12]!, matrices[at + 13]!, matrices[at + 14]!]);
          return out;
        });
      // Whether each climbing cell's first level casts a shadow, as the drawing chose at creation.
      const casting = (drawn.root.find((node) => node.name.startsWith('style-pack:instanced:climb:')) as pc.Entity[])
        .flatMap((cell) => cell.render?.meshInstances ?? [])
        .filter((instance) => instance.visible)
        .map((instance) => instance.castShadow);
      during = { climb: canvas.dataset['siteClimb'], translations, casting };
      return undress;
    },
  }).attach({ app, camera, environmentRoot });
  attached.dispose();
  return { summaries, during: during!, after: canvas.dataset['siteClimb'] };
}

describe('a site dressed in a pack with climbing plants', () => {
  it('grows them on the hall\'s walls as instanced pieces set just proud of each face, and takes them back', () => {
    const { summaries, during, after } = dressed();
    const sizeOf = (role: string, pick: number) => {
      const module = pack.modules[role]!;
      return module.variants[Math.floor(pick * module.variants.length)]!.size_mm;
    };
    const site = { ...HALL, positionMm: [20_000, 20_000, 0] };
    const expected = growClimbers([site], pack.climb, { sizeOf, sunAzimuthDeg: preset().sun.azimuth_mdeg / 1000 });
    expect(expected.points.length).toBeGreaterThan(0);
    expect(summaries[0]!.climb).toEqual({ pieces: expected.points.length, buildings: 1, leftOut: 0 });
    expect(JSON.parse(during.climb!)).toEqual({ pieces: expected.points.length, buildings: 1, leftOut: 0 });
    expect(after).toBeUndefined();
    // Each plant scaled whole to its 6 m from the card's 0.35 m, its back (0.02 m out) 30 mm from the face.
    const scale = 6 / 0.35;
    const out = CLIMB_STANDOFF_M - 0.02 * scale;
    const want = expected.points.map((point) => [point.footM[0] + point.outward[0] * out, 0, -(point.footM[1] + point.outward[1] * out)]
      .map((value) => value.toFixed(3)).join(',')).sort();
    // The drawing's root sits at the site's origin; compare in plan, east and south.
    const got = during.translations.map(([east, , south]) => [east!, 0, south!].map((value) => value.toFixed(3)).join(',')).sort();
    expect(got).toEqual(want);
    // A plant lying on its wall casts no shadow within the trees' reach: the drawing gives climbers none.
    expect(during.casting.length).toBeGreaterThan(0);
    expect(during.casting.every((cast) => !cast)).toBe(true);
  });
});

function preset() {
  return MANIFEST.light!.presets[MANIFEST.light!.default_preset]!;
}
