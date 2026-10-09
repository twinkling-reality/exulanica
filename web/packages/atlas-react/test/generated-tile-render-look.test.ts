// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, textureSetBlobPath, type TextureSetDigest } from '@exulanica/atlas-core';
import { bakeTile } from '@exulanica/loom-tess/core';
import { RENDER_SHADOW_TYPES, applyTileEnvironment } from '../src/playcanvas/generated-tile/environment.js';
import { INK_OPTIONS, attachTileInk, inkSegments } from '../src/playcanvas/generated-tile/ink.js';
import {
  RENDER_LOOK_ID,
  TILE_LOOK_V1,
  TileLookError,
  validateLook,
  validateRenderLook,
  type RenderLook,
} from '../src/playcanvas/generated-tile/look.js';
import { applyShading, shadingChunks } from '../src/playcanvas/generated-tile/shading.js';
import { latticeHash, renderSkyFaces, renderSkyRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { TileTextureLibrary } from '../src/playcanvas/generated-tile/texture-materials.js';
import { loadGeneratedTile } from '../src/playcanvas/generated-tile/tile-runtime.js';

/**
 * A complete render look, written out here rather than imported, so every expectation below is read
 * from values this test states.
 */
const LOOK: RenderLook = {
  id: RENDER_LOOK_ID,
  version: 1,
  exposure: 1,
  toneMapping: 'neutral',
  sky: {
    zenith: [0.1, 0.3, 0.8],
    horizon: [0.6, 0.7, 0.8],
    ground: [0.2, 0.5, 0.1],
    bounceGround: [0.3, 0.3, 0.3],
    intensity: 2,
    sunGlow: 0,
    sunDisc: 40,
    clouds: null,
    faceTexels: 64,
  },
  fog: { kind: 'exp2', density: 0.001, colour: [0.7, 0.75, 0.8] },
  sun: {
    elevationDeg: 40,
    azimuthDeg: 0,
    colour: [1, 0.9, 0.8],
    intensity: 2.5,
    shadow: { resolution: 4096, distanceM: 140, cascades: 4, cascadeDistribution: 0.6, bias: 0.12, normalOffsetBias: 0.08, filter: 'pcss', penumbra: 6 },
  },
  environment: { intensity: 1, atlasSize: 256, sourceSize: 32 },
  contactShadow: { mode: 'lighting', radiusM: 0.5, intensity: 0.5, samples: 16, power: 2, minAngleDeg: 10, blur: true, scale: 1 },
  surface: { normalStrength: 1, anisotropy: 8, parallax: false, parallaxFactor: 0 },
  post: {
    bloom: { intensity: 0.02, blurLevel: 12 },
    grading: { brightness: 1, contrast: 1.05, saturation: 1.1, tint: [1, 0.98, 0.95] },
    enhance: { shadows: 0.1, highlights: -0.05, midtones: 0, vibrance: 0.15, dehaze: 0 },
    vignette: { intensity: 0.25, inner: 0.5, outer: 1.2, curvature: 0.6, colour: [0, 0, 0] },
    taa: true,
  },
  shading: { model: 'toon', toon: { shadowEdge: 0.1, lightEdge: 0.6, bandShare: 0.7, softness: 0.04 }, ink: [0.1, 0.12, 0.2] },
  edge: { ground: [0.3, 0.45, 0.2], dropM: 0.6, reachM: 3000 },
  unavailable: { ink: [0.9, 0.05, 0.6], ground: [0.02, 0.02, 0.02], stripeTexels: 16, tileMm: 1200 },
};

type Mutable = Record<string, unknown>;
const copy = (): Mutable => structuredClone(LOOK) as unknown as Mutable;
const at = (look: Mutable, path: string): Mutable => path.split('.').reduce((node, key) => node[key] as Mutable, look);
const refused = (value: unknown): string => {
  try {
    validateRenderLook(value);
  } catch (error) {
    if (error instanceof TileLookError) return error.message;
    throw error;
  }
  throw new Error('the look was accepted');
};

describe('the render look descriptor', () => {
  it('validates a complete look and returns a frozen copy', () => {
    const look = validateRenderLook(LOOK);
    expect(look).toEqual(LOOK);
    expect(Object.isFrozen(look.post.grading)).toBe(true);
    expect(look).not.toBe(LOOK);
  });

  it('keeps the probe and the contact shadowing without an off switch', () => {
    for (const path of ['environment', 'contactShadow']) {
      const look = copy();
      at(look, path)['enabled'] = false;
      expect(refused(look)).toBe(`${path}: has an unknown key "enabled"`);
    }
  });

  it('holds a linear fog to the 40 to 60 m onset and bounds an exponential one', () => {
    const linear = copy();
    linear['fog'] = { kind: 'linear', startM: 39, endM: 400, colour: [0.5, 0.5, 0.5] };
    expect(refused(linear)).toMatch(/^fog\.startM: must be within 40 to 60/);
    linear['fog'] = { kind: 'linear', startM: 50, endM: 400, colour: [0.5, 0.5, 0.5] };
    expect(() => validateRenderLook(linear)).not.toThrow();
    const dense = copy();
    at(dense, 'fog')['density'] = 0.01;
    expect(refused(dense)).toBe('fog.density: must be within 0.0001 to 0.006');
    const other = copy();
    at(other, 'fog')['kind'] = 'volumetric';
    expect(refused(other)).toBe('fog: kind must be one of linear, exp2');
    const mixed = copy();
    at(mixed, 'fog')['startM'] = 50;
    expect(refused(mixed)).toBe('fog: has an unknown key "startM"');
  });

  it('states toon bands exactly for the toon model, in order', () => {
    const missing = copy();
    at(missing, 'shading')['toon'] = null;
    expect(refused(missing)).toBe('shading: toon bands are stated exactly when the model is toon');
    const stray = copy();
    at(stray, 'shading')['model'] = 'flat';
    expect(refused(stray)).toBe('shading: toon bands are stated exactly when the model is toon');
    const inverted = copy();
    at(inverted, 'shading.toon')['shadowEdge'] = 0.7;
    expect(refused(inverted)).toBe('shading.toon: shadowEdge must lie below lightEdge');
    const flat = copy();
    at(flat, 'shading')['model'] = 'flat';
    at(flat, 'shading')['toon'] = null;
    expect(validateRenderLook(flat).shading.model).toBe('flat');
  });

  it('allows a penumbra only for the soft filter, and refuses out-of-range finish anywhere', () => {
    const penumbra = copy();
    at(penumbra, 'sun.shadow')['filter'] = 'pcf5';
    expect(refused(penumbra)).toBe('sun.shadow: penumbra must be 0 unless the filter is pcss');
    const bloom = copy();
    at(bloom, 'post.bloom')['intensity'] = 0.5;
    expect(refused(bloom)).toBe('post.bloom.intensity: must be within 0 to 0.2');
    const clouds = copy();
    at(clouds, 'sky')['clouds'] = { cover: 1.2, colour: [1, 1, 1], shade: [0.8, 0.8, 0.9], scale: 1, seed: 3 };
    expect(refused(clouds)).toBe('sky.clouds.cover: must be within 0 to 1');
    const texels = copy();
    at(texels, 'sky')['faceTexels'] = 512;
    expect(refused(texels)).toMatch(/^sky\.faceTexels: must be one of 64, 128, 256/);
    const unknown = copy();
    at(unknown, 'post')['shader'] = 'void main() {}';
    expect(refused(unknown)).toBe('post: has an unknown key "shader"');
  });

  it('is told apart from the tile look by its id', () => {
    expect(validateLook(TILE_LOOK_V1)).toEqual(TILE_LOOK_V1);
    expect(validateLook(LOOK)).toEqual(LOOK);
    const misnamed = copy();
    misnamed['id'] = 'exulanica.render-looks';
    // Not a render look, so the tile look's rules read it, and its first key the tile look lacks is refused.
    expect(() => validateLook(misnamed)).toThrow(': has an unknown key "post"');
  });
});

describe('the render look sky', () => {
  // Expected values follow the sky's stated definition: straight up is the zenith, level is the
  // horizon, straight down is the ground (the bounce ground for the image light), each times the
  // intensity; the sun sits at azimuth 0 and 40 degrees up, so these directions are far from it and
  // the glow is 0.
  it('is the stated colours at the zenith, the horizon and the nadir', () => {
    const round = (c: number): number => Math.round(c * 1e9) / 1e9;
    expect(renderSkyRadiance(LOOK, [0, 1, 0]).map(round)).toEqual([0.2, 0.6, 1.6]);
    const level = renderSkyRadiance(LOOK, [0, 0, 1]);
    expect(level.map((c) => Math.round(c * 1e9) / 1e9)).toEqual([1.2, 1.4, 1.6]);
    expect(renderSkyRadiance(LOOK, [0, -1, 0]).map((c) => Math.round(c * 1e9) / 1e9)).toEqual([0.4, 1, 0.2]);
    expect(renderSkyRadiance(LOOK, [0, -1, 0], true).map((c) => Math.round(c * 1e9) / 1e9)).toEqual([0.6, 0.6, 0.6]);
  });

  it('draws the sun disc in the sky and never in the image light', () => {
    const elevation = (40 * Math.PI) / 180;
    // The light travels along (-cos e sin a, -sin e, -cos e cos a) with azimuth 0: the sun is at (0, sin e, cos e).
    const toward: [number, number, number] = [0, Math.sin(elevation), Math.cos(elevation)];
    const drawn = renderSkyRadiance(LOOK, toward);
    const lighting = renderSkyRadiance(LOOK, toward, true);
    // The disc adds 40 times the sun's colour, times the intensity 2: 80 in red.
    expect(drawn[0] - lighting[0]).toBeCloseTo(80, 9);
    expect(drawn[2] - lighting[2]).toBeCloseTo(64, 9);
  });

  it('lays the same clouds for the same seed, only above the horizon', () => {
    const cloudy = { ...LOOK, sky: { ...LOOK.sky, clouds: { cover: 0.6, colour: [1, 1, 1] as const, shade: [0.7, 0.7, 0.8] as const, scale: 1, seed: 11 } } };
    const other = { ...cloudy, sky: { ...cloudy.sky, clouds: { ...cloudy.sky.clouds, seed: 12 } } };
    const dome: [number, number, number][] = [];
    for (let i = 0; i < 64; i += 1) dome.push([Math.cos(i), 0.3 + (i % 7) / 10, Math.sin(i * 1.3)]);
    const first = dome.map((d) => renderSkyRadiance(cloudy, d));
    expect(dome.map((d) => renderSkyRadiance(cloudy, d))).toEqual(first);
    expect(dome.some((d, i) => renderSkyRadiance(other, d)[0] !== first[i]![0])).toBe(true);
    expect(dome.some((d, i) => renderSkyRadiance(LOOK, d)[0] !== first[i]![0])).toBe(true);
    const below: [number, number, number] = [0.6, -0.3, 0.2];
    expect(renderSkyRadiance(cloudy, below)).toEqual(renderSkyRadiance(LOOK, below));
  });

  it('hashes lattice points to fractions, the same every time', () => {
    const values = new Set<number>();
    for (let x = -50; x < 50; x += 1) {
      const value = latticeHash(x, x * 3, 7);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
      expect(latticeHash(x, x * 3, 7)).toBe(value);
      values.add(value);
    }
    expect(values.size).toBe(100);
  });

  it('fills six faces of the stated size with opaque texels', () => {
    const faces = renderSkyFaces(LOOK, 8);
    expect(faces).toHaveLength(6);
    for (const face of faces) {
      expect(face).toHaveLength(8 * 8 * 4);
      for (let at = 3; at < face.length; at += 4) expect(face[at]).toBe(1);
    }
  });
});

describe('the shading models', () => {
  it('sets no chunk for physically based shading', () => {
    expect(shadingChunks({ model: 'pbr', toon: null, ink: null })).toEqual({ glsl: {}, wgsl: {} });
    const material = new pc.StandardMaterial();
    expect(applyShading(material, { model: 'pbr', toon: null, ink: null })).toBe(false);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('lightDiffuseLambertPS')).toBe(false);
  });

  it('writes the toon bands from the look, at fixed precision, in both shader languages', () => {
    // shadowEdge 0.1 and lightEdge 0.6, each widened by half the 0.04 softness; the first band 0.7.
    const chunks = shadingChunks(LOOK.shading);
    for (const code of [chunks.glsl['lightDiffuseLambertPS']!, chunks.wgsl['lightDiffuseLambertPS']!]) {
      expect(code).toContain('smoothstep(0.0800, 0.1200, d) * 0.7000 + smoothstep(0.5800, 0.6200, d) * 0.3000');
    }
    const material = new pc.StandardMaterial();
    expect(applyShading(material, LOOK.shading)).toBe(true);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('lightDiffuseLambertPS')).toBe(chunks.glsl['lightDiffuseLambertPS']);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).get('lightDiffuseLambertPS')).toBe(chunks.wgsl['lightDiffuseLambertPS']);
  });

  it('takes a flat face normal from screen-space derivatives', () => {
    const chunks = shadingChunks({ model: 'flat', toon: null, ink: null });
    expect(chunks.glsl['normalMapPS']).toContain('cross(dFdx(vPositionW), dFdy(vPositionW))');
    expect(chunks.wgsl['normalMapPS']).toContain('cross(dpdx(vPositionW), dpdy(vPositionW))');
    // The normal-map uniforms stay declared for materials that name them.
    expect(chunks.glsl['normalMapPS']).toContain('uniform float material_bumpiness;');
  });
});

