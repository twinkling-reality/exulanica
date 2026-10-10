// @vitest-environment happy-dom
/**
 * A world kind's site dressed in a style pack: each slot by its look role, a surface's swatch on the
 * engine's primitive, a piece in its slot by its family's fit, the engine's primitive where the pack
 * dresses nothing, and everything put back when the site goes.
 *
 * The drawing and the pack are hand-written here. The drawing is a yard in the served shape
 * (`exulanica.site-drawing/v1`); the pack is the readers' complete case with this file's surfaces,
 * two modules and two palette pieces written below, apart from the pieces' writer. Families come
 * from the world kinds' look-family catalog, as the page reads them.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  readSiteInterior, readSiteScenery, readStylePackManifest, readSurfaceMaterials, readSurfacePatterns, resolveStylePack, sceneryBeyond,
  type LookFamily, type ResolvedStylePack, type SiteInteriorCatalog, type SiteSceneryCatalog, type StylePackFile, type SurfaceMaterials, type SurfacePatterns,
} from '@exulanica/atlas-core';
import { baseGroundSlot, ceilingRests, parseSiteDrawing, sceneryOf, siteMount, siteNavigationWorld, type SiteDrawing } from '../src/playcanvas/generated-site/index.js';
import type { RenderShading } from '../src/playcanvas/generated-tile/look.js';
import { fetchPackPieces, packSiteDresser, type FetchedPieces, type SiteDressingSummary } from '../src/playcanvas/style-pack/index.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8'));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const CATALOG = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(CATALOG.entries.map((entry) => [entry.key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));

const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const PATTERNS = readSurfacePatterns(readFileSync('../assets/catalogs/world-kinds/surface-pattern.v1.json', 'utf8'));
const SCENERY = readSiteScenery(readFileSync('../assets/catalogs/world-kinds/site-scenery.v1.json', 'utf8'));
const INTERIOR = readSiteInterior(readFileSync('../assets/catalogs/world-kinds/site-interior.v1.json', 'utf8'));
/** The colour chunk a material was given, or undefined where it draws its plain colour. */
const colourChunk = (material: pc.Material): string | undefined => (material as pc.StandardMaterial).getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined;
const colourOf = (key: string): number[] => [...MATERIALS.materials.find((material) => material.key === key)!.swatch.srgb8];

const SOIL = [120, 90, 60] as const;
const OAK = [150, 110, 70] as const;
const PBR: RenderShading = { model: 'pbr', toon: null, ink: null };
const TOON: RenderShading = { model: 'toon', toon: { shadowEdge: 0.1, lightEdge: 0.6, bandShare: 0.7, softness: 0.04 }, ink: [0.05, 0.04, 0.03] };

/** Quads, each one colour with one normal, as a palette piece. */
function paletteGlb(quads: readonly { points: number[][]; normal: number[]; srgb: readonly number[] }[]): Uint8Array<ArrayBuffer> {
  const positions = quads.flatMap((quad) => quad.points.flat());
  const normals = quads.flatMap((quad) => Array(4).fill(quad.normal).flat() as number[]);
  const colours = quads.flatMap((quad) => Array(4).fill([...quad.srgb.map((byte) => TABLE[byte]!), 65535]).flat() as number[]);
  const indices = quads.flatMap((_, q) => [0, 1, 2, 0, 2, 3].map((corner) => corner + q * 4));
  const views = [new Float32Array(positions), new Float32Array(normals), new Uint16Array(colours), new Uint16Array(indices)].map((view) => new Uint8Array(view.buffer));
  const offsets: number[] = [];
  let length = 0;
  for (const view of views) {
    offsets.push(length);
    length += Math.ceil(view.byteLength / 4) * 4;
  }
  const binary = new Uint8Array(length);
  views.forEach((view, k) => binary.set(view, offsets[k]));
  const vertices = quads.length * 4;
  const document = {
    asset: { version: '2.0' },
    accessors: [
      { bufferView: 0, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 1, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 2, componentType: 5123, count: vertices, type: 'VEC4', normalized: true },
      { bufferView: 3, componentType: 5123, count: quads.length * 6, type: 'SCALAR' },
    ],
    bufferViews: views.map((view, k) => ({ buffer: 0, byteOffset: offsets[k], byteLength: view.byteLength })),
    buffers: [{ byteLength: length }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, COLOR_0: 2 }, indices: 3 }] }],
  };
  const text = new TextEncoder().encode(JSON.stringify(document));
  const json = new Uint8Array(Math.ceil(text.byteLength / 4) * 4).fill(0x20);
  json.set(text);
  const bytes = new Uint8Array(28 + json.byteLength + binary.byteLength);
  const out = new DataView(bytes.buffer);
  out.setUint32(0, 0x46546c67, true);
  out.setUint32(4, 2, true);
  out.setUint32(8, bytes.byteLength, true);
  out.setUint32(12, json.byteLength, true);
  out.setUint32(16, 0x4e4f534a, true);
  bytes.set(json, 20);
  out.setUint32(20 + json.byteLength, binary.byteLength, true);
  out.setUint32(24 + json.byteLength, 0x004e4942, true);
  bytes.set(binary, 28 + json.byteLength);
  return bytes;
}

