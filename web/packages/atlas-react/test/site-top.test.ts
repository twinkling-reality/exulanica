// @vitest-environment happy-dom
/**
 * A site on a floating island's top in the browser: its drawing (`exulanica.site-drawing/v6`) and
 * the graded top it names are read and held to their digests, a person stands on the top at the
 * server's heights, only the cells with rock under them are drawn as land, the landscape stands at
 * the inverse of the site's frame so the island lies under the site whatever its turn, and the land
 * below the island is drawn with it in the same frame.
 *
 * The drawing, its top and its landscape (`fixtures/site-top.v6.json`) are the server's own output:
 * a hamlet on a sky island 60 m up. The fixture carries none of the volumes' chunks or the land
 * below, so the landscape here keeps its placements without their chunks, and its ground is the
 * synthetic yard's land of `site-land.test.ts`, named by its digests. Heights are pinned by the
 * server-made `tests/fixtures/landform/site-top-conformance.json`, made from the same top.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {
  canonicalJson, landscapeToSiteMm, readLandSurfaces, readLandscapeDrawing, readSurfaceMaterials, siteTopHeightMm,
  type LandscapeDrawing,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  SITE_DRAWING_TOP_PROFILE, baseGroundSlot, drawSiteLand, drawSiteVolumes, landscapePlacementM, parseSiteDrawing,
  parseStructuredSiteDrawing, readLandscapeGround, readSiteTopLand, readSiteVolumes, siteLandSurface, siteMount,
  siteNavigationWorld, type SiteVolumes,
} from '../src/playcanvas/generated-site/index.js';
import { withLandSurfaces } from '../src/playcanvas/generated-site/land-slope.js';
import type { TileLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-top.v6.json', 'utf8')) as {
  drawing: Record<string, unknown>; drawing_sha256: string; top: Record<string, unknown>; top_sha256: string;
  landscape: Record<string, unknown>; landscape_sha256: string;
};
const CONFORMANCE = JSON.parse(readFileSync('../tests/fixtures/landform/site-top-conformance.json', 'utf8')) as {
  sha256: string; points: [number, number, number][];
};
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const SURFACES = readLandSurfaces(readFileSync('../assets/catalogs/landform/landform-surface.v1.json', 'utf8'));
const COZY = JSON.parse(readFileSync('../assets/style-packs/packs/exulanica.cozy-town/manifest.json', 'utf8')) as {
  light: { default_preset: string; presets: Record<string, never> }; shading: never; edge: never;
};
/** A look that draws a flat plane beyond the place, which a site on a top must not. */
const edgedLook = (): TileLook => renderLookOfPreset(COZY.light.presets[COZY.light.default_preset]!, COZY.shading, COZY.edge);

const served = (): Record<string, unknown> => structuredClone(FIXTURE.drawing);
const topOf = (raw: Record<string, unknown>): Record<string, unknown> => raw['top'] as Record<string, unknown>;
const drawing = parseStructuredSiteDrawing(served());
const topLand = () => readSiteTopLand(drawing, structuredClone(FIXTURE.top), sha256, 777);
/** Every cell the drawing draws as land, as `row,column`. */
const held = (): Set<string> => new Set(drawing.top!.rockCells.flatMap(([row, first, last]) => Array.from({ length: last - first + 1 }, (_, k) => `${row},${first + k}`)));

/** The yard's land of `site-land.test.ts`, which here lies below the island. */
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
const digestOf = (value: unknown): string => sha256(new TextEncoder().encode(canonicalJson(value)));

/**
 * The fixture's landscape with its volumes' chunks left out, the land below it the yard's, and its
 * site frame turned by `yawMdeg`: the island turned with it, and the site's corner where the
 * drawing's offset in the island's frame puts it, so the island stands under the site whatever the turn.
 */