/** Triangles whose corners are each their own vertex, as a tile's surfaces are drawn. */
function soup(triangles: readonly (readonly [number, number, number])[][]): { positions: Float32Array; corners: number[] } {
  const positions: number[] = [];
  const corners: number[] = [];
  for (const triangle of triangles) {
    for (const point of triangle) {
      corners.push(positions.length / 3);
      positions.push(...point);
    }
  }
  return { positions: new Float32Array(positions), corners };
}

describe('ink lines', () => {
  it('inks a cube\'s twelve edges and none of its face diagonals', () => {
    const v = (x: number, y: number, z: number): [number, number, number] => [x, y, z];
    const quad = (a: [number, number, number], b: [number, number, number], c: [number, number, number], d: [number, number, number]) => [[a, b, c], [a, c, d]];
    const triangles = [
      ...quad(v(0, 0, 0), v(1, 0, 0), v(1, 1, 0), v(0, 1, 0)),
      ...quad(v(0, 0, 1), v(0, 1, 1), v(1, 1, 1), v(1, 0, 1)),
      ...quad(v(0, 0, 0), v(0, 0, 1), v(1, 0, 1), v(1, 0, 0)),
      ...quad(v(0, 1, 0), v(1, 1, 0), v(1, 1, 1), v(0, 1, 1)),
      ...quad(v(0, 0, 0), v(0, 1, 0), v(0, 1, 1), v(0, 0, 1)),
      ...quad(v(1, 0, 0), v(1, 0, 1), v(1, 1, 1), v(1, 1, 0)),
    ];
    const { positions, corners } = soup(triangles);
    const segments = inkSegments(positions, corners);
    expect(segments.length / 6).toBe(12);
  });

  it('leaves a seam between coplanar pieces uninked and lifts lines off their face', () => {
    // Two unit squares side by side on the ground (y up), sharing an edge: six outline edges. Wound
    // so their normals face up.
    const squares = [
      [[0, 0, 0], [1, 0, 1], [1, 0, 0]], [[0, 0, 0], [0, 0, 1], [1, 0, 1]],
      [[1, 0, 0], [2, 0, 1], [2, 0, 0]], [[1, 0, 0], [1, 0, 1], [2, 0, 1]],
    ] as [number, number, number][][];
    const { positions, corners } = soup(squares);
    const segments = inkSegments(positions, corners);
    expect(segments.length / 6).toBe(6);
    // Every point lifted by the stated 25 mm along the faces' normal, which is up.
    for (let at = 1; at < segments.length; at += 3) expect(segments[at]).toBeCloseTo(INK_OPTIONS.liftM, 6);
    const short = inkSegments(positions, corners, { ...INK_OPTIONS, maxLengthM: 0.999 });
    expect(short).toHaveLength(0);
  });

  it('gives every point of a line the normal it is lifted along', () => {
    const squares = [
      [[0, 0, 0], [1, 0, 1], [1, 0, 0]], [[0, 0, 0], [0, 0, 1], [1, 0, 1]],
      [[1, 0, 0], [2, 0, 1], [2, 0, 0]], [[1, 0, 0], [1, 0, 1], [2, 0, 1]],
    ] as [number, number, number][][];
    const { positions, corners } = soup(squares);
    const normals: number[] = [];
    const segments = inkSegments(positions, corners, INK_OPTIONS, normals);
    expect(normals).toHaveLength(segments.length);
    for (let at = 0; at < normals.length; at += 3) {
      expect(normals[at]).toBeCloseTo(0, 9);
      expect(normals[at + 1]).toBeCloseTo(1, 9);
      expect(normals[at + 2]).toBeCloseTo(0, 9);
    }
  });

  it('draws its lines with the normal the unlit material\'s shader declares', () => {
    const { app } = scene();
    const material = new pc.StandardMaterial();
    const box = new pc.Entity('generated-tile:box');
    box.addComponent('render', { meshInstances: [new pc.MeshInstance(pc.Mesh.fromGeometry(app.graphicsDevice, new pc.BoxGeometry()), material)] });
    app.root.addChild(box);
    const ink = attachTileInk(app.graphicsDevice, app.root, [0, 0, 0]);
    expect(ink.segments).toBe(12);
    const drawn = (box.findByName('generated-tile:ink') as pc.Entity).render!.meshInstances[0]!.mesh;
    const positions: number[] = [];
    const normals: number[] = [];
    drawn.getPositions(positions);
    drawn.getNormals(normals);
    expect(normals).toHaveLength(positions.length);
    ink.dispose();
    app.destroy();
  });
});

