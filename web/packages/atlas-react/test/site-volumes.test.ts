// @vitest-environment happy-dom
/**
 * A site on a landscape in the browser: its landscape drawing and the chunks of the level each volume
 * is drawn at are read and held to their digests, each volume stands at its origin and turn in the
 * renderer's frame with its faces turned out, and the mount draws the volumes on the land in the
 * engine's rock or the pack's, says so on the canvas and takes them all back.
 *
 * The landscape (`fixtures/landscape.v1.json`) is the server's own output: one small floating island
 * realized at 4 m by `exulanica.grammar.landscape`, placed 70 m up and turned 30 degrees. The site it
 * is mounted with is `site-land.test.ts`'s synthetic yard on land, its land rebuilt here the same way.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {
  canonicalJson, readLandscapeDrawing, readStylePackManifest, readSurfaceMaterials, resolveStylePack,
  type LandscapeDrawing, type LookFamily, type StylePackManifest,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  drawSiteVolumes, parseStructuredSiteDrawing, readSiteLand, readSiteVolumes, siteMount, siteVolumeChunks,
  volumeChunkVertices, volumeOriginM, type SiteVolumes, type StructuredSiteDrawing,
} from '../src/playcanvas/generated-site/index.js';
import { readSurfaceFinish } from '../src/playcanvas/style-pack/ground-finish.js';
import { packSiteDresser } from '../src/playcanvas/style-pack/site-dresser.js';

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/landscape.v1.json', 'utf8')) as {
  drawing: Record<string, unknown>; drawing_sha256: string; chunks: Record<string, unknown>;
};
const SITE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-land.v5.json', 'utf8')) as Record<string, unknown>;
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));

const drawingOf = (worldId?: string): LandscapeDrawing => {
  if (worldId === undefined) return readLandscapeDrawing(structuredClone(FIXTURE.drawing), sha256, FIXTURE.drawing_sha256);
  return readLandscapeDrawing({ ...structuredClone(FIXTURE.drawing), world_id: worldId }, sha256);
};
const bodies = (): Map<string, unknown> => new Map(Object.entries(structuredClone(FIXTURE.chunks)));
const volumesOf = (worldId?: string): SiteVolumes => readSiteVolumes(drawingOf(worldId), bodies(), sha256, 4321);
/** The fixture's landscape with its island's looks named, as a drawing does from 4c on. */
const toppedOf = (worldId: string, topLook: string): SiteVolumes => {
  const raw: Record<string, unknown> = { ...structuredClone(FIXTURE.drawing), world_id: worldId };
  const island = (raw['volumes'] as Record<string, unknown>[])[0]!;
  island['look'] = 'rock';
  island['top_look'] = topLook;
  return readSiteVolumes(readLandscapeDrawing(raw, sha256), bodies(), sha256, 4321);
};

/** The yard's land, as `site-land.test.ts` rebuilds it. */
const lattice = (east: number, north: number): number => 6000 + (40 * north) / 1000 + (east >= 8000 ? 500 : 0);
function chunkDocument(chunkX: number, chunkY: number): Record<string, unknown> {
  const height = [];
  for (let j = 0; j < 129; j += 1) for (let i = 0; i < 129; i += 1) height.push(lattice(chunkX * 128_000 + i * 1000, chunkY * 128_000 + j * 1000));
  return { profile: 'exulanica.landform-chunk/v1', chunk: [chunkX, chunkY], cell_mm: 1000, samples_per_side: 129, height_mm: height };
}
const xs = [-400_000, -128_000, 0, 128_000, 400_000], ys = [-400_000, 0, 128_000, 400_000];
const backdrop = (): Record<string, unknown> => ({
  profile: 'exulanica.landform-backdrop/v1', near_mm: [-128_000, 0, 128_000, 128_000], x_mm: xs, y_mm: ys,
  height_mm: ys.flatMap((y) => xs.map((x) => (y < 0 ? -20_000 : y > 128_000 ? 150_000 : lattice(x, y)))),
  water: [{ id: 'sea', kind: 'sea', level_mm: 0, side: 'south' }],
});
const landOf = (drawing: StructuredSiteDrawing) =>
  readSiteLand(drawing, new Map([['-1,0', chunkDocument(-1, 0)], ['0,0', chunkDocument(0, 0)]]), backdrop(), sha256, 1234);

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

