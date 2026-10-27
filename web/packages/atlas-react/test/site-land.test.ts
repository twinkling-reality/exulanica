// @vitest-environment happy-dom
/**
 * A site laid out on land in the browser: its drawing (`exulanica.site-drawing/v5`) and its land
 * are read and held to their digests, a person walks the land, the slots that follow the land are
 * laid on it, the land is drawn to the horizon in place of the flat plane beyond, and a site on
 * level ground is drawn exactly as before, with no land read, made or asked.
 *
 * The drawing (`fixtures/site-land.v5.json`) is synthetic, in the served shape: a 20 m by 16 m yard
 * on land that rises 40 per mille to the north and steps up 500 mm across the cell east of 7 m, with
 * a draped ground, zone, path and fence, a bench, a shed's roof and a pond at its level. Its two
 * chunks and its backdrop are rebuilt here from the same formula, and the drawing names their
 * digests; it is not a site a kind generated.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { canonicalJson, chunkHeightMm, readLandChunk, readLandSurfaces, readRoofForms, readStylePackManifest, readSurfaceMaterials, resolveStylePack, type LookFamily, type SceneryPiece, type StylePackManifest } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  LAND_GROUND_RGB,
  attachLandRound,
  baseGroundSlot,
  drawSiteLand,
  drawSiteScenery,
  parseStructuredSiteDrawing,
  readLandSection,
  readSiteLand,
  shapeRoofs,
  siteMount,
  siteNavigationWorld,
  siteStart,
  siteSurface,
  type SiteLand,
  type StructuredSiteDrawing,
} from '../src/playcanvas/generated-site/index.js';
import type { TileLook } from '../src/playcanvas/generated-tile/look.js';
import { withLandSurfaces } from '../src/playcanvas/generated-site/land-slope.js';
import { readSurfaceFinish, withFinish } from '../src/playcanvas/style-pack/ground-finish.js';
import { packSiteDresser } from '../src/playcanvas/style-pack/site-dresser.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const served = (): Record<string, unknown> => structuredClone(FIXTURE);
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const ROOF_FORMS = readRoofForms(readFileSync('../assets/catalogs/world-kinds/roof-form.v1.json', 'utf8'));
const COZY = JSON.parse(readFileSync('../assets/style-packs/packs/exulanica.cozy-town/manifest.json', 'utf8')) as {
  light: { default_preset: string; presets: Record<string, never> }; shading: never; edge: never;
};
const edgedLook = (): TileLook => renderLookOfPreset(COZY.light.presets[COZY.light.default_preset]!, COZY.shading, COZY.edge);
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const SURFACES = readLandSurfaces(readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8'));

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

/** A cascade's water over the fixture's land, as the server lists it: two pools and the fall between. */
const POOL = { id: 'falls pool 0', kind: 'pool', level_mm: 9000, rect_mm: [-20_000, 40_000, -16_000, 60_000] };
const FALL = { id: 'falls fall 0', kind: 'fall', level_mm: 9000, bottom_mm: 7000, rect_mm: [-20_000, 38_000, -16_000, 38_000], side: 'south' };
const LOWER = { id: 'falls pool 1', kind: 'pool', level_mm: 7000, rect_mm: [-20_000, 20_000, -16_000, 36_000] };

function landOf(drawing: StructuredSiteDrawing): SiteLand {
  return readSiteLand(drawing, chunks(), backdropDocument(), sha256, 1234);
}

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

/** A mesh instance's points in the scene's frame, metres. */
function pointsOf(instance: pc.MeshInstance): pc.Vec3[] {
  const positions: number[] = [];
  instance.mesh.getPositions(positions);
  const world = instance.node.getWorldTransform();
  const out: pc.Vec3[] = [];
  for (let k = 0; k < positions.length; k += 3) out.push(world.transformPoint(new pc.Vec3(positions[k]!, positions[k + 1]!, positions[k + 2]!)));
  return out;
}

