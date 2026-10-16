// @vitest-environment happy-dom
/**
 * Where a site's near land meets its backdrop, at the near land's edge: the backdrop is coloured
 * over the ground the near land wears. Drawn alone, it is coloured over the ground it is drawn
 * over, as before; handed another ground it is coloured over that, the land's bands as before, and
 * handed none it is as drawn. Dressed in a pack, the backdrop is coloured over the pack's own
 * ground where the near land wears it, and a site in no pack keeps the catalog's.
 *
 * The drawing and its land are `fixtures/site-land.v5.json` and the formula `site-land.test.ts`
 * rebuilds its chunks and backdrop from; its base ground's leaf is set to grass here, which every
 * pack draws in its own ground default.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { readLandSurfaces, readStylePackManifest, readSurfaceMaterials, resolveStylePack, type LookFamily, type Srgb8 } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { drawSiteLand, parseStructuredSiteDrawing, readSiteLand, siteMount, type SiteLand, type StructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';
import { packSiteDresser } from '../src/playcanvas/style-pack/site-dresser.js';

// Relative to web/, where the suite runs.
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const SURFACES = readLandSurfaces(readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8'));
const LOOK_FAMILIES = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(LOOK_FAMILIES.entries.map((entry) => [entry.key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const textureSets = new Set<string>((JSON.parse(readFileSync('../assets/textures/manifest.json', 'utf8')) as { sets: { set_id: string }[] }).sets.map((set) => set.set_id));
const PACKS = '../assets/style-packs/packs';
const PBR = { model: 'pbr', toon: null, ink: null } as const;
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

/** The fixture's land at a lattice point, millimetres above the datum. */
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

/** The fixture's drawing, its base ground's leaf set to `leaf`. */
function drawingOn(leaf: string): StructuredSiteDrawing {
  const document = structuredClone(FIXTURE);
  (document['slots'] as { identity: string; lookRole: string }[]).find((slot) => slot.identity === 'yard:ground')!.lookRole = `ground.${leaf}`;
  return parseStructuredSiteDrawing(document);
}
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

/** Every vertex colour of the backdrop drawn under `root`, block by block, RGBA. */
function backdropColours(root: pc.Entity): number[] {
  const out: number[] = [];
  for (const instance of (root.findByName('site-land:backdrop') as pc.Entity).render!.meshInstances) {
    const colours: number[] = [];
    instance.mesh.getColors(colours);
    out.push(...colours);
  }
  return out;
}

/** The largest difference between two colour lists of one length. */
function apart(a: readonly number[], b: readonly number[]): number {
  expect(a).toHaveLength(b.length);
  return a.reduce((most, value, k) => Math.max(most, Math.abs(value - b[k]!)), 0);
}

const linear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const linearOf = (rgb: readonly number[]): readonly [number, number, number] => [linear(rgb[0]!), linear(rgb[1]!), linear(rgb[2]!)];
/** One colour on every vertex, RGBA. */
const everywhere = (rgb: readonly number[], vertices: number): number[] => Array.from({ length: vertices }, () => [...rgb, 1]).flat();

describe('the backdrop of a site on land', () => {
  const drawing = drawingOn('grass');

  it('is coloured over the ground it is drawn over, and over a ground it is handed', () => {
    const { app } = nullApp();
    const drawn = drawSiteLand(app.graphicsDevice, landOf(drawing), new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    const drawnAs = backdropColours(drawn.root);
    const vertices = drawnAs.length / 4;
    expect(vertices).toBeGreaterThan(0);
    expect(apart(drawnAs, everywhere(linearOf([0.4, 0.5, 0.3]), vertices))).toBeLessThan(1e-6);
    const near = drawn.ground.map((instance) => instance.material);
    drawn.colourBackdrop([0.1, 0.2, 0.05]);
    expect(apart(backdropColours(drawn.root), everywhere([0.1, 0.2, 0.05], vertices))).toBeLessThan(1e-6);
    // The near land wears what it wore.
    expect(drawn.ground.map((instance) => instance.material)).toEqual(near);
    drawn.colourBackdrop(null);
    expect(backdropColours(drawn.root)).toEqual(drawnAs);
    drawn.destroy();
    drawn.colourBackdrop([0.1, 0.2, 0.05]);
  });

  it("keeps the land's bands over a ground it is handed, as over one it is drawn over", () => {
    const { app } = nullApp();
    const land = landOf(drawing);
    const drawn = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3], SURFACES);
    const other = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.6, 0.7, 0.2], SURFACES);
    const drawnAs = backdropColours(drawn.root);
    expect(apart(drawnAs, backdropColours(other.root))).toBeGreaterThan(0.05);
    drawn.colourBackdrop(linearOf([0.6, 0.7, 0.2]));
    const handed = backdropColours(drawn.root);
    expect(apart(handed, backdropColours(other.root))).toBeLessThan(1e-6);
    // Its slopes north of the near land are wooded still.
    const wooded = SURFACES.bands.find((one) => one.key === 'wooded')!.linear[1];
    expect(handed.filter((_, k) => k % 4 === 1).some((green) => Math.abs(green - wooded) < 0.005)).toBe(true);
    drawn.colourBackdrop(null);
    expect(backdropColours(drawn.root)).toEqual(drawnAs);
    drawn.destroy();
    other.destroy();
  });
});

