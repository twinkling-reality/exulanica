// @vitest-environment happy-dom
/**
 * The retaining walls of a site on land, where its levels meet: the drawing's land section may list
 * them, each a run along x or along y on the low side's lattice line rising toward a main side
 * across it, and anything else is refused by name. The land draws them as one mesh, one draw, with
 * each face's foot on the land and its top at the upper level and its coping, casting no shadow and
 * walked by no one. A site whose land lists no walls draws exactly what it drew.
 *
 * The drawing and its land are `fixtures/site-land.v5.json` and the formula `site-land.test.ts`
 * rebuilds its chunks and backdrop from: land rising 40 per mille to the north and 500 mm across
 * the cell east of 7 m. Its walls are set here: one along y on the line x = 7 m rising east over that
 * step, and one along x on the line y = 6 m rising north.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { readLandSurfaces, readSurfaceMaterials } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { VOLUME_ROCK_RGB, drawSiteLand, parseStructuredSiteDrawing, readSiteLand, siteMount, siteNavigationWorld, type SiteLand, type StructuredSiteDrawing } from '../src/playcanvas/generated-site/index.js';

// Relative to web/, where the suite runs.
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const SURFACE_CATALOG = readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8');
const SURFACES = readLandSurfaces(SURFACE_CATALOG);
const ROCK_SRGB8 = (JSON.parse(SURFACE_CATALOG) as { entries: { key: string; srgb8: number[] }[] }).entries.find((one) => one.key === 'rock')!.srgb8;
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
const landOf = (drawing: StructuredSiteDrawing): SiteLand => readSiteLand(drawing, chunks(), backdropDocument(), sha256, 1234);

/** A run along y on the line x = 7 m, 3 m long, rising east over the fixture's 500 mm step. */
const EAST_WALL = { from_mm: [7000, 2000], to_mm: [7000, 5000], high: 'east' };
/** A run along x on the line y = 6 m, 2 m long, rising north. */
const NORTH_WALL = { from_mm: [10_000, 6000], to_mm: [12_000, 6000], high: 'north' };