function landscapeOf(yawMdeg = 0, raw: (landscape: Record<string, unknown>) => void = () => {}): {
  readonly drawing: LandscapeDrawing; readonly chunks: Map<string, unknown>; readonly backdrop: unknown;
} {
  const landscape = structuredClone(FIXTURE.landscape);
  const volumes = landscape['volumes'] as { id: string; at_mm: number[]; yaw_mdeg: number; chunks: unknown[] }[];
  for (const volume of volumes) volume.chunks = [];
  const isle = volumes.find((volume) => volume.id === 'isle')!;
  isle.yaw_mdeg = yawMdeg;
  const [east, north] = topOf(FIXTURE.drawing)['offset_mm'] as [number, number];
  const turn = (yawMdeg / 1000) * (Math.PI / 180);
  const frame = landscape['site_frame'] as { at_mm: number[]; yaw_mdeg: number };
  frame.yaw_mdeg = yawMdeg;
  frame.at_mm = [
    isle.at_mm[0]! + Math.round(east * Math.cos(turn) - north * Math.sin(turn)),
    isle.at_mm[1]! + Math.round(east * Math.sin(turn) + north * Math.cos(turn)),
    isle.at_mm[2]!,
  ];
  const chunks = new Map([['-1,0', chunkDocument(-1, 0)], ['0,0', chunkDocument(0, 0)]]);
  const ground = landscape['ground'] as Record<string, unknown>;
  ground['chunks'] = [...chunks].map(([place, body]) => ({ chunk: place.split(',').map(Number), sha256: digestOf(body) }));
  ground['backdrop_sha256'] = digestOf(backdropDocument());
  ground['water'] = [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }];
  raw(landscape);
  return { drawing: readLandscapeDrawing(landscape, sha256), chunks, backdrop: backdropDocument() };
}
const volumesOf = (yawMdeg = 0): SiteVolumes => {
  const landscape = landscapeOf(yawMdeg);
  const ground = readLandscapeGround(landscape.drawing, landscape.chunks, landscape.backdrop, sha256, 99);
  return readSiteVolumes(landscape.drawing, new Map(), sha256, 4321, undefined, ground);
};

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

const close = (a: pc.Vec3, b: readonly [number, number, number], digits: number): void => {
  expect(a.x).toBeCloseTo(b[0], digits);
  expect(a.y).toBeCloseTo(b[1], digits);
  expect(a.z).toBeCloseTo(b[2], digits);
};

describe("reading a site on a volume's top", () => {
  it("reads the server's drawing: version 5's slots and drapes, and its top in place of land", () => {
    expect(sha256(new TextEncoder().encode(canonicalJson(FIXTURE.drawing)))).toBe(FIXTURE.drawing_sha256);
    expect(drawing.profile).toBe(SITE_DRAWING_TOP_PROFILE);
    expect(drawing.land).toBeUndefined();
    const top = drawing.top!;
    expect(top.topSha256).toBe(FIXTURE.top_sha256);
    expect(top.landscapeSha256).toBe(FIXTURE.landscape['landscape_sha256']);
    expect(top.placement).toBe('isle');
    expect(top.offsetMm).toEqual([-11_000, -11_000]);
    expect(top.water).toEqual([]);
    expect(top.rockCells).toHaveLength(41);
    expect(top.rockCells[0]).toEqual([2, 17, 24]);
    expect(drawing.slots.filter((slot) => slot.drape === true)).toHaveLength(9);
    expect(baseGroundSlot(drawing)?.lookRole).toBe('ground.grass');
  });

  it.each([
    ['land beside its top', (d: Record<string, unknown>) => { d['land'] = {}; }, 'states no land'],
    ['no top', (d: Record<string, unknown>) => { delete d['top']; }, "top is not an object"],
    ['a field its top does not state', (d: Record<string, unknown>) => { topOf(d)['extra'] = 1; }, 'unexpected or missing fields'],
    ['a top missing its cells', (d: Record<string, unknown>) => { delete topOf(d)['rock_cells']; }, 'unexpected or missing fields'],
    ['a top digest that is not one', (d: Record<string, unknown>) => { topOf(d)['top_sha256'] = 'top'; }, 'top digest is not a SHA-256 digest'],
    ['a placement that is no key', (d: Record<string, unknown>) => { topOf(d)['placement'] = 'Isle'; }, "not a placement's key"],
    ['a run of two figures', (d: Record<string, unknown>) => { topOf(d)['rock_cells'] = [[2, 17]]; }, 'top cells 0 is not three figures'],
    ['a run in parts of a cell', (d: Record<string, unknown>) => { topOf(d)['rock_cells'] = [[2, 17.5, 24]]; }, 'top cells 0 is not a whole number'],
    ['a run below the first row', (d: Record<string, unknown>) => { topOf(d)['rock_cells'] = [[-1, 17, 24]]; }, 'not a row and its first and last column'],
    ['a run west of the first column', (d: Record<string, unknown>) => { topOf(d)['rock_cells'] = [[2, -1, 24]]; }, 'not a row and its first and last column'],
    ['a run that ends before it starts', (d: Record<string, unknown>) => { topOf(d)['rock_cells'] = [[2, 24, 17]]; }, 'not a row and its first and last column'],
    ['water of no kind', (d: Record<string, unknown>) => { topOf(d)['water'] = [{ id: 'mere', kind: 'mere', level_mm: 0 }]; }, 'top water 0 is not sea, lake, pond, pool or fall'],
    ['a drape on level ground', (d: Record<string, unknown>) => { d['profile'] = 'exulanica.site-drawing/v1'; delete d['top']; }, 'drapes only on land'],
  ])('refuses %s', (_, change, said) => {
    const changed = served();
    change(changed);
    expect(() => parseSiteDrawing(changed)).toThrow(said);
  });

  it('reads the water on a top as a land section states it', () => {
    const watered = served();
    topOf(watered)['water'] = [{ id: 'pond', kind: 'pond', level_mm: 1900, rect_mm: [3000, 3000, 5000, 6000] }];
    expect(parseStructuredSiteDrawing(watered).top!.water).toEqual([{ id: 'pond', kind: 'pond', levelMm: 1900, rectMm: [3000, 3000, 5000, 6000] }]);
  });
});

