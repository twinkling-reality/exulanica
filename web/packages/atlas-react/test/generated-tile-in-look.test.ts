// @vitest-environment happy-dom
/**
 * A loaded tile drawn in another look (`inLook`) without loading it again.
 *
 * A look is read only when a tile is attached, so the tile in another look shares what loading
 * made: the verified and decoded containers, the prepared texture sets, the plan and the
 * navigation. The equivalence test is the claim that sharing them changes nothing drawn: the tile
 * loaded in one look and moved to another attaches exactly the scene a tile loaded in that other
 * look attaches, compared by value (scene settings, lights, entities, meshes, materials and the
 * texels a look writes), never by pixels. A control shows the comparison sees a change of look.
 */
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  parseTextureSetManifest,
  readStylePackManifest,
  resolveStylePack,
  textureSetBlobPath,
  type LookFamily,
  type TextureSetDigest,
  type TextureSetManifestEntry,
} from '@exulanica/atlas-core';
import { bakeTile } from '@exulanica/loom-tess/core';
import { TILE_LOOK_V1, type TileLook } from '../src/playcanvas/generated-tile/look.js';
import { loadGeneratedTile, type LoadedGeneratedTile } from '../src/playcanvas/generated-tile/tile-runtime.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

// Relative to web/, where the suite runs.
const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
const TEXTURES = '../assets/textures/';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync(`${TEXTURES}manifest.json`)));
const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
/** Every set the tile cites, as committed, so textured surfaces are drawn too. */
const fetchSet = async (entry: TextureSetManifestEntry): Promise<Uint8Array> =>
  new Uint8Array(readFileSync(`${TEXTURES}${textureSetBlobPath(entry)}`));
/** Loading verifies and decodes every container and set: seconds, not vitest's default 5. */
const LOADS_TIMEOUT_MS = 120_000;

/** The default light of a committed pack, as the page builds a tile look from it. */
function packLook(packId: string): TileLook {
  const catalog = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
    entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
  };
  const families = new Map<string, LookFamily>(catalog.entries.map((e) => [e.key, {
    fit: e.fit, dressing: e.dressing, fillMinimumPermille: e.fill_minimum_permille, fillMaximumPermille: e.fill_maximum_permille,
  }]));
  const read = readStylePackManifest(
    JSON.parse(readFileSync(`../assets/style-packs/packs/${packId}/manifest.json`, 'utf8')),
    { families, textureSets: new Set(manifest.byId.keys()) },
  );
  const pack = resolveStylePack([read]);
  return renderLookOfPreset(pack.light.presets[pack.light.default_preset]!, pack.shading, pack.edge);
}

function host(): { app: pc.AppBase; camera: pc.Entity; environmentRoot: pc.Entity } {
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = 200;
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const environmentRoot = new pc.Entity('geographic-environment');
  app.root.addChild(environmentRoot);
  return { app, camera, environmentRoot };
}

/** Fields that name an object rather than describe it: ids, caches, back references. */
const IDENTITY = new Set([
  'id', 'userId', '_guid', 'meshInstances', 'variants', 'parameters', 'device', '_device', '_scene', 'dirty',
  '_dirtyShader', '_shaderVersion', '_definesDirty', '_definesKey', '_assetReferences', '_activeParams',
  '_activeLightingParams', 'shaderOptBuilder', '_uniformCache', '_oldChunks', 'impl', '_gpuSize', 'renderVersionDirty',
]);

/** A value as data: numbers, strings and the content of what it holds, never an object's identity. */
function described(value: unknown, depth = 0): unknown {
  if (value === null || value === undefined) return null;
  if (typeof value === 'function') return undefined;
  if (typeof value !== 'object') return value;
  if (ArrayBuffer.isView(value)) {
    const view = value as ArrayBufferView;
    return `${view.constructor.name}:${createHash('sha256').update(new Uint8Array(view.buffer, view.byteOffset, view.byteLength)).digest('hex')}`;
  }
  if (value instanceof pc.Color) return [value.r, value.g, value.b, value.a];
  if (value instanceof pc.Vec2 || value instanceof pc.Vec3 || value instanceof pc.Vec4 || value instanceof pc.Quat) {
    return Object.values(value);
  }
  if (value instanceof pc.Texture) {
    return {
      name: value.name, width: value.width, height: value.height, format: value.format, cubemap: value.cubemap,
      mipmaps: value.mipmaps, anisotropy: value.anisotropy, addressU: value.addressU, addressV: value.addressV,
      minFilter: value.minFilter, magFilter: value.magFilter,
      levels: described((value as unknown as { _levels?: unknown })._levels, depth + 1),
    };
  }
  if (depth > 6) return '(deeper)';
  if (value instanceof Map) return [...value.entries()].map(([k, v]) => [String(k), described(v, depth + 1)]).sort();
  if (value instanceof Set) return [...value].map((v) => described(v, depth + 1)).sort();
  if (Array.isArray(value)) return value.map((v) => described(v, depth + 1));
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) {
    if (IDENTITY.has(key)) continue;
    const field = described((value as Record<string, unknown>)[key], depth + 1);
    if (field !== undefined) out[key] = field;
  }
  return out;
}

function meshOf(mesh: pc.Mesh): unknown {
  const read = (fill: (into: number[]) => number): string => {
    const into: number[] = [];
    fill(into);
    return createHash('sha256').update(new Uint8Array(new Float64Array(into).buffer)).digest('hex');
  };
  return {
    positions: read((into) => mesh.getPositions(into)),
    normals: read((into) => mesh.getNormals(into)),
    uvs: read((into) => mesh.getUvs(0, into)),
    indices: read((into) => mesh.getIndices(into)),
    primitive: mesh.primitive.map((p) => [p.type, p.base, p.count, p.indexed]),
  };
}