describe('reading a landscape', () => {
  it('holds the server\'s drawing and every chunk of the drawn level to their digests', () => {
    const drawing = drawingOf();
    expect(drawing.volumes.map((volume) => volume.id)).toEqual(['small_island']);
    const refs = siteVolumeChunks(drawing);
    expect(refs.length).toBe(Object.keys(FIXTURE.chunks).length);
    const volumes = volumesOf();
    const [island] = volumes.volumes;
    expect(island!.cellMm).toBe(4000);
    expect(island!.chunks.reduce((sum, chunk) => sum + chunk.triangles.length / 3, 0)).toBe(264);
    expect(volumes.servedBytes).toBe(4321);
  });

  it('refuses a chunk it was not given, or one that is not the chunk its drawing names', () => {
    const drawing = drawingOf();
    const [first, second] = siteVolumeChunks(drawing);
    const missing = bodies();
    missing.delete(first!.sha256);
    expect(() => readSiteVolumes(drawing, missing, sha256, 0)).toThrow(/was not fetched/);
    const swapped = bodies();
    swapped.set(first!.sha256, FIXTURE.chunks[second!.sha256]);
    expect(() => readSiteVolumes(drawing, swapped, sha256, 0)).toThrow(/digest names/);
  });
});

describe('a volume in the renderer\'s frame', () => {
  it('stands at its origin, east as x, up as y and north as minus z', () => {
    const [volume] = drawingOf().volumes;
    expect(volumeOriginM(volume!)).toEqual([32, 70, 60]);
  });

  it('keeps every face turned from solid toward air, as its normals say', () => {
    let agreeing = 0, faces = 0;
    for (const chunk of volumesOf().volumes[0]!.chunks) {
      const { positions, normals } = volumeChunkVertices(chunk);
      const at = (v: number) => new pc.Vec3(positions[3 * v]!, positions[3 * v + 1]!, positions[3 * v + 2]!);
      for (let t = 0; t < chunk.triangles.length; t += 3) {
        const [a, b, c] = [chunk.triangles[t]!, chunk.triangles[t + 1]!, chunk.triangles[t + 2]!];
        const face = new pc.Vec3().cross(at(b).sub(at(a)), at(c).sub(at(a)));
        const normal = new pc.Vec3();
        for (const v of [a, b, c]) normal.add(new pc.Vec3(normals[3 * v]!, normals[3 * v + 1]!, normals[3 * v + 2]!));
        faces += 1;
        if (face.dot(normal) > 0) agreeing += 1;
      }
    }
    expect(faces).toBe(264);
    expect(agreeing / faces).toBeGreaterThan(0.95);
  });
});

describe('drawing the volumes', () => {
  it('places each volume at its origin and turn, one mesh per chunk, and takes them all back', () => {
    const { app } = nullApp();
    const plain = new pc.StandardMaterial();
    const drawn = drawSiteVolumes(app.graphicsDevice, volumesOf(), plain);
    // A landscape in the site's own frame stands its root at the site's origin, unturned, with no land below.
    const root = drawn.root.getLocalPosition();
    expect([root.x, root.y, root.z]).toEqual([0, 0, 0]);
    expect(drawn.root.getLocalEulerAngles().y).toBe(0);
    expect(volumesOf().ground).toBeNull();
    const placed = drawn.root.findByName('site-volumes:small_island') as pc.Entity;
    const at = placed.getLocalPosition();
    expect([at.x, at.y, at.z]).toEqual([32, 70, 60]);
    expect(placed.getLocalEulerAngles().y).toBeCloseTo(30, 5);
    expect(drawn.triangles).toBe(264);
    expect(drawn.draws).toBe(volumesOf().volumes[0]!.chunks.filter((chunk) => chunk.triangles.length > 0).length);
    const other = new pc.StandardMaterial();
    drawn.wear(other);
    expect(drawn.instances.every((instance) => instance.material === other)).toBe(true);
    const topped = new pc.StandardMaterial();
    expect(drawn.wearEach(() => null)).toBe(0);
    expect(drawn.instances.every((instance) => instance.material === other)).toBe(true);
    expect(drawn.wearEach((volume) => (volume.id === 'small_island' ? topped : null))).toBe(1);
    expect(drawn.instances.every((instance) => instance.material === topped)).toBe(true);
    drawn.destroy();
    drawn.destroy();
  });

  it('leaves out a volume\'s upward faces only where something else draws its top, and only that volume\'s', () => {
    const { app } = nullApp();
    const plain = new pc.StandardMaterial();
    const volumes = volumesOf();
    const upward = (chunk: (typeof volumes.volumes)[number]['chunks'][number]): number => {
      let count = 0;
      for (let i = 0; i < chunk.triangles.length; i += 3) {
        if ([0, 1, 2].every((k) => chunk.normals[3 * chunk.triangles[i + k]! + 2]! >= Math.round(0.72 * 32_767))) count += 1;
      }
      return count;
    };
    const faces = volumes.volumes[0]!.chunks.reduce((sum, chunk) => sum + upward(chunk), 0);
    expect(faces).toBeGreaterThan(0);
    // Everything covered: every upward face is left out, and every other face is kept.
    const all = drawSiteVolumes(app.graphicsDevice, volumes, plain, (id) => id === 'small_island');
    expect(all.triangles).toBe(264 - faces);
    // Another volume covered, or none: nothing is left out.
    expect(drawSiteVolumes(app.graphicsDevice, volumes, plain, (id) => id === 'elsewhere').triangles).toBe(264);
    // Covered only east of the volume's axis: some upward faces go, fewer than all.
    const half = drawSiteVolumes(app.graphicsDevice, volumes, plain, (id, xMm) => id === 'small_island' && xMm > 0);
    expect(half.triangles).toBeGreaterThan(264 - faces);
    expect(half.triangles).toBeLessThan(264);
    for (const drawn of [all, half]) drawn.destroy();
  });
});