describe("a volume's graded top as a site's land", () => {
  it("stands every point at the server's height, in the site's frame and in the scene's", () => {
    const land = topLand();
    expect(land.top.sha256).toBe(CONFORMANCE.sha256);
    expect(land.section).toBe(drawing.top);
    expect(land.chunks).toEqual([]);
    expect(land.backdrop).toBeNull();
    expect(land.servedBytes).toBe(777);
    for (const [east, north, height] of CONFORMANCE.points) {
      expect(land.groundMm(east, north)).toBe(height);
      expect(land.groundMm(east, north)).toBe(siteTopHeightMm(land.top, east, north));
      expect(land.groundM(east / 1000, -north / 1000)).toBeCloseTo(height / 1000, 9);
    }
    // A person arrives standing on the top.
    const [east, north, up] = drawing.arrival.positionMm;
    expect(land.groundMm(east, north)).toBe(up);
    expect(land.dryAt(east, north)).toBe(true);
  });

  it('refuses a top that is not the one named, a cell off its lattice, and a drawing on no top', () => {
    const tampered = structuredClone(FIXTURE.top);
    (tampered['height_mm'] as number[])[0] = 1;
    expect(() => readSiteTopLand(drawing, tampered, sha256)).toThrow('is the document its digest names');
    const wide = served();
    topOf(wide)['rock_cells'] = [[2, 17, 44]];
    expect(() => readSiteTopLand(parseStructuredSiteDrawing(wide), structuredClone(FIXTURE.top), sha256)).toThrow("off the top's lattice");
    const high = served();
    topOf(high)['rock_cells'] = [[44, 0, 0]];
    expect(() => readSiteTopLand(parseStructuredSiteDrawing(high), structuredClone(FIXTURE.top), sha256)).toThrow("off the top's lattice");
    const level = served();
    level['profile'] = 'exulanica.site-drawing/v1';
    delete level['top'];
    for (const slot of level['slots'] as Record<string, unknown>[]) delete slot['drape'];
    expect(() => readSiteTopLand(parseStructuredSiteDrawing(level), structuredClone(FIXTURE.top), sha256)).toThrow("stands on no volume's top");
  });

  it('draws two triangles for each cell with rock under it and half of each rim cell three of whose corners are on rock, with no backdrop', () => {
    const { app } = nullApp();
    const land = topLand();
    const drawn = drawSiteLand(app.graphicsDevice, land, new pc.StandardMaterial(), [0.4, 0.5, 0.3]);
    expect(drawn.root.children.map((child) => child.name)).toEqual(['site-land:top']);
    expect(drawn.ground).toHaveLength(1);
    const cells = held();
    expect(cells.size).toBe(1169);
    // The rim's fringe: cells outside the runs three of whose corners are corners of a held cell.
    const { columns, rows } = land.top;
    const rock = new Set<string>();
    for (const cell of cells) {
      const [row, column] = cell.split(',').map(Number) as [number, number];
      for (const [dj, di] of [[0, 0], [0, 1], [1, 0], [1, 1]] as const) rock.add(`${row + dj},${column + di}`);
    }
    let fringe = 0;
    for (let j = 0; j + 1 < rows; j += 1) for (let i = 0; i + 1 < columns; i += 1) {
      if (cells.has(`${j},${i}`)) continue;
      if ([[0, 0], [0, 1], [1, 0], [1, 1]].filter(([dj, di]) => rock.has(`${j + dj!},${i + di!}`)).length === 3) fringe += 1;
    }
    expect(fringe).toBeGreaterThan(10);
    expect(drawn.triangles).toBe(2 * cells.size + fringe);
    expect(drawn.draws).toBe(1);
    // Every triangle lies in a held cell or the fringe, at the top's height there, a few millimetres over it.
    const mesh = drawn.ground[0]!.mesh;
    const positions: number[] = [], indices: number[] = [];
    mesh.getPositions(positions);
    mesh.getIndices(indices);
    expect(indices.length).toBe(6 * cells.size + 3 * fringe);
    const [x0, y0] = land.top.originMm;
    const found = new Set<string>();
    for (let t = 0; t < indices.length; t += 3) {
      const corners = [0, 1, 2].map((k) => indices[t + k]!);
      const east = Math.min(...corners.map((v) => positions[3 * v]!)), north = Math.min(...corners.map((v) => -positions[3 * v + 2]!));
      found.add(`${Math.round((north * 1000 - y0) / 1000)},${Math.round((east * 1000 - x0) / 1000)}`);
      for (const v of corners) {
        const height = land.groundMm(Math.round(positions[3 * v]! * 1000), Math.round(-positions[3 * v + 2]! * 1000));
        expect(positions[3 * v + 1]! * 1000 - height).toBeCloseTo(3, 2);
      }
    }
    expect([...cells].every((cell) => found.has(cell))).toBe(true);
    expect(found.size).toBe(cells.size + fringe);
    // Faces up, as the near land's do.
    const normals: number[] = [];
    mesh.getNormals(normals);
    expect(normals.filter((_, k) => k % 3 === 1).every((up) => up > 0)).toBe(true);
    expect(drawn.reachM).toBeGreaterThan(Math.hypot(33, 33));
    drawn.destroy();
  });

  it('lays the land surfaces over it with heights above the sea, from the level the island stands at', () => {
    const plain = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n    dAlbedo = material_diffuse.rgb;\n}\n';
    expect(withLandSurfaces(plain, SURFACES, false)).toContain('\tfloat h = vPositionW.y * 1000.0;\n');
    expect(withLandSurfaces(plain, SURFACES, false, 60_000)).toContain('\tfloat h = vPositionW.y * 1000.0 + 60000.0;\n');
    const { app } = nullApp();
    const drawn = drawSiteLand(app.graphicsDevice, topLand(), new pc.StandardMaterial(), [0.4, 0.5, 0.3], SURFACES, { datumMm: 60_000 });
    const worn = drawn.ground[0]!.material as pc.StandardMaterial;
    expect(worn.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS')).toContain('vPositionW.y * 1000.0 + 60000.0');
    drawn.destroy();
  });
});