describe('reading a site on land', () => {
  it('reads the land section and which slots follow the land', () => {
    const drawing = parseStructuredSiteDrawing(served());
    expect(drawing.profile).toBe('exulanica.site-drawing/v5');
    expect(drawing.land?.chunks.map((one) => one.chunk)).toEqual([[-1, 0], [0, 0]]);
    expect(drawing.land?.water).toEqual([
      { id: 'sea', kind: 'sea', levelMm: 0, side: 'south' },
      { id: 'pond 0', kind: 'pond', levelMm: 6500, rectMm: [15_500, 1000, 18_500, 4000] },
    ]);
    expect(drawing.slots.filter((slot) => slot.drape === true).map((slot) => slot.identity))
      .toEqual(['yard:ground', 'zone:west', 'path:main', 'fence:wall:0']);
    expect('drape' in drawing.slots.find((slot) => slot.identity === 'bench')!).toBe(false);
    expect(baseGroundSlot(drawing)?.identity).toBe('yard:ground');
  });

  it.each([
    ['a drape on level ground', (d: Record<string, unknown>) => { d['profile'] = 'exulanica.site-drawing/v1'; delete d['land']; }, 'drapes only on land'],
    ['a drape that is not true', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[])[0]!['drape'] = false; }, 'drapes only on land'],
    ['chunks of another size', (d: Record<string, unknown>) => { (d['land'] as Record<string, unknown>)['chunk_mm'] = 64_000; }, 'are not 128000 mm'],
    ['a chunk named twice', (d: Record<string, unknown>) => { const land = d['land'] as { chunks: unknown[] }; land.chunks.push(land.chunks[0]); }, 'states a chunk twice'],
    ['a digest that is not one', (d: Record<string, unknown>) => { (d['land'] as Record<string, unknown>)['backdrop_sha256'] = 'f00d'; }, 'not a SHA-256 digest'],
    ['water of another kind', (d: Record<string, unknown>) => { ((d['land'] as { water: Record<string, unknown>[] }).water[0]!)['kind'] = 'river'; }, 'not sea, lake, pond, pool or fall'],
    ['a fall that does not fall', (d: Record<string, unknown>) => { (d['land'] as { water: unknown[] }).water.push({ ...FALL, bottom_mm: 9000 }); }, 'does not fall'],
    ['a fall with depth', (d: Record<string, unknown>) => { (d['land'] as { water: unknown[] }).water.push({ ...FALL, rect_mm: [-20_000, 37_000, -16_000, 38_000] }); }, 'not a line across its channel'],
    ['a fall toward a corner', (d: Record<string, unknown>) => { (d['land'] as { water: unknown[] }).water.push({ ...FALL, side: 'south_east' }); }, 'not north, east, south or west'],
    ['no land at all', (d: Record<string, unknown>) => { delete d['land']; }, "land is not an object"],
  ])('refuses %s by name', (_name, change, words) => {
    const document = served();
    change(document);
    expect(() => parseStructuredSiteDrawing(document)).toThrow(words);
  });

  it('holds every chunk and the backdrop to the digest its drawing names', () => {
    const drawing = parseStructuredSiteDrawing(served());
    const land = landOf(drawing);
    expect(land.chunks).toHaveLength(2);
    expect(land.servedBytes).toBe(1234);
    const changed = chunks();
    const heights = (changed.get('0,0') as { height_mm: number[] }).height_mm;
    heights[7] = heights[7]! + 1;
    expect(() => readSiteLand(drawing, changed, backdropDocument(), sha256)).toThrow('is the document its digest names');
    const missing = chunks();
    missing.delete('-1,0');
    expect(() => readSiteLand(drawing, missing, backdropDocument(), sha256)).toThrow('(-1, 0) its land section names was not served');
    const far = backdropDocument();
    (far['height_mm'] as number[])[0] = 0;
    expect(() => readSiteLand(drawing, chunks(), far, sha256)).toThrow('is the document its digest names');
    expect(() => readSiteLand(parseStructuredSiteDrawing({ ...served(), profile: 'exulanica.site-drawing/v1', land: undefined, slots: [] }), chunks(), backdropDocument(), sha256)).toThrow('states no land');
  });

  it('says how high the land is anywhere, across a chunk edge and in the scene frame', () => {
    const land = landOf(parseStructuredSiteDrawing(served()));
    const zero = readLandChunk(chunkDocument(0, 0), sha256);
    for (const [x, y] of [[4000, 8000], [7500, 3200], [12_345, 15_900], [500, 900]] as const) {
      expect(land.groundMm(x, y)).toBe(chunkHeightMm(zero, x, y));
    }
    // On the edge two chunks share, and in the western chunk.
    expect(land.groundMm(0, 5000)).toBe(6200);
    expect(land.groundMm(-3000, 5000)).toBe(6200);
    // Beyond the near land, the nearest point of its edge.
    expect(land.groundMm(500_000, 5000)).toBe(land.groundMm(128_000, 5000));
    // Metres east and south: a site point (x, y) is the scene's (x / 1000, -y / 1000).
    expect(land.groundM(4, -8)).toBe(land.groundMm(4000, 8000) / 1000);
    expect(land.dryAt(4000, 8000)).toBe(true);
    expect(land.dryAt(17_000, 2500)).toBe(false);
  });
});

