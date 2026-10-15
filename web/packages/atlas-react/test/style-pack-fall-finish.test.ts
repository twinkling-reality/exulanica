// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { readStylePackManifest, readSurfaceMaterials, resolveStylePack, type LookFamily, type StylePackManifest } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { parseStructuredSiteDrawing, readSiteLand, siteMount, type SiteLand, type StructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';
import { FALLING_WATER_DEFAULTS, validateRenderLook, type RenderLook, type TileLook } from '../src/playcanvas/generated-tile/look.js';
import { applyFallFinish, withFallFinish } from '../src/playcanvas/style-pack/fall-finish.js';
import { readSurfaceFinish } from '../src/playcanvas/style-pack/ground-finish.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import { packSiteDresser } from '../src/playcanvas/style-pack/site-dresser.js';

/*
 * A cascade's pools and falls on a site on land, dressed by a pack: the land and its cascade are
 * site-land.test.ts's fixture (its lattice, backdrop and the two pools with the fall between).
 */
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const FINISH = readSurfaceFinish(JSON.parse(readFileSync('../assets/catalogs/world-kinds/surface-finish.v2.json', 'utf8')));
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
const chunks = (): Map<string, unknown> => new Map([['-1,0', chunkDocument(-1, 0)], ['0,0', chunkDocument(0, 0)]]);
const POOL = { id: 'falls pool 0', kind: 'pool', level_mm: 9000, rect_mm: [-20_000, 40_000, -16_000, 60_000] };
const FALL = { id: 'falls fall 0', kind: 'fall', level_mm: 9000, bottom_mm: 7000, rect_mm: [-20_000, 38_000, -16_000, 38_000], side: 'south' };
const LOWER = { id: 'falls pool 1', kind: 'pool', level_mm: 7000, rect_mm: [-20_000, 20_000, -16_000, 36_000] };
const cascade = (): StructuredSiteDrawing => {
  const document = structuredClone(FIXTURE);
  (document['land'] as { water: unknown[] }).water.push(POOL, FALL, LOWER);
  return parseStructuredSiteDrawing(document);
};
const landOf = (drawing: StructuredSiteDrawing): SiteLand => readSiteLand(drawing, chunks(), backdropDocument(), sha256, 1234);
function nullApp(): { app: pc.AppBase; camera: pc.Entity; environmentRoot: pc.Entity } {
  const canvas = document.createElement('canvas');
  canvas.width = 0;
  canvas.height = 0;
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
  return { app, camera, environmentRoot };
}