/** A plank door 1 m wide and 2.1 m tall, its front an oak quad. */
const DOOR = paletteGlb([{ points: [[-0.5, 0, 0.09], [0.5, 0, 0.09], [0.5, 2.1, 0.09], [-0.5, 2.1, 0.09]], normal: [0, 0, 1], srgb: OAK }]);
/** A fence panel 2 m long and 1 m tall. */
const FENCE = paletteGlb([{ points: [[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], normal: [0, 0, 1], srgb: OAK }]);
/** A tree as a town pack's is sized, 3.2 m across and 5.8 m tall: one green quad. */
const LEAF = [70, 110, 60] as const;
const TREE = paletteGlb([{ points: [[-1.6, 0, 0], [1.6, 0, 0], [1.6, 5.8, 0], [-1.6, 5.8, 0]], normal: [0, 0, 1], srgb: LEAF }]);
const PIECES: Readonly<Record<string, Uint8Array<ArrayBuffer>>> = { 'pieces/door.glb': DOOR, 'pieces/fence.glb': FENCE, 'pieces/tree.glb': TREE };

/**
 * The readers' complete case with this site's dressing: swatches for ground, walls and roofs, a
 * texture set for one wall leaf, and pieces for doors and boundaries; nothing for fixtures.
 */
function sitePack(plant = false): ResolvedStylePack {
  const manifest = structuredClone(CASES.cases.find((c: { name: string }) => c.name === 'a complete pack with no base').manifest);
  manifest['palette'].swatches.push(
    { key: 'soil', srgb8: [...SOIL], roughness_permille: 900, metalness_permille: 0, emission_permille: 0 },
    { key: 'oak', srgb8: [...OAK], roughness_permille: 700, metalness_permille: 0, emission_permille: 0 },
    ...(plant ? [{ key: 'leaf', srgb8: [...LEAF], roughness_permille: 900, metalness_permille: 0, emission_permille: 0 }] : []),
  );
  manifest['surfaces'] = {
    'ground.default': { swatch: 'soil', up: null },
    'roof.default': { swatch: 'roof_tile', up: null },
    'wall.brick_running_bond': { texture_set: 'cc0.brick-running-bond', up: null },
    'wall.default': { swatch: 'cream', up: null },
    // A pack's own stone, which colours its upward faces apart.
    'wall.stone': { swatch: 'cream', up: 'roof_tile' },
  };
  manifest['modules'] = {
    'boundary.default': { variants: [{ file: 'pieces/fence.glb', lod1: null, size_mm: [2000, 100, 1000], stretch_mm: [null, null, null] }] },
    'door.default': { variants: [{ file: 'pieces/door.glb', lod1: null, size_mm: [1000, 180, 2100], stretch_mm: [null, null, null] }] },
    // A pack with a tree of its own, as every town pack has.
    ...(plant ? { 'plant.default': { variants: [{ file: 'pieces/tree.glb', lod1: null, size_mm: [3200, 3200, 5800], stretch_mm: [null, null, null] }] } } : {}),
  };
  manifest['files'] = Object.entries(PIECES).filter(([path]) => plant || path !== 'pieces/tree.glb').map(([path, bytes]) => ({
    path, sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.byteLength, media_type: 'model/gltf-binary',
  }));
  return resolveStylePack([readStylePackManifest(manifest, { families, textureSets: new Set<string>(CASES.context.texture_sets) })]);
}

function slot(identity: string, lookRole: string, primitive: string, position: number[], yaw: number, box: number[], fit = 'contain') {
  return { identity, part: identity.split(':')[0], label: identity, lookRole, positionMm: position, yawQuarterTurns: yaw, boxMm: box, front: '+y', fit, primitive };
}

/** A yard: tilled ground, a shed of brick with a plank door and a thatched roof, a fence, a bench, a farmer and a barn only a pack fills. */
const drawing: SiteDrawing = parseSiteDrawing({
  profile: 'exulanica.site-drawing/v1',
  world_id: 'world-1',
  receipt_sha256: 'a'.repeat(64),
  kind: { kind: 'fixture_yard', version: 1, label: 'Yard' },
  extent: { widthMm: 12_000, depthMm: 12_000, enclosure: 'open' },
  arrival: { positionMm: [5000, 3000, 0], facingMm: [0, 1] },
  slots: [
    slot('ground', 'ground.tilled_soil', 'plane', [6000, 6000, 0], 0, [12_000, 12_000, 0], 'surface'),
    slot('shed:wall:0', 'wall.brick_running_bond', 'box', [3750, 7100, 0], 0, [1500, 200, 2400], 'surface'),
    slot('shed:door:0', 'door.plank', 'none', [5000, 7100, 0], 0, [1000, 200, 2100], 'fill'),
    slot('shed:roof', 'roof.thatch', 'gable', [5000, 8500, 2400], 0, [4000, 3000, 1050], 'surface'),
    slot('fence', 'boundary.picket', 'box', [6000, 500, 0], 2, [6000, 100, 1000], 'tile'),
    slot('bench', 'fixture.bench', 'box', [5000, 3000, 0], 2, [1800, 500, 450]),
    slot('farmer', 'character.farmer', 'box', [8000, 3000, 0], 0, [600, 400, 1800]),
    slot('barn', 'structure.barn', 'none', [9000, 9000, 0], 0, [4000, 4000, 4000]),
  ],
  walk: { floorMm: [0, 0, 12_000, 12_000], blockersMm: [], keepOutMm: [] },
  seats: [],
});

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

async function dressedSite(
  shading: RenderShading, materials?: SurfaceMaterials, site: SiteDrawing = drawing, patterns?: SurfacePatterns,
  beyondIt: { readonly scenery?: SiteSceneryCatalog; readonly plant?: boolean; readonly interior?: SiteInteriorCatalog } = {},
) {
  const pack = sitePack(beyondIt.plant === true);
  const pieces: FetchedPieces = await fetchPackPieces(pack, Object.keys(pack.modules), TABLE, async (file: StylePackFile) => PIECES[file.path]!);
  const summaries: SiteDressingSummary[] = [];
  const { app, camera, environmentRoot } = nullApp();
  // The pack's own light, with a ground beyond the world stated where the pack states none.
  const look = renderLookOfPreset(pack.light.presets[pack.light.default_preset]!, pack.shading, pack.edge ?? { ground: [136, 165, 96], drop_mm: 600, reach_mm: 3_000_000 });
  const mount = siteMount(site, { servedBytes: 1, look, dress: packSiteDresser({ pack, families, pieces, shading, ...(materials === undefined ? {} : { materials }), ...(patterns === undefined ? {} : { patterns }), told: (summary) => summaries.push(summary) }), ...(materials === undefined || beyondIt.scenery === undefined ? {} : { materials, scenery: beyondIt.scenery }), ...(beyondIt.interior === undefined ? {} : { interior: beyondIt.interior }) });
  const attachment = mount.attach({ app, camera, environmentRoot });
  const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
  const root = environmentRoot.findByName(`generated-site:${site.worldId}`) as pc.Entity;
  const shape = (identity: string): pc.MeshInstance => (root.findByName(`${identity}:shape`) as pc.Entity).render!.meshInstances[0]!;
  const rgb = (material: pc.Material): number[] => {
    const { r, g, b } = (material as pc.StandardMaterial).diffuse;
    return [r, g, b].map((channel) => Math.round(channel * 255));
  };
  const beyond = (): pc.Material => (app.root.findByName('generated-tile:edge-ground') as pc.Entity).render!.meshInstances[0]!.material;
  return { root, environmentRoot, attachment, summaries, shape, rgb, canvas, beyond, mount, app };
}

describe('a site dressed in a pack that carries the surface material catalog', () => {
  it('draws a leaf the pack does not state in its material, not the family default, and says what it read', async () => {
    const site = await dressedSite(PBR, MATERIALS);
    // Tilled soil, a thatched roof and a brick wall whose texture set a site cannot hold: each its own material.
    expect(site.shape('ground').material.name).toBe('style-pack:material:ground.soil');
    expect(site.rgb(site.shape('ground').material)).toEqual(colourOf('soil'));
    expect(site.shape('shed:roof').material.name).toBe('style-pack:material:roof.thatch');
    expect(site.rgb(site.shape('shed:roof').material)).toEqual(colourOf('thatch'));
    expect(site.shape('shed:wall:0').material.name).toBe('style-pack:material:wall.brick');
    // The pieces stand as before: a leaf's material never takes a slot a piece fills.
    expect((site.root.findByName('fence') as pc.Entity).enabled).toBe(false);
    expect(site.summaries).toEqual([{ surfaces: 0, materials: 3, unknownLooks: ['boundary.picket'], patterned: 0, pieces: 2, placed: 4, undressed: 2, inkSegments: 0, sceneryPieces: 0 }]);
    // The ground beyond the site wears the very material the dressed ground wears: soil to the horizon.
    expect(site.beyond()).toBe(site.shape('ground').material);
    expect(site.beyond().name).toBe('style-pack:material:ground.soil');
    expect(site.canvas.dataset['siteMaterials']).toBe('3');
    expect(JSON.parse(site.canvas.dataset['siteUnknownLooks']!)).toEqual(['boundary.picket']);
    site.attachment.dispose();
    expect('siteMaterials' in site.canvas.dataset || 'siteUnknownLooks' in site.canvas.dataset).toBe(false);
  });

  it('draws a material in the pack\'s shading, as it draws a swatch', async () => {
    const toon = await dressedSite(TOON, MATERIALS);
    const plain = await dressedSite(PBR, MATERIALS);
    const chunk = (material: pc.Material): string | undefined => (material as pc.StandardMaterial).getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('lightDiffuseLambertPS') as string | undefined;
    // Positive control: a swatch surface of the same pack is banded in toon and not in pbr.
    expect(chunk(toon.shape('ground').material)).not.toEqual(chunk(plain.shape('ground').material));
    toon.attachment.dispose();
    plain.attachment.dispose();
  });

  it('gives a leaf that names no material its family default as before, and counts its words', async () => {
    const yard = parseSiteDrawing({
      profile: 'exulanica.site-drawing/v1', world_id: 'world-1', receipt_sha256: 'a'.repeat(64),
      kind: { kind: 'fixture_yard', version: 1, label: 'Yard' },
      extent: { widthMm: 12_000, depthMm: 12_000, enclosure: 'open' },
      arrival: { positionMm: [5000, 3000, 0], facingMm: [0, 1] },
      slots: [
        slot('ground', 'ground.playground', 'plane', [6000, 6000, 0], 0, [12_000, 12_000, 0], 'surface'),
        slot('lawn', 'ground.grass', 'plane', [3000, 3000, 6], 0, [2000, 2000, 0], 'surface'),
        slot('plain', 'ground.default', 'plane', [9000, 3000, 6], 0, [2000, 2000, 0], 'surface'),
        slot('wall', 'wall.market_wall', 'box', [3750, 7100, 0], 0, [1500, 200, 2400], 'surface'),
      ],
      walk: { floorMm: [0, 0, 12_000, 12_000], blockersMm: [], keepOutMm: [] },
      seats: [],
    });
    const site = await dressedSite(PBR, MATERIALS, yard);
    expect(site.shape('ground').material.name).toBe('style-pack:surface:ground.default');
    expect(site.shape('wall').material.name).toBe('style-pack:surface:wall.default');
    // Grass is what the pack's ground default is already, and a default leaf names nothing to throw away.
    expect(site.shape('lawn').material.name).toBe('style-pack:surface:ground.default');
    expect(site.shape('plain').material.name).toBe('style-pack:surface:ground.default');
    expect(site.summaries[0]).toMatchObject({ surfaces: 4, materials: 0, unknownLooks: ['ground.playground', 'wall.market_wall'] });
    site.attachment.dispose();
  });
});

describe('a site dressed in a pack that carries the surface patterns', () => {
  const yard = parseSiteDrawing({
    profile: 'exulanica.site-drawing/v1', world_id: 'world-1', receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_yard', version: 1, label: 'Yard' },
    extent: { widthMm: 12_000, depthMm: 12_000, enclosure: 'open' },
    arrival: { positionMm: [5000, 3000, 0], facingMm: [0, 1] },
    slots: [
      slot('ground', 'ground.sand', 'plane', [6000, 6000, 0], 0, [12_000, 12_000, 0], 'surface'),
      slot('lawn', 'ground.grass', 'plane', [3000, 3000, 6], 0, [2000, 2000, 0], 'surface'),
      slot('plain', 'ground.default', 'plane', [9000, 3000, 6], 0, [2000, 2000, 0], 'surface'),
      slot('play', 'ground.playground', 'plane', [9000, 9000, 6], 0, [2000, 2000, 0], 'surface'),
      slot('brick', 'wall.brick', 'box', [3750, 7100, 0], 0, [1500, 200, 2400], 'surface'),
      slot('stone', 'wall.stone', 'box', [6250, 7100, 0], 0, [1500, 200, 2400], 'surface'),
    ],
    walk: { floorMm: [0, 0, 12_000, 12_000], blockersMm: [], keepOutMm: [] },
    seats: [],
  });

  it('draws each material\'s pattern in its colour, whichever swatch that colour is, and says how many', async () => {
    const site = await dressedSite(PBR, MATERIALS, yard, PATTERNS);
    // Sand and brick in the catalog's colours: a grain, and courses of bricks.
    expect(colourChunk(site.shape('ground').material)).toContain('exuPatternNoise(uv / 1.600000)');
    expect(colourChunk(site.shape('brick').material)).toContain('uv.y / 0.076000');
    // Grass is the pack's own lawn, and takes grass's grain all the same, apart from the plain default beside it.
    expect(site.shape('lawn').material.name).toBe('style-pack:surface:ground.default:grass');
    expect(colourChunk(site.shape('lawn').material)).toContain('exuPatternNoise(uv / 0.900000)');
    expect(site.shape('plain').material.name).toBe('style-pack:surface:ground.default');
    expect(colourChunk(site.shape('plain').material)).toBeUndefined();
    // A leaf that names no material has no pattern to take.
    expect(colourChunk(site.shape('play').material)).toBeUndefined();
    // The pack's own stone colours its upward faces apart, and keeps that instead of stone's courses.
    expect(site.shape('stone').material.name).toBe('style-pack:surface:wall.stone');
    expect(colourChunk(site.shape('stone').material)).not.toContain('exuPattern');
    expect(site.summaries[0]).toMatchObject({ surfaces: 4, materials: 2, patterned: 3 });
    expect(site.canvas.dataset['sitePatterned']).toBe('3');
    // The ground beyond wears the patterned sand itself.
    expect(site.beyond()).toBe(site.shape('ground').material);
    site.attachment.dispose();
    expect('sitePatterned' in site.canvas.dataset).toBe(false);
  });

  it('darkens toward the pack\'s ink where the pack draws ink', async () => {
    const toon = await dressedSite(TOON, MATERIALS, yard, PATTERNS);
    expect(colourChunk(toon.shape('brick').material)).toContain('vec3(0.050000, 0.040000, 0.030000)');
    const plain = await dressedSite(PBR, MATERIALS, yard, PATTERNS);
    expect(colourChunk(plain.shape('brick').material)).toContain('dAlbedo * 0.500000');
    toon.attachment.dispose();
    plain.attachment.dispose();
  });

  it('draws every surface flat without the patterns, and without the materials a leaf is not read at all', async () => {
    const flat = await dressedSite(PBR, MATERIALS, yard);
    expect(colourChunk(flat.shape('ground').material)).toBeUndefined();
    expect(flat.summaries[0]).toMatchObject({ patterned: 0 });
    flat.attachment.dispose();
    const unread = await dressedSite(PBR, undefined, yard, PATTERNS);
    expect(colourChunk(unread.shape('ground').material)).toBeUndefined();
    expect(unread.summaries[0]).toMatchObject({ patterned: 0, materials: 0 });
    unread.attachment.dispose();
  });
});

describe('a site dressed in a pack', () => {
  it('draws a surface slot in the swatch its leaf, else its family default, names', async () => {
    const site = await dressedSite(PBR);
    expect(site.rgb(site.shape('ground').material)).toEqual([...SOIL]);
    expect(site.shape('ground').material.name).toBe('style-pack:surface:ground.default');
    expect(site.shape('shed:roof').material.name).toBe('style-pack:surface:roof.default');
    site.attachment.dispose();
  });

  it('dresses a leaf the pack gives a texture set as its family default, a site holding no texture images', async () => {
    const site = await dressedSite(PBR);
    expect(site.shape('shed:wall:0').material.name).toBe('style-pack:surface:wall.default');
    site.attachment.dispose();
  });

  it('stands a piece in a hole only a pack fills, and in a primitive slot with the primitive hidden', async () => {
    const site = await dressedSite(PBR);
    const pieces = site.root.findByName('style-pack:pieces') as pc.Entity;
    // The door fills its hole once and the 6 m fence takes three 2 m panels: four quads in oak.
    expect(pieces.render!.meshInstances.map((instance) => instance.material.name)).toEqual(['style-pack:swatch:oak']);
    expect(pieces.render!.meshInstances[0]!.mesh.primitive[0]!.count).toBe(4 * 6);
    expect((site.root.findByName('fence') as pc.Entity).enabled).toBe(false);
    expect(site.root.findByName('barn')).toBeNull();
    expect(site.summaries).toEqual([{ surfaces: 3, materials: 0, unknownLooks: [], patterned: 0, pieces: 2, placed: 4, undressed: 2, inkSegments: 0, sceneryPieces: 0 }]);
    site.attachment.dispose();
  });

  it('keeps the engine\'s primitive where the pack dresses nothing, in the pack\'s shading', async () => {
    const plain = await dressedSite(PBR);
    expect(plain.shape('bench').material.name).toMatch(/^generated-site-colour:/);
    plain.attachment.dispose();
    const toon = await dressedSite(TOON);
    const bench = toon.shape('bench').material as pc.StandardMaterial;
    expect(bench.name).toMatch(/^style-pack:shaded:generated-site-colour:/);
    expect(toon.rgb(bench)).toEqual([0.58, 0.44, 0.3].map((channel) => Math.round(channel * 255)));
    expect(bench.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('lightDiffuseLambertPS')).toBe(true);
    expect(toon.shape('farmer').material.name).toMatch(/^style-pack:shaded:/);
    toon.attachment.dispose();
  });

  it('outlines everything the site draws when the shading draws ink', async () => {
    const site = await dressedSite(TOON);
    expect(site.summaries[0]!.inkSegments).toBeGreaterThan(0);
    expect(site.root.find((node) => node.name === 'generated-tile:ink').length).toBeGreaterThan(0);
    site.attachment.dispose();
  });

  it('puts back every material and primitive before the slots go', async () => {
    const pack = sitePack();
    const pieces = await fetchPackPieces(pack, Object.keys(pack.modules), TABLE, async (file: StylePackFile) => PIECES[file.path]!);
    const { app, camera, environmentRoot } = nullApp();
    let seenBeforeTheSlotsWent: { ground: string; fence: boolean; pieces: boolean; ink: number } | null = null;
    const dresser = packSiteDresser({ pack, families, pieces, shading: TOON });
    const mount = siteMount(drawing, {
      servedBytes: 1,
      dress: (host, drawn, dressing) => {
        const undress = dresser(host, drawn, dressing);
        return () => {
          undress();
          const ground = (drawn.root.findByName('ground:shape') as pc.Entity).render!.meshInstances[0]!.material.name;
          seenBeforeTheSlotsWent = {
            ground,
            fence: (drawn.root.findByName('fence') as pc.Entity).enabled,
            pieces: drawn.root.findByName('style-pack:pieces') !== null,
            ink: drawn.root.find((node) => node.name === 'generated-tile:ink').length,
          };
        };
      },
    });
    mount.attach({ app, camera, environmentRoot }).dispose();
    expect(seenBeforeTheSlotsWent).toEqual({ ground: expect.stringMatching(/^generated-site-colour:/), fence: true, pieces: false, ink: 0 });
    expect(environmentRoot.children).toEqual([]);
  });
});

/** A place of one ground over its whole extent and one wall, in the served shape: 40 m by 30 m. */
const placeOn = (ground: string, enclosure: 'open' | 'indoor' = 'open'): SiteDrawing => parseSiteDrawing({
  profile: 'exulanica.site-drawing/v1',
  world_id: 'world:generated:beyond',
  receipt_sha256: 'a'.repeat(64),
  kind: { kind: 'fixture_place', version: 1, label: 'Place' },
  extent: { widthMm: 40_000, depthMm: 30_000, enclosure },
  arrival: { positionMm: [20_000, 3000, 0], facingMm: [0, 1] },
  slots: [
    slot('ground', ground, 'plane', [20_000, 15_000, 0], 0, [40_000, 30_000, 0], 'surface'),
    slot('hut:wall:0', 'wall.timber', 'box', [20_000, 20_000, 0], 0, [4000, 200, 2400], 'surface'),
  ],
  walk: { floorMm: [0, 0, 40_000, 30_000], blockersMm: [[18_000, 19_900, 22_000, 20_100]], keepOutMm: [] },
  seats: [],
});

/** Every point of an entity's meshes, in the renderer's metres (east, up, south). */
function pointsUnder(entity: pc.Entity): number[][] {
  const out: number[][] = [];
  for (const render of entity.findComponents('render') as pc.RenderComponent[]) {
    for (const instance of render.meshInstances) {
      const flat: number[] = [];
      instance.mesh.getPositions(flat);
      for (let i = 0; i < flat.length; i += 3) out.push([flat[i]!, flat[i + 1]!, flat[i + 2]!]);
    }
  }
  return out;
}

describe('the scenery beyond a made place', () => {
  const forest = placeOn('ground.forest_floor');
  const expected = sceneryBeyond(forest.worldId, forest.extent, SCENERY.byMaterial.get('forest_floor')!);

  it('stands trees beyond a forest floor as plain trunks and crowns where no pack has a tree, all of them past the rectangle', async () => {
    // The test pack has no plant of its own: the plain trees stay, in the pack's shading.
    const site = await dressedSite(TOON, MATERIALS, forest, undefined, { scenery: SCENERY });
    const scenery = site.environmentRoot.findByName('site-scenery') as pc.Entity;
    const trees = scenery.findByName('site-scenery:trees') as pc.Entity;
    expect(trees.enabled).toBe(true);
    // Two meshes for the whole wood: every trunk, every crown.
    const instances = (trees.findByName('site-scenery:trees:shape') as pc.Entity).render!.meshInstances;
    expect(instances).toHaveLength(2);
    expect(instances.map((instance) => instance.material.name)).toEqual(['style-pack:shaded:site-scenery-colour:trunk', 'style-pack:shaded:site-scenery-colour:crown']);
    expect(expected.length).toBeGreaterThan(300);
    expect(JSON.parse(site.canvas.dataset['siteScenery']!)).toEqual({ stands: 'tree', beyond: 'forest_floor', pieces: expected.length });
    expect(site.canvas.dataset['siteSceneryPieces']).toBeUndefined();
    expect(site.summaries[0]!.sceneryPieces).toBe(0);
    // Every point of every tree lies beyond the place's rectangle (east 0 to 40, south -30 to 0), on
    // or over the ground, and no higher than the tallest tree the catalog states.
    const points = pointsUnder(trees);
    expect(points.length).toBeGreaterThan(expected.length * 10);
    const tallest = SCENERY.byMaterial.get('forest_floor')!.heightMm[1] / 1000;
    for (const [x, y, z] of points) {
      expect(x! > 0 && x! < 40 && z! > -30 && z! < 0).toBe(false);
      expect(y!).toBeGreaterThanOrEqual(-1e-6);
      expect(y!).toBeLessThanOrEqual(tallest + 1e-6);
    }
    // The nearest tree's trunk stands where the placement puts it: east is x, north is minus z.
    const [first] = expected;
    const near = points.filter(([x, , z]) => Math.hypot(x! - first!.xMm / 1000, z! + first!.yMm / 1000) < first!.heightMm / 1000 * 0.05);
    expect(near.length).toBeGreaterThan(0);
    site.attachment.dispose();
    expect(site.canvas.dataset['siteScenery']).toBeUndefined();
    expect(site.environmentRoot.findByName('site-scenery')).toBeNull();
  });

  it('stands the pack\'s own tree at each tree where the pack has one, in a mesh beside the site\'s, and puts all back', async () => {
    const site = await dressedSite(PBR, MATERIALS, forest, undefined, { scenery: SCENERY, plant: true });
    const trees = site.environmentRoot.findByName('site-scenery:trees') as pc.Entity;
    // The plain trees are hidden: the pack's piece stands at each.
    expect(trees.enabled).toBe(false);
    expect(site.summaries[0]!.sceneryPieces).toBe(expected.length);
    expect(site.canvas.dataset['siteSceneryPieces']).toBe(String(expected.length));
    // The pack's trees are their own mesh under the environment, not under the site's root: nothing
    // that reads or outlines the site's slots meets them.
    const packs = site.environmentRoot.children.filter((child) => child.name === 'style-pack:pieces');
    expect(packs).toHaveLength(1);
    expect(site.root.findByName('site-scenery')).toBeNull();
    const points = pointsUnder(packs[0] as pc.Entity);
    // The test tree is one quad, baked as its two triangles: six points a tree, each past the rectangle.
    expect(points).toHaveLength(expected.length * 6);
    for (const [x, , z] of points) expect(x! > 0 && x! < 40 && z! > -30 && z! < 0).toBe(false);
    // Each is the piece scaled to its own tree: the nearest is as tall as the placement says, within
    // the uniform fit (3.2 by 5.8 into a box 0.55 as wide as it is tall loses under 1 percent).
    const heights = points.map(([, y]) => y!);
    expect(Math.max(...heights)).toBeLessThanOrEqual(SCENERY.byMaterial.get('forest_floor')!.heightMm[1] / 1000 + 1e-6);
    expect(Math.max(...heights)).toBeGreaterThan(SCENERY.byMaterial.get('forest_floor')!.heightMm[1] / 1000 * 0.9);
    site.attachment.dispose();
    expect(site.canvas.dataset['siteSceneryPieces']).toBeUndefined();
    expect(site.environmentRoot.children.filter((child) => child.name === 'style-pack:pieces')).toHaveLength(0);
  });

  it('lays stones beyond sand, a tree here and there beyond grass, and nothing beyond any other ground, indoors, or with no catalog', async () => {
    const sand = await dressedSite(PBR, MATERIALS, placeOn('ground.sand'), undefined, { scenery: SCENERY, plant: true });
    const stones = sand.environmentRoot.findByName('site-scenery:stones') as pc.Entity;
    expect((stones.findByName('site-scenery:stones:shape') as pc.Entity).render!.meshInstances).toHaveLength(1);
    expect(sand.environmentRoot.findByName('site-scenery:trees')).toBeNull();
    const count = sceneryBeyond('world:generated:beyond', { widthMm: 40_000, depthMm: 30_000 }, SCENERY.byMaterial.get('sand')!).length;
    expect(JSON.parse(sand.canvas.dataset['siteScenery']!)).toEqual({ stands: 'stone', beyond: 'sand', pieces: count });
    // A stone is no piece of any pack: none stands as one, though the pack has a tree.
    expect(sand.summaries[0]!.sceneryPieces).toBe(0);
    // Low: no point of any stone is higher than the catalog's tallest, and each lies past the rectangle.
    for (const [x, y, z] of pointsUnder(stones)) {
      expect(y!).toBeLessThanOrEqual(SCENERY.byMaterial.get('sand')!.heightMm[1] / 1000 + 1e-6);
      expect(x! > 0 && x! < 40 && z! > -30 && z! < 0).toBe(false);
    }
    sand.attachment.dispose();
    const grass = await dressedSite(PBR, MATERIALS, placeOn('ground.grass'), undefined, { scenery: SCENERY, plant: true });
    const fewer = JSON.parse(grass.canvas.dataset['siteScenery']!) as { stands: string; pieces: number };
    expect(fewer.stands).toBe('tree');
    expect(fewer.pieces).toBeLessThan(expected.length / 3);
    grass.attachment.dispose();
    // Tilled soil has no entry; an indoor place has no ground beyond; a leaf that names no material
    // names no scenery; and with no catalog handed, a forest floor is bare as before.
    for (const [place, withCatalog] of [
      [placeOn('ground.tilled_soil'), true], [placeOn('ground.forest_floor', 'indoor'), true],
      [placeOn('ground.playground'), true], [forest, false],
    ] as const) {
      const bare = await dressedSite(PBR, MATERIALS, place, undefined, withCatalog ? { scenery: SCENERY } : {});
      expect(bare.environmentRoot.findByName('site-scenery')).toBeNull();
      expect(bare.canvas.dataset['siteScenery']).toBeUndefined();
      bare.attachment.dispose();
    }
    // Asked directly, with its ground handed: an indoor place has none, an open one of the same ground has.
    const indoors = placeOn('ground.forest_floor', 'indoor');
    expect(baseGroundSlot(indoors)).not.toBeNull();
    expect(sceneryOf(indoors, baseGroundSlot(indoors), SCENERY, MATERIALS)).toBeNull();
    expect(sceneryOf(forest, baseGroundSlot(forest), SCENERY, MATERIALS)?.pieces).toEqual(expected);
    expect(sceneryOf(forest, null, SCENERY, MATERIALS)).toBeNull();
    // A look that draws no ground beyond the place (the tile look) has nothing for a tree to stand
    // on: a forest floor there has none, with the catalog handed and no dresser.
    const { app, camera, environmentRoot } = nullApp();
    const plain = siteMount(forest, { servedBytes: 1, materials: MATERIALS, scenery: SCENERY }).attach({ app, camera, environmentRoot });
    expect(app.root.findByName('generated-tile:edge-ground')).toBeNull();
    expect(environmentRoot.findByName('site-scenery')).toBeNull();
    expect((app.graphicsDevice.canvas as HTMLCanvasElement).dataset['siteScenery']).toBeUndefined();
    plain.dispose();
  });

  it('is no part of the world: the drawing, the walk, the site\'s own shapes and what the site counts are the same with it as without', async () => {
    const before = JSON.stringify(forest);
    const off = await dressedSite(PBR, MATERIALS, forest, undefined, {});
    const on = await dressedSite(PBR, MATERIALS, forest, undefined, { scenery: SCENERY, plant: true });
    // The drawing is the same object, untouched: scenery is never a slot of it.
    expect(on.mount.drawing).toBe(forest);
    expect(JSON.stringify(forest)).toBe(before);
    expect(forest.slots.map((one) => one.identity)).toEqual(['ground', 'hut:wall:0']);
    // The place a person and a society stand on is the drawing's own: the same floor, the same
    // blockers, nothing added for a tree.
    expect(JSON.stringify(on.mount.navigationWorld.polygonObstacles)).toBe(JSON.stringify(off.mount.navigationWorld.polygonObstacles));
    expect(JSON.stringify(siteNavigationWorld(forest).polygonObstacles)).toBe(JSON.stringify(off.mount.navigationWorld.polygonObstacles));
    expect(on.mount.navigationWorld.fieldRadius).toBe(off.mount.navigationWorld.fieldRadius);
    expect(on.mount.navigationWorld.surface.sample(-20, -15)).toEqual(off.mount.navigationWorld.surface.sample(-20, -15));
    // The site's own root holds the same shapes: nothing of the scenery is under it, so nothing
    // that reads the site's slots (its ink, its dressing, what hides a being) can meet a tree.
    const named = (root: pc.Entity) => root.find(() => true).map((entity) => entity.name).sort();
    expect(named(on.root)).toEqual(named(off.root));
    // And what the site says it drew is the same: scenery is counted on its own, never as the site.
    expect(on.attachment.metrics.triangles).toBe(off.attachment.metrics.triangles);
    expect(on.attachment.metrics.drawBatches).toBe(off.attachment.metrics.drawBatches);
    expect({ ...on.summaries[0]!, sceneryPieces: 0 }).toEqual(off.summaries[0]);
    on.attachment.dispose();
    off.attachment.dispose();
  });
});

describe('the inside of an indoor made place', () => {
  // The place of the scenery tests, indoors: a floor 40 m by 30 m and one timber wall 2.4 m high.
  const hall = placeOn('ground.floor', 'indoor');
  const { indoor } = INTERIOR;

  it('has a ceiling over its whole extent on the top of its walls, in what they are drawn in, and light from above', async () => {
    const open = await dressedSite(PBR, MATERIALS, placeOn('ground.floor'), undefined, { interior: INTERIOR });
    const sunOf = (site: Awaited<ReturnType<typeof dressedSite>>) => site.app.root.findByName('generated-tile-sun') as pc.Entity;
    const lookSun = { intensity: sunOf(open).light!.intensity, down: sunOf(open).up.clone().mulScalar(-1) };
    // An open place has no ceiling and the look's own sun.
    expect(open.environmentRoot.findByName('site-ceiling')).toBeNull();
    expect(open.canvas.dataset['siteCeiling']).toBeUndefined();
    open.attachment.dispose();

    const site = await dressedSite(PBR, MATERIALS, hall, undefined, { interior: INTERIOR });
    const ceiling = site.environmentRoot.findByName('site-ceiling') as pc.Entity;
    const shape = ceiling.findByName('site-ceiling:shape') as pc.Entity;
    // It lies on the wall's top, 2.4 m, a slab of the catalog's thickness over the whole extent:
    // its middle is half a thickness over the wall, at the middle of the floor (east 20, south -15).
    const at = ceiling.getPosition();
    expect([at.x, at.y, at.z].map((value) => Number(value.toFixed(6)))).toEqual([20, (2400 + indoor.ceilingThicknessMm / 2) / 1000, -15]);
    const size = shape.getLocalScale();
    expect([size.x, size.y, size.z].map((value) => Number(value.toFixed(6)))).toEqual([40, indoor.ceilingThicknessMm / 1000, 30]);
    expect(site.canvas.dataset['siteCeiling']).toBe('2400');
    // It wears what the wall wears once the place is dressed, and casts no shadow: the light is under it.
    const worn = shape.render!.meshInstances[0]!;
    expect(worn.material).toBe(site.shape('hut:wall:0').material);
    expect(worn.material.name).not.toBe('site-ceiling-colour');
    expect(shape.render!.castShadows).toBe(false);
    // The look's sun is the room's light: from the catalog's tilt off straight down (the cosine of
    // the angle between where it shines and straight down), at its share of the look's strength,
    // in its colour; no longer the low sun the look states.
    const sun = sunOf(site);
    const shines = sun.up.clone().mulScalar(-1);
    expect(-shines.y).toBeCloseTo(Math.cos(indoor.lightTiltDegrees * Math.PI / 180), 6);
    expect(-lookSun.down.y).toBeLessThan(-shines.y);
    expect(sun.light!.intensity).toBeCloseTo(lookSun.intensity * indoor.lightSharePermille / 1000, 9);
    const { r, g, b } = sun.light!.color;
    expect([r, g, b].map((channel) => Math.round(channel * 255))).toEqual([...indoor.lightSrgb8]);
    site.attachment.dispose();
    expect(site.canvas.dataset['siteCeiling']).toBeUndefined();
    expect(site.environmentRoot.findByName('site-ceiling')).toBeNull();
  });

  it('lies on the tallest box the place draws, whatever it is, the first of those as tall', () => {
    const market = parseSiteDrawing({
      profile: 'exulanica.site-drawing/v1', world_id: 'world:generated:market', receipt_sha256: 'a'.repeat(64),
      kind: { kind: 'fixture_market', version: 1, label: 'Market' },
      extent: { widthMm: 20_000, depthMm: 16_000, enclosure: 'indoor' },
      arrival: { positionMm: [10_000, 4000, 0], facingMm: [0, 1] },
      slots: [
        slot('floor', 'ground.floor', 'plane', [10_000, 8000, 0], 0, [20_000, 16_000, 0], 'surface'),
        slot('stall', 'fixture.stall', 'box', [5000, 8000, 0], 0, [3000, 2000, 2200]),
        slot('hall:wall:0', 'wall.plaster', 'box', [10_000, 15_900, 0], 0, [20_000, 200, 4000], 'surface'),
        // A lintel over the door reaches as high as the wall, from 2.1 m up: the wall, stated first, is what the ceiling lies on.
        slot('hall:lintel:0', 'wall.plaster', 'box', [10_000, 100, 2100], 0, [1200, 200, 1900], 'surface'),
        slot('counter', 'fixture.counter', 'box', [15_000, 8000, 0], 0, [2000, 800, 1100]),
        // The roof over a stall is a ridge, not a box, and is not what a ceiling lies on though it is the highest thing.
        slot('stall:roof', 'roof.canvas', 'gable', [5000, 8000, 2200], 0, [3200, 2200, 2500], 'surface'),
      ],
      walk: { floorMm: [0, 0, 20_000, 16_000], blockersMm: [], keepOutMm: [] },
      seats: [],
    });
    expect(ceilingRests(market)?.identity).toBe('hall:wall:0');
    // A place that draws no box has nothing for a ceiling to lie on.
    expect(ceilingRests(parseSiteDrawing({
      profile: 'exulanica.site-drawing/v1', world_id: 'world:generated:bare', receipt_sha256: 'a'.repeat(64),
      kind: { kind: 'fixture_bare', version: 1, label: 'Bare' },
      extent: { widthMm: 10_000, depthMm: 10_000, enclosure: 'indoor' },
      arrival: { positionMm: [5000, 2000, 0], facingMm: [0, 1] },
      slots: [slot('floor', 'ground.floor', 'plane', [5000, 5000, 0], 0, [10_000, 10_000, 0], 'surface')],
      walk: { floorMm: [0, 0, 10_000, 10_000], blockersMm: [], keepOutMm: [] },
      seats: [],
    }))).toBeNull();
  });

  it('is drawn as before with no catalog handed, and is no part of the world: the drawing, the walk and the site\'s own shapes are the same', async () => {
    const before = JSON.stringify(hall);
    const off = await dressedSite(PBR, MATERIALS, hall, undefined, {});
    const on = await dressedSite(PBR, MATERIALS, hall, undefined, { interior: INTERIOR });
    expect(off.environmentRoot.findByName('site-ceiling')).toBeNull();
    expect(on.mount.drawing).toBe(hall);
    expect(JSON.stringify(hall)).toBe(before);
    expect(JSON.stringify(on.mount.navigationWorld.polygonObstacles)).toBe(JSON.stringify(off.mount.navigationWorld.polygonObstacles));
    const named = (root: pc.Entity) => root.find(() => true).map((entity) => entity.name).sort();
    expect(named(on.root)).toEqual(named(off.root));
    expect(on.attachment.metrics.triangles).toBe(off.attachment.metrics.triangles);
    expect(on.attachment.metrics.drawBatches).toBe(off.attachment.metrics.drawBatches);
    expect(on.summaries[0]).toEqual(off.summaries[0]);
    on.attachment.dispose();
    off.attachment.dispose();
  });
});