describe('walking a site on land', () => {
  const drawing = parseStructuredSiteDrawing(served());
  const land = landOf(drawing);
  const world = siteNavigationWorld(drawing, undefined, land);

  it('stands a person on the land over the site floor, tilted with it, and on nothing beyond it', () => {
    const sample = world.surface.sample(4, -8)!;
    expect(sample.height).toBeCloseTo(6.32, 6);
    // The land rises to the north, the scene's minus z: its normal leans south.
    expect(sample.normal.z).toBeGreaterThan(0.03);
    expect(sample.normal.y).toBeGreaterThan(0.99);
    expect(world.surface.sample(-0.5, -8)).toBeNull();
    expect(world.surface.sample(4, 0.5)).toBeNull();
  });

  it('opens a person at the arrival on the land, eye high', () => {
    expect(siteStart(drawing, world)).toMatchObject({ x: 10, y: 6.5 + world.eyeHeight, z: -0 });
  });

  it('is not mounted without the land its drawing names', () => {
    expect(() => siteMount(drawing, { servedBytes: 1 })).toThrow('with the land its drawing names');
    const other = parseStructuredSiteDrawing(served());
    expect(() => siteMount(drawing, { servedBytes: 1, land: landOf(other) })).toThrow('with the land its drawing names');
    expect(siteMount(drawing, { servedBytes: 1, land }).land).toBe(land);
  });
});