const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { context: { texture_sets: string[] }; cases: { name: string; manifest: StylePackManifest }[] };
const LOOK_FAMILIES = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(LOOK_FAMILIES.entries.map((entry) => [entry.key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const manifest = (name: string): StylePackManifest => structuredClone(CASES.cases.find((one) => one.name === name)!.manifest);
const PBR = { model: 'pbr', toon: null, ink: null } as const;
const watered = manifest('a pack with a falling water finish');
const lookOf = (falling: boolean): TileLook => renderLookOfPreset(
  watered.light!.presets[watered.light!.default_preset]!, watered.shading!, watered.edge, 1, watered.water, falling ? watered.falling_water : undefined,
);

/** What each of the land's waters wears, dressed by `pack` under `look`. */
interface Worn { readonly name: string; readonly chunks: ReadonlyMap<string, string>; readonly diffuse: readonly number[]; readonly parameters: ReadonlyMap<string, unknown> }
function dressed(pack: StylePackManifest, look: TileLook): Map<string, Worn> {
  const { app, camera, environmentRoot } = nullApp();
  const drawing = cascade();
  const resolved = resolveStylePack([readStylePackManifest(pack, { families, textureSets: new Set(CASES.context.texture_sets) })]);
  const dress = packSiteDresser({ pack: resolved, families, pieces: { pieces: new Map() }, shading: PBR, materials: MATERIALS, finish: FINISH, look });
  const attachment = siteMount(drawing, { servedBytes: 1, land: landOf(drawing), materials: MATERIALS, dress, look }).attach({ app, camera, environmentRoot });
  const out = new Map<string, Worn>();
  for (const id of ['sea', 'falls pool 0', 'falls fall 0', 'falls pool 1']) {
    const material = (environmentRoot.findByName(`site-land:water:${id}`) as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial;
    const glsl = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    out.set(id, {
      name: material.name,
      chunks: new Map([...glsl.keys()].map((key) => [key, String(glsl.get(key))])),
      diffuse: [material.diffuse.r, material.diffuse.g, material.diffuse.b].map((c) => Math.round(c * 255)),
      parameters: new Map(['exuFallShape', 'exuFallMotion', 'exuFallFoam'].map((key) => [key, (material.getParameter(key) as { data?: unknown } | undefined)?.data])),
    });
  }
  attachment.dispose();
  return out;
}
const swatchOf = (key: string): readonly number[] => MATERIALS.materials.find((one) => one.key === key)!.swatch.srgb8;
const close = (actual: unknown, expected: readonly number[]): void => {
  expect(Array.from(actual as ArrayLike<number>)).toHaveLength(expected.length);
  Array.from(actual as ArrayLike<number>).forEach((value, index) => expect(value).toBeCloseTo(expected[index]!, 5));
};

describe('a cascade on a site on land, dressed', () => {
  it('wears the lake\'s water on a pool where the look states no pool, with the depth water and a pond\'s ripple', () => {
    const worn = dressed(manifest('a complete pack with no base'), lookOf(false));
    const pool = worn.get('falls pool 0')!;
    expect(pool.name).toBe('style-pack:land-water:pool:falls pool 0');
    expect(pool.diffuse).toEqual([...swatchOf('lake')]);
    expect(pool.chunks.get('opacityPS')).toContain('getLinearScreenDepth');
    // A pool is near, inside the site: it keeps the ripple the sea and lakes go without.
    expect(pool.chunks.has('normalMapPS')).toBe(true);
    expect(worn.get('sea')!.chunks.has('normalMapPS')).toBe(false);
    expect(worn.get('falls pool 1')!.diffuse).toEqual([...swatchOf('lake')]);
  });

  it('wears the look\'s own pool water where the look states one', () => {
    const pack = manifest('a complete pack with no base');
    (pack.palette.swatches as unknown as object[]).push({ key: 'pool_teal', srgb8: [20, 170, 160], roughness_permille: 100, metalness_permille: 0, emission_permille: 0 });
    (pack.surfaces as Record<string, unknown>)['water.pool'] = { swatch: 'pool_teal', up: null };
    const worn = dressed(pack, lookOf(false));
    expect(worn.get('falls pool 0')!.diffuse).toEqual([20, 170, 160]);
    // The fall is not a pool: it is the lake's water still.
    expect(worn.get('falls fall 0')!.diffuse).toEqual([...swatchOf('lake')]);
  });

  it('finishes a fall with streaks down it and foam where it lands, by the defaults where the look states none', () => {
    const fall = dressed(manifest('a complete pack with no base'), lookOf(false)).get('falls fall 0')!;
    expect(fall.name).toBe('style-pack:land-water:fall:falls fall 0');
    expect(fall.chunks.get('diffusePS')).toContain('exuFallBase();');
    // Its foam stands on 7 m, where it lands; it faces south, so its sheet runs east and west.
    close(fall.parameters.get('exuFallShape'), [7, FALLING_WATER_DEFAULTS.foamHeightM, FALLING_WATER_DEFAULTS.streakWidthM, FALLING_WATER_DEFAULTS.streakLengthM]);
    close(fall.parameters.get('exuFallMotion'), [1, 0, FALLING_WATER_DEFAULTS.streakSpeedMps, FALLING_WATER_DEFAULTS.streakContrast]);
    close(fall.parameters.get('exuFallFoam'), [...FALLING_WATER_DEFAULTS.foam, FALLING_WATER_DEFAULTS.aeration]);
    // No depth and no ripple on a sheet standing upright.
    expect(fall.chunks.has('normalMapPS')).toBe(false);
    expect(fall.chunks.has('opacityPS')).toBe(false);
  });

  it('finishes a fall by the look\'s own falling water where it states one', () => {
    const fall = dressed(manifest('a complete pack with no base'), lookOf(true)).get('falls fall 0')!;
    const stated = watered.falling_water!;
    close(fall.parameters.get('exuFallShape'), [7, stated.foam_height_mm / 1000, stated.streak_width_mm / 1000, stated.streak_length_mm / 1000]);
    close(fall.parameters.get('exuFallMotion'), [1, 0, stated.streak_speed_mm_per_s / 1000, stated.streak_contrast_permille / 1000]);
    expect((fall.parameters.get('exuFallFoam') as ArrayLike<number>)[3]).toBeCloseTo(stated.aeration_permille / 1000, 5);
  });
});

describe('a look\'s falling water', () => {
  // A render look is refused whole for a key or a figure its validator does not know, and a refused
  // look is drawn another way: the section must pass the validator the page reads every look through.
  const stated = lookOf(true) as RenderLook;
  it('passes the page\'s validation of a whole render look, in the look\'s units', () => {
    const read = validateRenderLook(JSON.parse(JSON.stringify(stated)));
    expect(read.fallingWater).toEqual({
      streakSpeedMps: 4, streakWidthM: 0.25, streakLengthM: 2, streakContrast: 0.4, aeration: 0.5, foamHeightM: 1.2,
      foam: stated.fallingWater!.foam,
    });
    expect(validateRenderLook(JSON.parse(JSON.stringify(lookOf(false)))).fallingWater).toBeUndefined();
  });

  it('refuses a figure out of its range or a key the look does not state', () => {
    const whole = JSON.parse(JSON.stringify(stated)) as { fallingWater: Record<string, unknown> };
    expect(() => validateRenderLook({ ...whole, fallingWater: { ...whole.fallingWater, aeration: 1.5 } })).toThrow(/fallingWater\.aeration/);
    expect(() => validateRenderLook({ ...whole, fallingWater: { ...whole.fallingWater, spray: 1 } })).toThrow(/fallingWater/);
  });
});

describe('the fall finish', () => {
  it('is set into a colour chunk once, and refused where there is no colour function to set it after', () => {
    const chunk = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n\tdAlbedo = material_diffuse;\n}\n';
    const once = withFallFinish(chunk);
    expect(once).toContain('void exuFallBase() {');
    expect(withFallFinish(once)).toBe(once);
    expect(() => withFallFinish('void main() {}')).toThrow('no one colour function');
  });

  it('leaves the flat colour on a WebGPU device, and keeps no time for it', () => {
    const { app } = nullApp();
    const material = new pc.StandardMaterial();
    const webgpu = { ...app.graphicsDevice, isWebGPU: true } as unknown as pc.GraphicsDevice;
    expect(applyFallFinish(webgpu, material, FALLING_WATER_DEFAULTS, { bottomM: 0, acrossEast: true })).toBe(false);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('diffusePS')).toBe(false);
    expect(material.getParameter('exuFallShape')).toBeUndefined();
  });

  it('runs its sheet north and south for a fall facing east or west', () => {
    const { app } = nullApp();
    const material = new pc.StandardMaterial();
    expect(applyFallFinish(app.graphicsDevice, material, FALLING_WATER_DEFAULTS, { bottomM: 2, acrossEast: false })).toBe(true);
    close((material.getParameter('exuFallMotion') as { data: unknown }).data, [0, 1, FALLING_WATER_DEFAULTS.streakSpeedMps, FALLING_WATER_DEFAULTS.streakContrast]);
  });
});

describe('a site\'s waters dressed under a look that states how water meets solids', () => {
  const CONTACT = { wetKeep: 0.6, lightDown: 0.5, shallowFacing: 1, foamReachM: { 'water.sea': 2.5, 'water.pool': 0.8, 'water.trough': 1 } };
  const stating = (contact: boolean): TileLook => {
    const look = lookOf(false) as RenderLook;
    return contact ? { ...look, water: { ...look.water!, contact: CONTACT } } : look;
  };
  /** Each water's material by its entity: the land's, and the pond and a trough, two roles drawn in the pond's one surface. */
  function worn(look: TileLook): Map<string, pc.StandardMaterial> {
    const { app, camera, environmentRoot } = nullApp();
    const document = structuredClone(FIXTURE);
    (document['land'] as { water: unknown[] }).water.push(POOL, FALL, LOWER);
    const slots = document['slots'] as Record<string, unknown>[];
    const pond = slots.find((slot) => slot['lookRole'] === 'water.pond')!;
    slots.push({ ...pond, identity: 'trough', label: 'trough', lookRole: 'water.trough', positionMm: [7000, 2500, 6500] });
    const drawing = parseStructuredSiteDrawing(document);
    const resolved = resolveStylePack([readStylePackManifest(manifest('a complete pack with no base'), { families, textureSets: new Set(CASES.context.texture_sets) })]);
    const dress = packSiteDresser({ pack: resolved, families, pieces: { pieces: new Map() }, shading: PBR, materials: MATERIALS, finish: FINISH, look });
    const attachment = siteMount(drawing, { servedBytes: 1, land: landOf(drawing), materials: MATERIALS, dress, look }).attach({ app, camera, environmentRoot });
    const out = new Map<string, pc.StandardMaterial>();
    for (const name of ['site-land:water:sea', 'site-land:water:falls pool 0', 'site-land:water:falls fall 0', 'pond:shape', 'trough:shape']) {
      out.set(name, (app.root.findByName(name) as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial);
    }
    attachment.dispose();
    return out;
  }
  const reach = (material: pc.StandardMaterial): number | undefined => (material.getParameter('exuWaterContact') as { data: Float32Array } | undefined)?.data[2];

  it('foams each land water by the role its own kind asks for, a pool wearing the lake\'s water included', () => {
    const waters = worn(stating(true));
    expect(reach(waters.get('site-land:water:sea')!)).toBeCloseTo(2.5, 6);
    expect(reach(waters.get('site-land:water:falls pool 0')!)).toBeCloseTo(0.8, 6);
    expect(waters.get('site-land:water:falls fall 0')!.getParameter('exuWaterContact')).toBeUndefined();
  });

  it('keeps a material for each role two slot waters ask for where it states contact, and shares one as before where it does not', () => {
    const met = worn(stating(true));
    expect(met.get('pond:shape')!.name).toBe(met.get('trough:shape')!.name);
    expect(met.get('pond:shape')).not.toBe(met.get('trough:shape'));
    expect(reach(met.get('trough:shape')!)).toBeCloseTo(1, 6);
    expect(reach(met.get('pond:shape')!)).toBe(0);
    const today = worn(stating(false));
    expect(today.get('pond:shape')).toBe(today.get('trough:shape'));
    expect(today.get('pond:shape')!.getParameter('exuWaterContact')).toBeUndefined();
  });
});