describe('the backdrop of a site on land, dressed', () => {
  /** The backdrop's colours and the base ground's colour, mounted on `leaf` in the pack in `folder`, or in none. */
  const mounted = (leaf: string, folder: string | null, landSurfaces: typeof SURFACES | null = null): { readonly backdrop: number[]; readonly base: pc.Color } => {
    const drawing = drawingOn(leaf);
    const { app, camera, environmentRoot } = nullApp();
    const pack = folder === null ? null
      : resolveStylePack([readStylePackManifest(JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')), { families, textureSets })]);
    const dress = pack === null ? undefined : packSiteDresser({ pack, families, pieces: { pieces: new Map() }, shading: PBR, materials: MATERIALS });
    const attachment = siteMount(drawing, {
      servedBytes: 1, land: landOf(drawing), materials: MATERIALS, ...(landSurfaces === null ? {} : { landSurfaces }), ...(dress === undefined ? {} : { dress }),
    }).attach({ app, camera, environmentRoot });
    const backdrop = backdropColours(environmentRoot.findByName('site-land') as pc.Entity);
    const base = ((environmentRoot.findByName('yard:ground:shape') as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial).diffuse.clone();
    attachment.dispose();
    return { backdrop, base };
  };
  const swatchOf = (folder: string, key: string): Srgb8 =>
    (JSON.parse(readFileSync(`${PACKS}/${folder}/manifest.json`, 'utf8')) as { palette: { swatches: { key: string; srgb8: Srgb8 }[] } })
      .palette.swatches.find((one) => one.key === key)!.srgb8;
  const grass = MATERIALS.materials.find((one) => one.key === 'grass')!.swatch.srgb8;

  it("is coloured over the pack's own ground where the near land wears it", () => {
    const cozy = swatchOf('exulanica.cozy-town', 'grass');
    // The pack and the catalog state two greens: the seam this closes.
    expect([...cozy]).not.toEqual([...grass]);
    const { backdrop, base } = mounted('grass', 'exulanica.cozy-town');
    // The near land wears the pack's own ground, and the backdrop is coloured over the same.
    expect([base.r, base.g, base.b].map((c) => Math.round(c * 255))).toEqual([...cozy]);
    expect(apart(backdrop, everywhere(linearOf(cozy.map((byte) => byte / 255)), backdrop.length / 4))).toBeLessThan(1e-6);
  });

  it("keeps the land's bands over the pack's ground", () => {
    const cozy = swatchOf('exulanica.cozy-town', 'grass');
    const { backdrop } = mounted('grass', 'exulanica.cozy-town', SURFACES);
    const { app } = nullApp();
    const drawing = drawingOn('grass');
    const expected = drawSiteLand(app.graphicsDevice, landOf(drawing), new pc.StandardMaterial(), cozy.map((byte) => byte / 255) as unknown as [number, number, number], SURFACES);
    expect(apart(backdrop, backdropColours(expected.root))).toBeLessThan(1e-6);
    expected.destroy();
  });

  it("keeps the catalog's ground in no pack, as it is drawn", () => {
    const { backdrop, base } = mounted('grass', null);
    expect([base.r, base.g, base.b].map((c) => Math.round(c * 255))).toEqual([...grass]);
    expect(apart(backdrop, everywhere(linearOf(grass.map((byte) => byte / 255)), backdrop.length / 4))).toBeLessThan(1e-6);
  });
});