describe('drawing a site on land', () => {
  const drawing = parseStructuredSiteDrawing(served());

  it('lays every draped slot on the land at its layer, keeps the rest level, and puts back every shape', () => {
    const land = landOf(drawing);
    const { app, camera, environmentRoot } = nullApp();
    const attachment = siteMount(drawing, { servedBytes: 1, land, materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const instance = (identity: string): pc.MeshInstance => (environmentRoot.findByName(`${identity}:shape`) as pc.Entity).render!.meshInstances[0]!;
    // The zone 6 mm over the land and the path 12 mm, at every point, across the step in the land.
    for (const [identity, layer] of [['zone:west', 0.006], ['path:main', 0.012]] as const) {
      const points = pointsOf(instance(identity));
      expect(points.length).toBeGreaterThan(4);
      for (const point of points) expect(point.y).toBeCloseTo(land.groundM(point.x, point.z) + layer, 5);
    }
    // The path climbs with the land to the north, and the zone rises up the step at its east edge.
    const path = pointsOf(instance('path:main')).map((point) => point.y);
    expect(Math.max(...path) - Math.min(...path)).toBeCloseTo(0.64, 5);
    const zone = pointsOf(instance('zone:west'));
    const at = (x: number) => zone.find((point) => Math.abs(point.x - x) < 1e-6 && Math.abs(point.z + 4) < 1e-6)!.y;
    expect(at(8) - at(7)).toBeCloseTo(0.5, 5);
    // The fence's foot follows the land under it, its top 1.2 m over it.
    for (const point of pointsOf(instance('fence:wall:0'))) {
      const over = point.y - land.groundM(point.x, point.z);
      expect(Math.min(Math.abs(over), Math.abs(over - 1.2))).toBeLessThan(0.006);
    }
    // The bench stands level where its slot says.
    expect((environmentRoot.findByName('bench') as pc.Entity).getLocalPosition().y).toBeCloseTo(6.48, 6);
    attachment.dispose();
    expect(environmentRoot.findByName('site-land')).toBeNull();
  });

  it('wears its sea in a material it is handed, keeps plain water where it is handed none, and frees only its own', () => {
    const { app } = nullApp();
    const drawn = drawSiteLand(app.graphicsDevice, landOf(drawing), new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    expect(drawn.water.map((one) => [one.body.id, one.body.kind])).toEqual([['sea', 'sea']]);
    const plain = drawn.water[0]!.instance.material;
    const given = new pc.StandardMaterial();
    let destroyed = 0;
    const own = given.destroy.bind(given);
    given.destroy = () => { destroyed += 1; own(); };
    drawn.wearWater((body) => (body.kind === 'sea' ? given : null));
    expect(drawn.water[0]!.instance.material).toBe(given);
    drawn.wearWater(() => null);
    expect(drawn.water[0]!.instance.material).toBe(plain);
    drawn.wearWater(() => given);
    drawn.destroy();
    // The water's material is its maker's to free; the land frees its own plain water.
    expect(destroyed).toBe(0);
  });

  it("draws a cascade's pools level and its falls upright, facing where they fall, and hands both to the water's finish", () => {
    const document = served();
    (document['land'] as { water: unknown[] }).water.push(POOL, FALL, LOWER);
    const cascade = parseStructuredSiteDrawing(document);
    const land = landOf(cascade);
    expect(land.dryAt(-18_000, 50_000)).toBe(false);
    expect(land.dryAt(-25_000, 50_000)).toBe(true);
    const { app } = nullApp();
    const drawn = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    expect(drawn.water.map((one) => one.body.kind)).toEqual(['sea', 'pool', 'fall', 'pool']);
    const [, pool, fall] = drawn.water;
    for (const point of pointsOf(pool!.instance)) {
      expect(point.y).toBeCloseTo(9);
      expect(point.x).toBeGreaterThanOrEqual(-20.001);
      expect(point.x).toBeLessThanOrEqual(-15.999);
      expect(-point.z).toBeGreaterThanOrEqual(39.999);
      expect(-point.z).toBeLessThanOrEqual(60.001);
    }
    const sheet = pointsOf(fall!.instance);
    expect(Math.min(...sheet.map((point) => point.y))).toBeCloseTo(7);
    expect(Math.max(...sheet.map((point) => point.y))).toBeCloseTo(9);
    for (const point of sheet) expect(point.z).toBeCloseTo(-38);
    // It faces south, the way it falls, so it is seen from below.
    const facing = fall!.instance.node.getWorldTransform().transformVector(pc.Vec3.UP, new pc.Vec3());
    expect([facing.x, facing.y, facing.z].map((v) => Math.round(v))).toEqual([0, 0, 1]);
    const given = new pc.StandardMaterial();
    const asked: string[] = [];
    drawn.wearWater((body) => { asked.push(body.kind); return body.kind === 'fall' ? given : null; });
    expect(asked).toEqual(['sea', 'pool', 'fall', 'pool']);
    expect(fall!.instance.material).toBe(given);
    expect(pool!.instance.material).not.toBe(given);
    drawn.destroy();
  });

  it('draws the land in place of the base ground and the flat plane beyond, out to its horizon, and takes it all away', () => {
    const land = landOf(drawing);
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    const farBefore = camera.camera!.farClip;
    const attachment = siteMount(drawing, { servedBytes: 1, land, look: edgedLook(), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const drawn = environmentRoot.findByName('site-land') as pc.Entity;
    expect(drawn).not.toBeNull();
    expect(drawn.children.map((child) => child.name)).toEqual([
      'site-land:chunk:-1:0', 'site-land:chunk:0:0', 'site-land:backdrop', 'site-land:water:sea',
    ]);
    // The base ground's slot is kept for its dressing and not drawn; the land wears what it wears.
    const base = environmentRoot.findByName('yard:ground') as pc.Entity;
    expect(base.enabled).toBe(false);
    const chunk = (drawn.findByName('site-land:chunk:0:0') as pc.Entity).render!.meshInstances[0]!;
    expect(chunk.material).toBe((base.findByName('yard:ground:shape') as pc.Entity).render!.meshInstances[0]!.material);
    // The land casts no shadow; nothing of it does.
    for (const child of drawn.children) expect((child as pc.Entity).render!.castShadows).toBe(false);
    // The look's flat plane is not drawn under the land, and the far plane reaches the horizon.
    expect((app.root.findByName('generated-tile:edge-ground') as pc.Entity).enabled).toBe(false);
    expect(camera.camera!.farClip).toBeGreaterThan(400 * Math.SQRT2);
    expect(JSON.parse(canvas.dataset['siteLand']!)).toMatchObject({ chunks: 2, draped: 4 });
    // The near land is the land read: a vertex at a lattice point stands at the lattice's height.
    const points = pointsOf(chunk);
    expect(points.some((point) => Math.abs(point.x - 4) < 1e-6 && Math.abs(point.z + 8) < 1e-6 && Math.abs(point.y - 6.32) < 1e-6)).toBe(true);
    attachment.dispose();
    expect(environmentRoot.findByName('site-land')).toBeNull();
    expect('siteLand' in canvas.dataset).toBe(false);
    expect(camera.camera!.farClip).toBe(farBefore);
  });

  it('stands a tent from its own building\'s base and scenery on the land under it', () => {
    const camp = parseStructuredSiteDrawing({ ...served(), slots: (served()['slots'] as { identity: string }[]).map((one) => (one.identity === 'shed:roof' ? { ...one, lookRole: 'roof.tent' } : one)) });
    const shaped = shapeRoofs(camp, MATERIALS, ROOF_FORMS).meshes.get('shed:roof')!;
    // The tent's sides reach the ground: 2.4 m under its eaves, its building's wall, and not down to the datum.
    expect(Math.min(...shaped.positions.filter((_, k) => k % 3 === 1))).toBeCloseTo(-2.4, 6);
    const land = landOf(drawing);
    const { app } = nullApp();
    const pieces: SceneryPiece[] = [{ identity: 'tree-1', stands: 'tree', xMm: 30_000, yMm: 40_000, beyondMm: 10_000, quarterTurns: 0, widthMm: 3000, heightMm: 6000 }];
    const trees = drawSiteScenery(app.graphicsDevice, { scenery: { key: 'grass', stands: 'tree' } as never, pieces }, null, land.groundMm);
    const lowest = Math.min(...pointsOf((trees.root.findByName('site-scenery:trees:shape') as pc.Entity).render!.meshInstances[0]!).map((point) => point.y));
    expect(lowest).toBeCloseTo(land.groundMm(30_000, 40_000) / 1000, 5);
    expect(trees.groundMm).toBe(land.groundMm);
    trees.destroy();
  });
});

describe('the land round a town on its land', () => {
  const drawing = parseStructuredSiteDrawing(served());

  it("is read from its own section as a site's is, drawn round the town's tiles and never under them, and taken away", () => {
    const section = drawing.land!;
    const land = readLandSection(section, chunks(), backdropDocument(), sha256, 99);
    expect(land.chunks.map((chunk) => [chunk.chunkX, chunk.chunkY])).toEqual([[-1, 0], [0, 0]]);
    expect(land.servedBytes).toBe(99);
    const missing = chunks();
    missing.delete('0,0');
    expect(() => readLandSection(section, missing, backdropDocument(), sha256)).toThrow('(0, 0) its land section names was not served');
    const { app, camera, environmentRoot } = nullApp();
    const farBefore = camera.camera!.farClip;
    // The town's one tile covers chunk (0, 0): the land is drawn round it, with its backdrop and sea.
    const round = attachLandRound({ app, camera, environmentRoot }, land, (x, y) => x === 0 && y === 0, SURFACES);
    const drawn = environmentRoot.findByName('site-land') as pc.Entity;
    expect(drawn.children.map((child) => child.name)).toEqual(['site-land:chunk:-1:0', 'site-land:backdrop', 'site-land:water:sea']);
    expect(round.drawn.ground).toHaveLength(1);
    expect(camera.camera!.farClip).toBeGreaterThan(400 * Math.SQRT2);
    round.dispose();
    expect(environmentRoot.findByName('site-land')).toBeNull();
    expect(camera.camera!.farClip).toBe(farBefore);
  });

  it('wears the open ground its town is drawn in, and the land\'s own plain ground where it is given none', () => {
    const land = readLandSection(drawing.land!, chunks(), backdropDocument(), sha256);
    const { app, camera, environmentRoot } = nullApp();
    const worn = (round: ReturnType<typeof attachLandRound>): number[] => {
      const { diffuse } = round.drawn.ground[0]!.material as pc.StandardMaterial;
      return [diffuse.r, diffuse.g, diffuse.b].map((value) => Math.round(value * 1000) / 1000);
    };
    // A desert setting's sand, as a look's open ground is handed over: linear RGB.
    const sand = [0.686, 0.468, 0.216] as const;
    const given = attachLandRound({ app, camera, environmentRoot }, land, (x, y) => x === 0 && y === 0, SURFACES, sand);
    expect(worn(given)).toEqual([...sand]);
    given.dispose();
    const own = attachLandRound({ app, camera, environmentRoot }, land, (x, y) => x === 0 && y === 0, SURFACES);
    expect(worn(own)).toEqual([...LAND_GROUND_RGB]);
    own.dispose();
  });
});

describe('a site on level ground', () => {
  const level = (): Record<string, unknown> => {
    const document = served();
    document['profile'] = 'exulanica.site-drawing/v1';
    delete document['land'];
    for (const slot of document['slots'] as Record<string, unknown>[]) {
      delete slot['drape'];
      const position = slot['positionMm'] as number[];
      position[2] = slot['identity'] === 'shed:roof' ? 2400 : 0;
    }
    (document['arrival'] as { positionMm: number[] }).positionMm[2] = 0;
    return document;
  };

  it('reads as it always did: no land, no slot that drapes', () => {
    const drawing = parseStructuredSiteDrawing(level());
    expect('land' in drawing).toBe(false);
    expect(drawing.slots.some((slot) => 'drape' in slot)).toBe(false);
  });

  it('constructs no land, walks its level floor and draws no land', () => {
    const drawing = parseStructuredSiteDrawing(level());
    const mount = siteMount(drawing, { servedBytes: 1, materials: MATERIALS });
    expect('land' in mount).toBe(false);
    expect(mount.navigationWorld.surface.sample(4, -8)).toEqual(siteSurface(drawing).sample(4, -8));
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    const attachment = mount.attach({ app, camera, environmentRoot });
    expect(environmentRoot.findByName('site-land')).toBeNull();
    expect('siteLand' in canvas.dataset).toBe(false);
    expect((environmentRoot.findByName('yard:ground') as pc.Entity).enabled).toBe(true);
    attachment.dispose();
  });

  it('ignores land it is handed', () => {
    const drawing = parseStructuredSiteDrawing(level());
    const land = landOf(parseStructuredSiteDrawing(served()));
    expect('land' in siteMount(drawing, { servedBytes: 1, land })).toBe(false);
  });
});

// The canonical JSON the reader holds a document to is atlas-core's.
it('rebuilds the fixture\'s land documents to the digests the fixture names', () => {
  const land = (FIXTURE['land'] as { chunks: { chunk: number[]; sha256: string }[]; backdrop_sha256: string });
  for (const { chunk: [x, y], sha256: named } of land.chunks) expect(sha256(new TextEncoder().encode(canonicalJson(chunkDocument(x!, y!))))).toBe(named);
  expect(sha256(new TextEncoder().encode(canonicalJson(backdropDocument())))).toBe(land.backdrop_sha256);
});

describe("a site on land in the land's own surfaces", () => {
  const drawing = parseStructuredSiteDrawing(served());

  it('wraps the colour function, the finish included, and lays the near bands over it once', () => {
    const plain = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n    dAlbedo = material_diffuse.rgb;\n}\n';
    const wrapped = withLandSurfaces(plain, SURFACES, true)!;
    expect(wrapped.split('void getAlbedo() {')).toHaveLength(2);
    expect(wrapped).toContain('void exuLandBase() {');
    for (const key of ['sand', 'planted', 'rock']) expect(wrapped).toContain(`// ${key}`);
    // Far bands are the backdrop's, and sand needs a sea.
    expect(wrapped).not.toContain('// wooded');
    expect(withLandSurfaces(plain, SURFACES, false)).not.toContain('// sand');
    // The slope is the land's own surface's, never a normal map's.
    expect(wrapped).toContain('dVertexNormalW');
    expect(wrapped).not.toContain('dNormalW');
    // Over the ground finish: both colour functions kept, the finish's called inside the land's.
    const finished = withLandSurfaces(withFinish(plain, 'ground'), SURFACES, true)!;
    expect(finished).toContain('void exuFinishBase() {');
    expect(finished).toContain('void exuLandBase() {');
    expect(finished.split('void getAlbedo() {')).toHaveLength(2);
    // The chain: the land's colour calls the finish's (renamed to the land's base), which calls the pack's.
    expect(finished.indexOf('void exuLandBase() {')).toBeLessThan(finished.indexOf('exuFinishBase();'));
    expect(finished.slice(finished.indexOf('void getAlbedo() {'))).toContain('exuLandBase();');
    // Once only, and never into a chunk with no one colour function.
    expect(withLandSurfaces(wrapped, SURFACES, true)).toBe(wrapped);
    expect(withLandSurfaces('void main() {}', SURFACES, true)).toBeNull();
  });

  it('wears a copy of the base ground with the bands over it on the one mesh of each chunk, and the backdrop in its woods', () => {
    const land = landOf(drawing);
    const { app, camera, environmentRoot } = nullApp();
    const attachment = siteMount(drawing, { servedBytes: 1, land, landSurfaces: SURFACES, materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const chunk = (environmentRoot.findByName('site-land:chunk:0:0') as pc.Entity).render!.meshInstances;
    expect(chunk).toHaveLength(1);
    const base = (environmentRoot.findByName('yard:ground:shape') as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial;
    const worn = chunk[0]!.material as pc.StandardMaterial;
    expect(worn).not.toBe(base);
    expect(worn.name).toBe(`site-land:surfaces:${base.name}`);
    expect(worn.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS')).toContain('// exulanica: land surfaces');
    // The base ground keeps its own colour function: the bands are the land's alone.
    expect(base.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS') ?? '').not.toContain('exuLandBase');
    // The same copy on every chunk: one material, made once.
    expect((environmentRoot.findByName('site-land:chunk:-1:0') as pc.Entity).render!.meshInstances[0]!.material).toBe(worn);
    // The backdrop's slopes north of the near land stand 40 to 150 m up: wooded, darker than its ground.
    const block = (environmentRoot.findByName('site-land:backdrop') as pc.Entity).render!.meshInstances;
    const greens: number[] = [];
    for (const one of block) {
      const colours: number[] = [];
      one.mesh.getColors(colours);
      for (let k = 1; k < colours.length; k += 4) greens.push(colours[k]!);
    }
    const wooded = SURFACES.bands.find((one) => one.key === 'wooded')!.linear[1];
    expect(greens.some((g) => Math.abs(g - wooded) < 0.005)).toBe(true);
    expect(Math.max(...greens)).toBeGreaterThan(wooded + 0.05);
    attachment.dispose();
    expect(environmentRoot.findByName('site-land')).toBeNull();
  });
});

describe('the sea of a site on land, dressed', () => {
  const drawing = parseStructuredSiteDrawing(served());
  const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { context: { texture_sets: string[] }; cases: { name: string; manifest: StylePackManifest }[] };
  const LOOK_FAMILIES = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
    entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
  };
  const families = new Map<string, LookFamily>(LOOK_FAMILIES.entries.map((entry) => [entry.key, {
    fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
  }]));
  const manifest = (name: string): StylePackManifest => CASES.cases.find((one) => one.name === name)!.manifest;
  const FINISH = readSurfaceFinish(JSON.parse(readFileSync('../assets/catalogs/world-kinds/surface-finish.v2.json', 'utf8')));
  const PBR = { model: 'pbr', toon: null, ink: null } as const;

  /** The material the land's sea is drawn in, mounted with a pack's dresser from `name`'s manifest, or with none. */
  interface Seen { readonly name: string; readonly chunks: Map<string, string>; readonly blendType: number; readonly depthWrite: boolean; readonly diffuse: pc.Color; readonly pondChunks: ReadonlySet<string> }
  const seaOf = (name: string | null, look?: TileLook): Seen => {
    const { app, camera, environmentRoot } = nullApp();
    const pack = name === null ? null : resolveStylePack([readStylePackManifest(manifest(name), { families, textureSets: new Set(CASES.context.texture_sets) })]);
    const dress = pack === null ? undefined
      : packSiteDresser({ pack, families, pieces: { pieces: new Map() }, shading: PBR, materials: MATERIALS, finish: FINISH, ...(look === undefined ? {} : { look }) });
    const attachment = siteMount(drawing, { servedBytes: 1, land: landOf(drawing), materials: MATERIALS, ...(dress === undefined ? {} : { dress }), ...(look === undefined ? {} : { look }) })
      .attach({ app, camera, environmentRoot });
    const material = (environmentRoot.findByName('site-land:water:sea') as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial;
    const glsl = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    // The site's own pond, a water slot beside the land's sea.
    const pond = (environmentRoot.findByName('pond:shape') as pc.Entity).render!.meshInstances[0]!.material;
    const pondChunks = new Set((pond as pc.StandardMaterial).getShaderChunks(pc.SHADERLANGUAGE_GLSL).keys());
    const seen: Seen = { name: material.name, chunks: new Map([...glsl.keys()].map((key) => [key, String(glsl.get(key))])), blendType: material.blendType, depthWrite: material.depthWrite, diffuse: material.diffuse.clone(), pondChunks };
    attachment.dispose();
    return seen;
  };
  const chunk = (material: Seen, name: string): string => material.chunks.get(name) ?? '';

  it('is drawn in the pack\'s water with the finish over it, its depth the land\'s own, faded in at the shore', () => {
    const sea = seaOf('a complete pack with no base');
    expect(sea.name).toBe('style-pack:land-water:sea:sea');
    expect(chunk(sea, 'diffusePS')).toContain('smoothstep(0.0, exuFinishSea.x, exuSeaDepth())');
    expect(chunk(sea, 'opacityPS')).toContain('exuSeaDepth()');
    expect(sea.blendType).toBe(pc.BLEND_NORMAL);
    expect(sea.depthWrite).toBe(false);
    // The pack states no water, so the sea takes the surface catalog's own sea colour, as a pond would.
    const swatch = MATERIALS.materials.find((one) => one.key === 'sea')!.swatch.srgb8;
    expect([sea.diffuse.r, sea.diffuse.g, sea.diffuse.b].map((c) => Math.round(c * 255))).toEqual([...swatch]);
  });

  it('takes the look\'s own depth water where the look states one', () => {
    const watered = manifest('a preset with haze and a pack with a water finish');
    const look = renderLookOfPreset(watered.light!.presets[watered.light!.default_preset]!, watered.shading!, watered.edge, 1, watered.water);
    const sea = seaOf('a complete pack with no base', look);
    expect(chunk(sea, 'opacityPS')).toContain('getLinearScreenDepth');
    expect(chunk(sea, 'opacityPS')).not.toContain('exuSeaDepth');
    expect(chunk(sea, 'diffusePS')).not.toContain('exuFinishSea');
    // A sea seen from afar carries no ripple in its light; the site's pond, under the same look, does.
    expect(sea.chunks.has('normalMapPS')).toBe(false);
    expect(sea.pondChunks.has('normalMapPS')).toBe(true);
  });

  it('keeps plain water where no pack dresses the site', () => {
    expect(seaOf(null).name).toBe('site-land:water');
  });
});
