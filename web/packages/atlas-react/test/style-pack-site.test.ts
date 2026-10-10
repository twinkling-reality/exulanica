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
  readStylePackManifest, readSurfaceMaterials, resolveStylePack,
  type LookFamily, type ResolvedStylePack, type StylePackFile, type SurfaceMaterials,
} from '@exulanica/atlas-core';
import { parseSiteDrawing, siteMount, type SiteDrawing } from '../src/playcanvas/generated-site/index.js';
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
const PIECES: Readonly<Record<string, Uint8Array<ArrayBuffer>>> = { 'pieces/door.glb': DOOR, 'pieces/fence.glb': FENCE };

/**
 * The readers' complete case with this site's dressing: swatches for ground, walls and roofs, a
 * texture set for one wall leaf, and pieces for doors and boundaries; nothing for fixtures.
 */
function sitePack(): ResolvedStylePack {
  const manifest = structuredClone(CASES.cases.find((c: { name: string }) => c.name === 'a complete pack with no base').manifest);
  manifest['palette'].swatches.push(
    { key: 'soil', srgb8: [...SOIL], roughness_permille: 900, metalness_permille: 0, emission_permille: 0 },
    { key: 'oak', srgb8: [...OAK], roughness_permille: 700, metalness_permille: 0, emission_permille: 0 },
  );
  manifest['surfaces'] = {
    'ground.default': { swatch: 'soil', up: null },
    'roof.default': { swatch: 'roof_tile', up: null },
    'wall.brick_running_bond': { texture_set: 'cc0.brick-running-bond', up: null },
    'wall.default': { swatch: 'cream', up: null },
  };
  manifest['modules'] = {
    'boundary.default': { variants: [{ file: 'pieces/fence.glb', lod1: null, size_mm: [2000, 100, 1000], stretch_mm: [null, null, null] }] },
    'door.default': { variants: [{ file: 'pieces/door.glb', lod1: null, size_mm: [1000, 180, 2100], stretch_mm: [null, null, null] }] },
  };
  manifest['files'] = Object.entries(PIECES).map(([path, bytes]) => ({
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

async function dressedSite(shading: RenderShading, materials?: SurfaceMaterials, site: SiteDrawing = drawing) {
  const pack = sitePack();
  const pieces: FetchedPieces = await fetchPackPieces(pack, Object.keys(pack.modules), TABLE, async (file: StylePackFile) => PIECES[file.path]!);
  const summaries: SiteDressingSummary[] = [];
  const { app, camera, environmentRoot } = nullApp();
  // The pack's own light, with a ground beyond the world stated where the pack states none.
  const look = renderLookOfPreset(pack.light.presets[pack.light.default_preset]!, pack.shading, pack.edge ?? { ground: [136, 165, 96], drop_mm: 600, reach_mm: 3_000_000 });
  const mount = siteMount(site, { servedBytes: 1, look, dress: packSiteDresser({ pack, families, pieces, shading, ...(materials === undefined ? {} : { materials }), told: (summary) => summaries.push(summary) }) });
  const attachment = mount.attach({ app, camera, environmentRoot });
  const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
  const root = environmentRoot.findByName('generated-site:world-1') as pc.Entity;
  const shape = (identity: string): pc.MeshInstance => (root.findByName(`${identity}:shape`) as pc.Entity).render!.meshInstances[0]!;
  const rgb = (material: pc.Material): number[] => {
    const { r, g, b } = (material as pc.StandardMaterial).diffuse;
    return [r, g, b].map((channel) => Math.round(channel * 255));
  };
  const beyond = (): pc.Material => (app.root.findByName('generated-tile:edge-ground') as pc.Entity).render!.meshInstances[0]!.material;
  return { root, environmentRoot, attachment, summaries, shape, rgb, canvas, beyond };
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
    expect(site.summaries).toEqual([{ surfaces: 0, materials: 3, unknownLooks: ['boundary.picket'], pieces: 2, placed: 4, undressed: 2, inkSegments: 0 }]);
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
    expect(site.summaries).toEqual([{ surfaces: 3, materials: 0, unknownLooks: [], pieces: 2, placed: 4, undressed: 2, inkSegments: 0 }]);
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