describe("a landscape that stands a site on a volume's top", () => {
  it.each([0, 30_000, 250_500])('stands the island under the site and the site\'s corner at the page\'s origin, turned %i millidegrees', (yawMdeg) => {
    const { app, environmentRoot } = nullApp();
    const volumes = volumesOf(yawMdeg);
    const frame = volumes.drawing.siteFrame!;
    const drawn = drawSiteVolumes(app.graphicsDevice, volumes, new pc.StandardMaterial());
    environmentRoot.addChild(drawn.root);
    const placed = landscapePlacementM(volumes.drawing);
    expect(placed.yawDeg).toBeCloseTo(-yawMdeg / 1000, 9);
    // The site's south-west corner, a point of the landscape's frame, is the page's origin (to the
    // renderer's single precision, a tenth of a millimetre).
    close(drawn.root.getWorldTransform().transformPoint(new pc.Vec3(frame.atMm[0] / 1000, frame.atMm[2] / 1000, -frame.atMm[1] / 1000)), [0, 0, 0], 4);
    // The island's origin under the site's middle at the site's level 0, unturned in the page.
    const isle = drawn.root.findByName('site-volumes:isle') as pc.Entity;
    const middle: [number, number, number] = [drawing.extent.widthMm / 2000, 0, -drawing.extent.depthMm / 2000];
    close(isle.getPosition(), middle, 2);
    close(isle.getWorldTransform().transformVector(new pc.Vec3(1, 0, 0)), [1, 0, 0], 4);
    // Every volume where the site frame's inverse puts its origin.
    for (const volume of volumes.drawing.volumes) {
      const [x, y, z] = landscapeToSiteMm(frame, volume.atMm[0], volume.atMm[1], volume.atMm[2]);
      close((drawn.root.findByName(`site-volumes:${volume.id}`) as pc.Entity).getPosition(), [x / 1000, z / 1000, -y / 1000], 4);
    }
    drawn.destroy();
  });

  it('reads the land below with the landscape that names it, and only it', () => {
    const landscape = landscapeOf();
    const ground = readLandscapeGround(landscape.drawing, landscape.chunks, landscape.backdrop, sha256, 99);
    expect(ground.section).toBe(landscape.drawing.ground);
    expect(ground.chunks.map((chunk) => [chunk.chunkX, chunk.chunkY])).toEqual([[-1, 0], [0, 0]]);
    expect(() => readSiteVolumes(landscape.drawing, new Map(), sha256, 0)).toThrow('read with it');
    const other = landscapeOf();
    expect(() => readSiteVolumes(landscape.drawing, new Map(), sha256, 0, undefined, readLandscapeGround(other.drawing, other.chunks, other.backdrop, sha256))).toThrow('read with it');
    const tampered = new Map(landscape.chunks);
    tampered.set('0,0', { ...chunkDocument(0, 0), height_mm: (chunkDocument(0, 0)['height_mm'] as number[]).map((h) => h + 1) });
    expect(() => readLandscapeGround(landscape.drawing, tampered, landscape.backdrop, sha256)).toThrow('is the document its digest names');
  });
});