/** The fixture's drawing as served, its land listing `walls` where they are given. */
function served(walls?: readonly unknown[]): Record<string, unknown> {
  const document = structuredClone(FIXTURE);
  if (walls !== undefined) (document['land'] as Record<string, unknown>)['walls'] = structuredClone(walls);
  return document;
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

/** The walls drawn under a land's root: their one mesh instance. */
function wallsOf(root: pc.Entity): pc.MeshInstance {
  const entity = root.findByName('site-land:walls') as pc.Entity | null;
  expect(entity).not.toBeNull();
  expect(entity!.render!.meshInstances).toHaveLength(1);
  return entity!.render!.meshInstances[0]!;
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

/** The heights, millimetres, of the points over a site point (millimetres east and north). */
function heightsAt(points: readonly pc.Vec3[], eastMm: number, northMm: number): number[] {
  const at = points.filter((point) => Math.abs(point.x * 1000 - eastMm) < 1e-3 && Math.abs(-point.z * 1000 - northMm) < 1e-3);
  return [...new Set(at.map((point) => Math.round(point.y * 1000)))].sort((a, b) => a - b);
}

describe('reading the walls of a site on land', () => {
  it('reads the walls its land lists, and none where it lists none', () => {
    const walled = parseStructuredSiteDrawing(served([EAST_WALL, NORTH_WALL]));
    expect(walled.land?.walls).toEqual([
      { fromMm: [7000, 2000], toMm: [7000, 5000], high: 'east' },
      { fromMm: [10_000, 6000], toMm: [12_000, 6000], high: 'north' },
    ]);
    const plain = parseStructuredSiteDrawing(served());
    expect('walls' in plain.land!).toBe(false);
    expect(parseStructuredSiteDrawing(served([])).land?.walls).toEqual([]);
  });

  it.each([
    ['a wall along a diagonal', { ...EAST_WALL, to_mm: [8000, 5000] }, 'land wall 0 runs along neither x nor y'],
    ['a wall off the lattice', { ...EAST_WALL, from_mm: [7000, 2500] }, 'land wall 0 is off the 1000 mm lattice'],
    ['a wall of no length', { ...EAST_WALL, to_mm: [7000, 2000] }, 'land wall 0 has no length'],
    ['a wall rising toward a side along its run', { ...EAST_WALL, high: 'north' }, 'land wall 0 rises toward north, along its run and not across it'],
    ['a wall rising toward no main side', { ...EAST_WALL, high: 'north_east' }, 'land wall 0 rises toward north_east, not north, east, south or west'],
    ['a wall run from its far end', { ...EAST_WALL, from_mm: [7000, 5000], to_mm: [7000, 2000] }, 'land wall 0 does not run from its least end'],
    ['a wall with a field more', { ...EAST_WALL, height_mm: 1200 }, 'land wall 0 has unexpected or missing fields'],
  ])('refuses %s by name', (_name, wall, words) => {
    expect(() => parseStructuredSiteDrawing(served([wall]))).toThrow(words);
  });

  it('refuses walls that are not a list by name', () => {
    const document = served();
    (document['land'] as Record<string, unknown>)['walls'] = { 0: EAST_WALL };
    expect(() => parseStructuredSiteDrawing(document)).toThrow('land walls are not a list');
  });
});

describe('drawing the walls of a site on land', () => {
  const plain = parseStructuredSiteDrawing(served());
  const walled = parseStructuredSiteDrawing(served([EAST_WALL, NORTH_WALL]));

  it('adds one draw: one mesh under the land, casting no shadow', () => {
    const { app } = nullApp();
    const before = drawSiteLand(app.graphicsDevice, landOf(plain), new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    const after = drawSiteLand(app.graphicsDevice, landOf(walled), new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    expect(after.draws).toBe(before.draws + 1);
    expect(after.root.children.map((child) => child.name)).toEqual([...before.root.children.map((child) => child.name), 'site-land:walls']);
    expect((after.root.findByName('site-land:walls') as pc.Entity).render!.castShadows).toBe(false);
    // Five metres of runs, each a face, a top and the coping's back; two ends to each of two runs.
    expect(after.triangles - before.triangles).toBe(5 * 3 * 2 + 2 * 2 * 2);
    expect(wallsOf(after.root).mesh.primitive[0]!.count / 3).toBe(5 * 3 * 2 + 2 * 2 * 2);
    before.destroy();
    after.destroy();
  });

  it("stands on the land at both ends of each run, up to the upper level and its coping", () => {
    const { app } = nullApp();
    const land = landOf(walled);
    const drawn = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    const points = pointsOf(wallsOf(drawn.root));
    for (const north of [2000, 5000]) {
      // On the low line: the land there, and the land one cell east and the coping over it.
      expect(heightsAt(points, 7000, north)).toEqual([lattice(7000, north), lattice(8000, north) + 100]);
      expect(heightsAt(points, 7000, north)).toEqual([land.groundMm(7000, north), land.groundMm(8000, north) + 100]);
      // On the high line: the upper land, and the coping over it.
      expect(heightsAt(points, 8000, north)).toEqual([land.groundMm(8000, north), land.groundMm(8000, north) + 100]);
    }
    expect(heightsAt(points, 7000, 2000)).toEqual([6080, 6680]);
    for (const east of [10_000, 12_000]) {
      expect(heightsAt(points, east, 6000)).toEqual([land.groundMm(east, 6000), land.groundMm(east, 7000) + 100]);
      expect(heightsAt(points, east, 7000)).toEqual([land.groundMm(east, 7000), land.groundMm(east, 7000) + 100]);
    }
    // Nothing of a wall lies under the land, and a wall stands only on its runs' cell strips.
    for (const point of points) expect(point.y * 1000).toBeGreaterThanOrEqual(land.groundMm(point.x * 1000, -point.z * 1000) - 1e-3);
    expect(heightsAt(points, 6000, 3000)).toEqual([]);
    expect(heightsAt(points, 9000, 3000)).toEqual([]);
    drawn.destroy();
  });

  it('faces out of the wall on every side, as the renderer culls', () => {
    const { app } = nullApp();
    const drawn = drawSiteLand(app.graphicsDevice, landOf(parseStructuredSiteDrawing(served([EAST_WALL]))), new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    const instance = wallsOf(drawn.root);
    const positions: number[] = [], normals: number[] = [], indices: number[] = [];
    instance.mesh.getPositions(positions);
    instance.mesh.getNormals(normals);
    instance.mesh.getIndices(indices);
    const vertex = (k: number): pc.Vec3 => new pc.Vec3(positions[k * 3]!, positions[k * 3 + 1]!, positions[k * 3 + 2]!);
    const middle = new pc.Vec3();
    for (let k = 0; k < positions.length / 3; k += 1) middle.add(vertex(k));
    middle.mulScalar(3 / positions.length);
    const facing = new Set<string>();
    for (let t = 0; t < indices.length; t += 3) {
      const [a, b, c] = [vertex(indices[t]!), vertex(indices[t + 1]!), vertex(indices[t + 2]!)];
      const normal = new pc.Vec3().cross(new pc.Vec3().sub2(b, a), new pc.Vec3().sub2(c, a)).normalize();
      const centre = new pc.Vec3().add2(a, b).add(c).mulScalar(1 / 3);
      // Counterclockwise seen from outside: out of the wall, as each vertex's normal says.
      expect(normal.dot(new pc.Vec3().sub2(centre, middle))).toBeGreaterThan(0);
      const stated = new pc.Vec3(normals[indices[t]! * 3]!, normals[indices[t]! * 3 + 1]!, normals[indices[t]! * 3 + 2]!);
      expect(normal.dot(stated)).toBeGreaterThan(0.999);
      expect(normal.y).toBeGreaterThan(-1e-9);
      facing.add([normal.x, normal.z].map((c) => Math.round(c)).join(','));
    }
    // The low side's face west, the coping's back east, the ends south and north, and the top up.
    expect([...facing].sort()).toEqual(['-1,0', '0,-1', '0,0', '0,1', '1,0']);
    drawn.destroy();
  });

  it("is worn in the surfaces' rock, in the engine's rock without them, and in a material it is handed", () => {
    const { app } = nullApp();
    const land = landOf(walled);
    const surfaced = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3], SURFACES);
    const rock = wallsOf(surfaced.root).material as pc.StandardMaterial;
    expect([rock.diffuse.r, rock.diffuse.g, rock.diffuse.b].map((c) => Math.round(c * 255))).toEqual(ROCK_SRGB8);
    const bare = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    const engine = wallsOf(bare.root).material as pc.StandardMaterial;
    expect([engine.diffuse.r, engine.diffuse.g, engine.diffuse.b]).toEqual([...VOLUME_ROCK_RGB]);
    const handed = new pc.StandardMaterial();
    surfaced.wearWalls(handed);
    expect(wallsOf(surfaced.root).material).toBe(handed);
    surfaced.wearWalls(null);
    expect(wallsOf(surfaced.root).material).toBe(rock);
    surfaced.destroy();
    bare.destroy();
    handed.destroy();
  });

  it('is drawn on the land a site is mounted on, and walked by no one', () => {
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    const said = (drawing: StructuredSiteDrawing): { draws: number } => {
      const attachment = siteMount(drawing, { servedBytes: 1, land: landOf(drawing), materials: MATERIALS }).attach({ app, camera, environmentRoot });
      const drawn = JSON.parse(canvas.dataset['siteLand']!) as { draws: number };
      expect(environmentRoot.findByName('site-land:walls') !== null).toBe(drawing.land?.walls !== undefined);
      attachment.dispose();
      return drawn;
    };
    expect(said(walled).draws).toBe(said(plain).draws + 1);
    // The fixture's only wall no building owns is a fence: the walls stay in rock.
    const attachment = siteMount(walled, { servedBytes: 1, land: landOf(walled), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    expect((wallsOf(environmentRoot).material as pc.StandardMaterial).name).toBe('site-land:walls');
    attachment.dispose();
    // A person stands on the land in the wall's strip, not on the wall.
    const over = siteNavigationWorld(walled, undefined, landOf(walled)), under = siteNavigationWorld(plain, undefined, landOf(plain));
    for (const [x, z] of [[7, -3], [7.5, -3.5], [8, -4]] as const) {
      expect(over.surface.sample(x, z)?.height).toBe(under.surface.sample(x, z)?.height);
      expect(over.surface.sample(x, z)?.height).toBeLessThan((lattice(8000, -z * 1000) + 100) / 1000);
    }
  });
});

describe("the walls of a site with walls of its own", () => {
  /** A parapet along the zone's edge: a wall no building owns, the site's own. */
  const PARAPET = {
    identity: 'zone:west:parapet:0', part: 'parapet', label: 'zone:west:parapet:0', lookRole: 'wall.limewash',
    positionMm: [5000, 12000, 7000], yawQuarterTurns: 0, boxMm: [6000, 400, 1100], front: '+y', fit: 'contain', primitive: 'box', drape: true,
  };

  it('wear what the site wears on its own wall, as the mount holds it', () => {
    const { app, camera, environmentRoot } = nullApp();
    const document = served([EAST_WALL, NORTH_WALL]);
    (document['slots'] as unknown[]).push(structuredClone(PARAPET));
    const drawing = parseStructuredSiteDrawing(document);
    const attachment = siteMount(drawing, { servedBytes: 1, land: landOf(drawing), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const parapet = (app.root.findByName(`${PARAPET.identity}:shape`) as pc.Entity | null)?.render?.meshInstances[0]?.material;
    expect(parapet).toBeDefined();
    // Compared as one answer: a failing comparison of two materials would print the engine's graph.
    expect(wallsOf(environmentRoot).material === parapet, 'the walls wear the parapet').toBe(true);
    attachment.dispose();
  });
});

describe('a site on land with no walls', () => {
  it('draws exactly what it drew: the same entities, draws and triangles, whether it states no walls or an empty list', () => {
    const { app } = nullApp();
    const plain = parseStructuredSiteDrawing(served());
    const none = parseStructuredSiteDrawing(served([]));
    const drawn = drawSiteLand(app.graphicsDevice, landOf(plain), new pc.StandardMaterial(), [0.4, 0.5, 0.3], SURFACES);
    const empty = drawSiteLand(app.graphicsDevice, landOf(none), new pc.StandardMaterial(), [0.4, 0.5, 0.3], SURFACES);
    for (const one of [drawn, empty]) {
      expect(one.root.children.map((child) => child.name)).toEqual([
        'site-land:chunk:-1:0', 'site-land:chunk:0:0', 'site-land:backdrop', 'site-land:water:sea',
      ]);
      // A draw for each mesh instance under the land: the chunks, the backdrop's blocks and the sea.
      expect(one.draws).toBe(one.root.children.reduce((sum, child) => sum + (child as pc.Entity).render!.meshInstances.length, 0));
      // Wearing walls where none are drawn changes nothing.
      one.wearWalls(new pc.StandardMaterial());
    }
    expect(empty.draws).toBe(drawn.draws);
    expect(empty.triangles).toBe(drawn.triangles);
    drawn.destroy();
    empty.destroy();
  });
});