/** Everything under the app's root, in tree order: what each entity is, where, and what it draws. */
function entitiesOf(root: pc.GraphNode, path = ''): unknown[] {
  const out: unknown[] = [];
  for (const child of root.children) {
    const entity = child as pc.Entity;
    const at = `${path}/${entity.name}`;
    const light = entity.light;
    const render = entity.render;
    out.push({
      at,
      enabled: entity.enabled,
      position: [...Object.values(entity.getLocalPosition())],
      rotation: [...Object.values(entity.getLocalRotation())],
      scale: [...Object.values(entity.getLocalScale())],
      light: light === undefined ? null : {
        type: light.type, color: described(light.color), intensity: light.intensity, castShadows: light.castShadows,
        shadowResolution: light.shadowResolution, shadowDistance: light.shadowDistance, numCascades: light.numCascades,
        cascadeDistribution: light.cascadeDistribution, shadowBias: light.shadowBias,
        normalOffsetBias: light.normalOffsetBias, shadowType: light.shadowType, penumbraSize: light.penumbraSize,
      },
      render: render === undefined ? null : {
        castShadows: render.castShadows,
        receiveShadows: render.receiveShadows,
        meshInstances: render.meshInstances.map((instance) => ({
          drawBucket: instance.drawBucket,
          mesh: meshOf(instance.mesh),
          material: { kind: instance.material.constructor.name, fields: described(instance.material) },
        })),
      },
    });
    out.push(...entitiesOf(entity, at));
  }
  return out;
}

/** What attaching `tile` puts in a fresh scene, as data, and the scene left after it is taken down. */
function builtScene(tile: LoadedGeneratedTile): { attached: unknown; after: unknown } {
  const { app, camera, environmentRoot } = host();
  const sceneOf = () => ({
    exposure: app.scene.exposure,
    ambient: described(app.scene.ambientLight),
    fog: { type: app.scene.fog.type, start: app.scene.fog.start, end: app.scene.fog.end, density: app.scene.fog.density, color: described(app.scene.fog.color) },
    skyboxIntensity: app.scene.skyboxIntensity,
    skybox: described(app.scene.skybox),
    envAtlas: described(app.scene.envAtlas),
    clearColor: described(camera.camera!.clearColor),
    toneMapping: camera.camera!.toneMapping,
    entities: entitiesOf(app.root),
  });
  const attachment = tile.attach({ app, environmentRoot, camera });
  const attached = { metrics: attachment.metrics, scene: sceneOf() };
  attachment.dispose();
  const after = sceneOf();
  app.destroy();
  return { attached, after };
}

let baked: Uint8Array;
const loadedIn = (look: TileLook): Promise<LoadedGeneratedTile> =>
  loadGeneratedTile({ name: 'tile-conformance', bytes: baked, manifest, fetchSet, digest: subtle, look });

beforeAll(async () => {
  baked = (await bakeTile(new Uint8Array(readFileSync(FIXTURE)), sha256)).container;
}, 60_000);

describe('a loaded tile in another look', () => {
  it('shares everything loading made, states the new look, attaches in it, and leaves the tile it came from as it was', async () => {
    const toon = packLook('exulanica.toon-town');
    const tile = await loadedIn(TILE_LOOK_V1);
    const relit = tile.inLook(toon);
    expect(relit.look).toBe(toon);
    expect(tile.look).toBe(TILE_LOOK_V1);
    for (const key of ['header', 'ranges', 'navigation', 'navigationWorld', 'routeObstructions', 'worldTiles'] as const) {
      expect(relit[key]).toBe(tile[key]);
    }
    expect(relit.start).toEqual(tile.start);
    expect(relit.transferredBytes).toBe(tile.transferredBytes);
    const { app, camera, environmentRoot } = host();
    const attachment = relit.attach({ app, environmentRoot, camera });
    expect(attachment.metrics).toMatchObject({ lookId: toon.id, lookVersion: toon.version });
    // The toon pack's look draws an edge ground, which the tile look does not.
    expect(app.root.findByName('generated-tile:edge-ground')).not.toBeNull();
    attachment.dispose();
    app.destroy();
    // Back again: the tile in its first look attaches in that look.
    const back = relit.inLook(TILE_LOOK_V1);
    const second = host();
    const again = back.attach({ app: second.app, environmentRoot: second.environmentRoot, camera: second.camera });
    expect(again.metrics).toMatchObject({ lookId: TILE_LOOK_V1.id, lookVersion: TILE_LOOK_V1.version });
    expect(second.app.root.findByName('generated-tile:edge-ground')).toBeNull();
    again.dispose();
    second.app.destroy();
  }, LOADS_TIMEOUT_MS);

  it('attaches exactly what a tile loaded in that look attaches, either way, and the comparison sees a change of look', async () => {
    const toon = packLook('exulanica.toon-town');
    const plain = await loadedIn(TILE_LOOK_V1);
    const inToon = await loadedIn(toon);
    const loadedPlain = builtScene(plain);
    const loadedToon = builtScene(inToon);
    // The control: two looks build two different scenes, so equality below says something.
    expect(loadedToon.attached).not.toEqual(loadedPlain.attached);
    // Textured surfaces are among what is compared, not only the unavailable pattern.
    expect((loadedToon.attached as { metrics: { drawBatches: number } }).metrics.drawBatches).toBeGreaterThan(1);
    expect(builtScene(plain.inLook(toon))).toEqual(loadedToon);
    expect(builtScene(inToon.inLook(TILE_LOOK_V1))).toEqual(loadedPlain);
  }, LOADS_TIMEOUT_MS);
});