describe("a site on a volume's top, mounted", () => {
  it('draws the top in place of the base ground with no land chunks, no backdrop and no plane beyond, and the land below under the landscape', () => {
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    const farBefore = camera.camera!.farClip;
    const volumes = volumesOf(30_000);
    const mount = siteMount(drawing, { servedBytes: 1, land: topLand(), look: edgedLook(), landSurfaces: SURFACES, materials: MATERIALS, landscape: volumes });
    // A person stands on the top.
    const [east, north, up] = drawing.arrival.positionMm;
    expect(mount.navigationWorld.surface.sample(east / 1000, -north / 1000)!.height).toBeCloseTo(up / 1000, 9);
    const attachment = mount.attach({ app, camera, environmentRoot });
    // The site's own land is its top alone.
    const own = environmentRoot.children.find((child) => child.name === 'site-land') as pc.Entity;
    expect(own.children.map((child) => child.name)).toEqual(['site-land:top']);
    expect(own.findByName('site-land:backdrop')).toBeNull();
    // The base ground is kept for its dressing and not drawn; the look's plane beyond is not drawn.
    const base = environmentRoot.findByName(baseGroundSlot(drawing)!.identity) as pc.Entity;
    expect(base.enabled).toBe(false);
    expect((app.root.findByName('generated-tile:edge-ground') as pc.Entity).enabled).toBe(false);
    expect('siteGroundBeyond' in canvas.dataset).toBe(false);
    expect('siteScenery' in canvas.dataset).toBe(false);
    // The top's surfaces and the land below's stand their heights above the sea, from the island's level.
    const worn = (own.findByName('site-land:top') as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect(worn.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS')).toContain('vPositionW.y * 1000.0 + 60000.0');
    // The land below hangs from the landscape's root, whose frame puts the site's corner at the origin.
    const landscapeRoot = environmentRoot.findByName('site-volumes') as pc.Entity;
    const below = landscapeRoot.children.find((child) => child.name === 'site-land') as pc.Entity;
    expect(below.children.map((child) => child.name)).toEqual(['site-land:chunk:-1:0', 'site-land:chunk:0:0', 'site-land:backdrop', 'site-land:water:sea']);
    const belowWorn = (below.findByName('site-land:chunk:0:0') as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect(belowWorn.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS')).toContain('vPositionW.y * 1000.0 + 60000.0');
    // The sea below lies 60 m under the island's level.
    expect((below.findByName('site-land:water:sea') as pc.Entity).getPosition().y).toBeCloseTo(-60, 3);
    expect(camera.camera!.farClip).toBeGreaterThan(400 * Math.SQRT2);
    const said = JSON.parse(canvas.dataset['siteLand']!) as Record<string, unknown>;
    expect(said).toMatchObject({ top: FIXTURE.top_sha256, draped: 9, draws: 1 });
    // The held cells' two triangles each and the rim's fringe of half cells.
    expect(said['triangles']).toBeGreaterThan(2 * 1169);
    expect(said['triangles']).toBeLessThan(2 * 1169 + 200);
    expect(said['chunks']).toBeUndefined();
    const landscapeSaid = JSON.parse(canvas.dataset['siteLandscape']!) as { volumes: { id: string }[]; ground: { chunks: number } };
    expect(landscapeSaid.volumes.map((one) => one.id)).toEqual(['west_stack', 'east_stack', 'isle']);
    expect(landscapeSaid.ground.chunks).toBe(2);
    expect(attachment.metrics.transferredBytes).toBe(1 + 777 + 4321 + 99);
    attachment.dispose();
    expect(environmentRoot.findByName('site-land')).toBeNull();
    expect(environmentRoot.findByName('site-volumes')).toBeNull();
    expect('siteLand' in canvas.dataset).toBe(false);
    expect('siteLandscape' in canvas.dataset).toBe(false);
    expect(camera.camera!.farClip).toBe(farBefore);
  });

  it('floats in the sky alone with no landscape, and is not mounted without its top', () => {
    const { app, camera, environmentRoot } = nullApp();
    const attachment = siteMount(drawing, { servedBytes: 1, land: topLand(), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    expect((environmentRoot.findByName('site-land') as pc.Entity).children.map((child) => child.name)).toEqual(['site-land:top']);
    expect(environmentRoot.findByName('site-volumes')).toBeNull();
    attachment.dispose();
    expect(() => siteMount(drawing, { servedBytes: 1 })).toThrow("mounted with the top its drawing names");
    const other = readSiteTopLand(parseStructuredSiteDrawing(served()), structuredClone(FIXTURE.top), sha256);
    expect(() => siteMount(drawing, { servedBytes: 1, land: other })).toThrow("mounted with the top its drawing names");
  });
});

describe("walking and wearing a volume's top", () => {
  it('lets a person walk the drawn top round the site, out to its rim and no further', () => {
    const land = topLand();
    const surface = siteLandSurface(drawing, land);
    const [x0, y0] = land.top.originMm;
    const [, , width, depth] = drawing.walk.floorMm;
    // A drawn cell outside the site's floor is floor, at the top's height there.
    const outside = [...held()].map((cell) => cell.split(',').map(Number) as [number, number])
      .find(([row, column]) => y0 + row * 1000 + 500 < 0 || x0 + column * 1000 + 500 > width || y0 + row * 1000 + 500 > depth);
    expect(outside).toBeDefined();
    const [row, column] = outside!;
    const east = (x0 + column * 1000 + 500) / 1000, south = -(y0 + row * 1000 + 500) / 1000;
    const stood = surface.sample(east, south);
    expect(stood).not.toBeNull();
    expect(stood!.height).toBeCloseTo(land.groundM(east, south), 6);
    // The lattice's corner is past the round island's rim: no floor there.
    expect(surface.sample((x0 + 500) / 1000, -(y0 + 500) / 1000)).toBeNull();
    // The person's field reaches the top's edge, not only the site's.
    const world = siteNavigationWorld(drawing, undefined, land);
    expect(world.fieldRadius).toBeGreaterThan(Math.hypot(width, depth) / 2000);
  });

  it('wears the top matte, without its texture\'s shine, and leaves land worlds as they were', () => {
    const { app } = nullApp();
    const shiny = new pc.StandardMaterial();
    shiny.useMetalness = true;
    shiny.metalness = 1;
    shiny.gloss = 0.9;
    shiny.update();
    const top = drawSiteLand(app.graphicsDevice, topLand(), shiny, [0.4, 0.5, 0.3], SURFACES, { matte: true });
    const worn = top.ground[0]!.material as pc.StandardMaterial;
    expect([worn.metalness, worn.gloss, worn.metalnessMap, worn.glossMap]).toEqual([0, 0, null, null]);
    expect(worn).not.toBe(shiny);
    top.wear(shiny);
    expect((top.ground[0]!.material as pc.StandardMaterial).metalness).toBe(0);
    expect(shiny.metalness).toBe(1);
    // Without matte the land wears the material as it always did.
    const plain = drawSiteLand(app.graphicsDevice, topLand(), shiny, [0.4, 0.5, 0.3], null);
    expect(plain.ground[0]!.material).toBe(shiny);
    for (const one of [top, plain]) one.destroy();
  });
});