function scene(width = 320, height = 200): { app: pc.AppBase; camera: pc.Entity; environmentRoot: pc.Entity } {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
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

describe('the environment a render look builds', () => {
  it('sets fog, sky, sun and the camera frame\'s finish from the look, and puts back what it changed', () => {
    const { app, camera } = scene();
    const before = { type: app.scene.fog.type, density: app.scene.fog.density, skybox: app.scene.skybox, atlas: app.scene.envAtlas };
    const environment = applyTileEnvironment(app, camera, LOOK);
    expect(app.scene.fog.type).toBe(pc.FOG_EXP2);
    expect(app.scene.fog.density).toBe(0.001);
    expect(app.scene.skybox?.format).toBe(pc.PIXELFORMAT_RGBA16F);
    expect(app.scene.skybox?.width).toBe(64);
    // The null device has no soft shadows, so the light falls back; the mapping is held below.
    expect(environment.sun.light!.shadowResolution).toBe(4096);
    expect(environment.sun.light!.numCascades).toBe(4);
    const frame = environment.frame!;
    expect(frame.bloom.intensity).toBe(0.02);
    expect(frame.bloom.blurLevel).toBe(12);
    expect(frame.grading.enabled).toBe(true);
    expect(frame.grading.saturation).toBe(1.1);
    expect(frame.colorEnhance.vibrance).toBe(0.15);
    expect(frame.vignette.intensity).toBe(0.25);
    expect(frame.taa.enabled).toBe(true);
    expect(frame.rendering.toneMapping).toBe(pc.TONEMAP_NEUTRAL);
    const ground = app.root.findByName('generated-tile:edge-ground') as pc.Entity | null;
    expect(ground).toBe(environment.ground);
    expect(ground!.getPosition().y).toBeCloseTo(-0.6, 6);
    environment.dispose();
    expect(app.root.findByName('generated-tile:edge-ground')).toBeNull();
    expect(app.scene.fog.type).toBe(before.type);
    expect(app.scene.fog.density).toBe(before.density);
    expect(app.scene.skybox).toBe(before.skybox);
    expect(app.scene.envAtlas).toBe(before.atlas);
  });

  it('maps each shadow filter to the engine\'s own type', () => {
    expect(RENDER_SHADOW_TYPES).toEqual({ pcf1: pc.SHADOW_PCF1_32F, pcf3: pc.SHADOW_PCF3_32F, pcf5: pc.SHADOW_PCF5_32F, pcss: pc.SHADOW_PCSS_32F });
    expect(new Set(Object.values(RENDER_SHADOW_TYPES)).size).toBe(4);
  });

  it('leaves the tile look\'s frame without bloom, grading or vignette', () => {
    const { app, camera } = scene();
    const environment = applyTileEnvironment(app, camera, TILE_LOOK_V1);
    const frame = environment.frame!;
    expect(frame.bloom.intensity).toBe(0);
    expect(frame.grading.enabled).toBe(false);
    expect(frame.vignette.intensity).toBe(0);
    expect(frame.taa.enabled).toBe(false);
    expect(app.scene.skybox?.format).toBe(pc.PIXELFORMAT_RGBA8);
    expect(environment.ground).toBeNull();
    environment.dispose();
  });
});

describe('a tile drawn with a render look', () => {
  const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
  const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
  const subtle = webcrypto.subtle as unknown as TextureSetDigest;
  const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
  const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };
  let baked: Uint8Array;
  beforeAll(async () => {
    baked = (await bakeTile(new Uint8Array(readFileSync(FIXTURE)), sha256)).container;
  }, 60_000);

  it('draws with a render look, inks what it drew, and removes everything again', async () => {
    const tile = await loadGeneratedTile({ name: 'tile-conformance', bytes: baked, manifest, fetchSet: noSets, digest: subtle, look: validateRenderLook(LOOK) });
    expect(tile.look).toEqual(LOOK);
    const { app, camera, environmentRoot } = scene();
    const attachment = tile.attach({ app, environmentRoot, camera });
    expect(attachment.metrics.lookId).toBe(RENDER_LOOK_ID);
    expect(app.root.findByName('generated-tile:edge-ground')).not.toBeNull();
    const ink = attachTileInk(app.graphicsDevice, environmentRoot, LOOK.shading.ink!);
    expect(ink.segments).toBeGreaterThan(0);
    const lines = (environmentRoot.findByName('generated-tile:ink') as pc.Entity).render!.meshInstances[0]!.mesh;
    expect(lines.primitive[0]!.type).toBe(pc.PRIMITIVE_LINES);
    ink.dispose();
    expect(environmentRoot.findByName('generated-tile:ink')).toBeNull();
    attachment.dispose();
    expect(app.root.findByName('generated-tile:edge-ground')).toBeNull();
  }, 60_000);
});