describe('a site on a landscape, mounted', () => {
  const site = parseStructuredSiteDrawing(structuredClone(SITE));
  const worldId = site.worldId;

  it('draws the volumes on the land in the engine\'s rock, says so on the canvas, and takes them back', () => {
    const { app, camera, environmentRoot } = nullApp();
    const plain = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const plainTriangles = plain.metrics.triangles;
    plain.dispose();
    const attachment = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS, landscape: volumesOf(worldId) })
      .attach({ app, camera, environmentRoot });
    const root = environmentRoot.findByName('site-volumes') as pc.Entity;
    expect(root).not.toBeNull();
    expect(attachment.metrics.triangles).toBe(plainTriangles + 264);
    const said = JSON.parse((app.graphicsDevice.canvas as HTMLCanvasElement).dataset['siteLandscape']!) as { volumes: { id: string; cellMm: number }[]; dressed: boolean };
    expect(said.volumes).toEqual([{ id: 'small_island', cellMm: 4000, chunks: volumesOf().volumes[0]!.chunks.length, topLook: null }]);
    expect(said.dressed).toBe(false);
    attachment.dispose();
    expect(environmentRoot.findByName('site-volumes')).toBeNull();
    expect((app.graphicsDevice.canvas as HTMLCanvasElement).dataset['siteLandscape']).toBeUndefined();
  });

  it('refuses another world\'s landscape', () => {
    const { app, camera, environmentRoot } = nullApp();
    const mount = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS, landscape: volumesOf('world:another') });
    expect(() => mount.attach({ app, camera, environmentRoot })).toThrow(/its own world/);
  });

  it('draws the volumes in the pack\'s rock when its dresser makes one', () => {
    const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { context: { texture_sets: string[] }; cases: { name: string; manifest: StylePackManifest }[] };
    const LOOK_FAMILIES = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
      entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
    };
    const families = new Map<string, LookFamily>(LOOK_FAMILIES.entries.map((entry) => [entry.key, {
      fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
    }]));
    const manifest = CASES.cases.find((one) => one.name === 'a complete pack with no base')!.manifest;
    const pack = resolveStylePack([readStylePackManifest(manifest, { families, textureSets: new Set(CASES.context.texture_sets) })]);
    const finish = readSurfaceFinish(JSON.parse(readFileSync('../assets/catalogs/world-kinds/surface-finish.v2.json', 'utf8')));
    const dress = packSiteDresser({ pack, families, pieces: { pieces: new Map() }, shading: { model: 'pbr', toon: null, ink: null }, materials: MATERIALS, finish });
    const { app, camera, environmentRoot } = nullApp();
    const attachment = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS, dress, landscape: volumesOf(worldId) })
      .attach({ app, camera, environmentRoot });
    const placed = environmentRoot.findByName('site-volumes:small_island') as pc.Entity;
    expect(placed.render!.meshInstances[0]!.material.name).toBe('style-pack:volumes:rock');
    const said = JSON.parse((app.graphicsDevice.canvas as HTMLCanvasElement).dataset['siteLandscape']!) as { dressed: boolean };
    expect(said.dressed).toBe(true);
    attachment.dispose();
    // An island whose upward faces are grass wears the rock with the look's grass on them; one whose
    // top is rock wears the rock alone.
    const grassy = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS, dress, landscape: toppedOf(worldId, 'grass') })
      .attach({ app, camera, environmentRoot });
    const island = environmentRoot.findByName('site-volumes:small_island') as pc.Entity;
    const worn = island.render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect(worn.name).toBe('style-pack:volumes:rock:grass');
    expect(worn.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS')).toMatch(/normalize\(vNormalW\)\.y/);
    const grassSaid = JSON.parse((app.graphicsDevice.canvas as HTMLCanvasElement).dataset['siteLandscape']!) as { volumes: { topLook: string | null }[] };
    expect(grassSaid.volumes.map((one) => one.topLook)).toEqual(['grass']);
    grassy.dispose();
    const rocky = siteMount(site, { servedBytes: 1, land: landOf(site), materials: MATERIALS, dress, landscape: toppedOf(worldId, 'rock') })
      .attach({ app, camera, environmentRoot });
    const bare = (environmentRoot.findByName('site-volumes:small_island') as pc.Entity).render!.meshInstances[0]!.material;
    expect(bare.name).toBe('style-pack:volumes:rock');
    rocky.dispose();
  });

  it('is the same document the fixture names', () => {
    expect(sha256(new TextEncoder().encode(canonicalJson(FIXTURE.drawing)))).toBe(FIXTURE.drawing_sha256);
  });
});