describe('the texture sets a render look draws', () => {
  // Relative to web/, where the suite runs.
  const textures = '../assets/textures/';
  const manifest = parseTextureSetManifest(new Uint8Array(readFileSync(`${textures}manifest.json`)));
  const library = (look: Parameters<typeof applyTileEnvironment>[2]) => new TileTextureLibrary(
    new pc.NullGraphicsDevice(document.createElement('canvas')), look, manifest,
    async (entry) => new Uint8Array(readFileSync(`${textures}${textureSetBlobPath(entry)}`)),
    webcrypto.subtle as unknown as TextureSetDigest,
  );
  const lambert = (material: pc.Material) => material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('lightDiffuseLambertPS');

  it('take the look\'s shading model, all but glass', async () => {
    const styled = library(validateRenderLook(LOOK));
    const kerb = await styled.resolve('cc0.kerb-stone');
    const glass = await styled.resolve('cc0.float-glazing');
    expect(kerb.state === 'available' && lambert(kerb.material)).toBe(true);
    expect(glass.state === 'available' && lambert(glass.material)).toBe(false);
    styled.destroy();
    const plain = library(TILE_LOOK_V1);
    const kerbPlain = await plain.resolve('cc0.kerb-stone');
    expect(kerbPlain.state === 'available' && lambert(kerbPlain.material)).toBe(false);
    plain.destroy();
  }, 60_000);
});
