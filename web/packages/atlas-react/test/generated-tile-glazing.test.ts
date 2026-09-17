// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, type TextureSetDigest } from '@exulanica/atlas-core';
import { applyTileEnvironment } from '../src/playcanvas/generated-tile/environment.js';
import { GLAZING_FRESNEL_CHUNK, GLAZING_FRESNEL_GLSL, GLAZING_FRESNEL_WGSL, glazingReflectance } from '../src/playcanvas/generated-tile/glazing-fresnel.js';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import {
  TileTextureLibrary,
  castsShadow,
  transmissionRoughnessTexels,
  undrawnClassReason,
} from '../src/playcanvas/generated-tile/texture-materials.js';

const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const CONFORMANCE = 'packages/loom-texture/test/conformance/';
const fixtures = parseTextureSetManifest(new Uint8Array(readFileSync(`${CONFORMANCE}manifest.json`)));

function app(width = 320, height = 200): { readonly app: pc.AppBase; readonly camera: pc.Entity; readonly device: pc.GraphicsDevice } {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const device = new pc.NullGraphicsDevice(canvas);
  const value = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  value.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  value.root.addChild(camera);
  return { app: value, camera, device };
}

describe('a glazing set as a material', () => {
  it('reflects by its index of refraction, transmits what is drawn behind it by the transmission map, and writes no depth', async () => {
    const { device } = app();
    const textures = new TileTextureLibrary(device, TILE_LOOK_V1, fixtures, async (entry) =>
      new Uint8Array(readFileSync(`${CONFORMANCE}${entry.setId}.ltex`)), subtle);
    const resolution = await textures.resolve('fixture.glazing');
    if (resolution.state !== 'available' || resolution.set.classParameters.materialClass !== 'glazing') throw new Error('the glazing fixture draws');
    const parameters = resolution.set.classParameters;
    const material = resolution.material as pc.StandardMaterial & Record<string, unknown>;
    expect(undrawnClassReason(resolution.set)).toBeNull();
    // metalness 0: reflectance at normal incidence is ((n - 1) / (n + 1))^2, from 1 / refractionIndex.
    expect(material.metalness).toBe(0);
    expect(material.metalnessMap).toBeNull();
    expect(material.refractionIndex).toBeCloseTo(1_000_000 / parameters.iorMillionths, 12);
    const n = 1 / (material.refractionIndex as number);
    expect(((n - 1) / (n + 1)) ** 2).toBeCloseTo(0.04, 12);
    // Transmission from the red channel, roughness from the green, of the same map.
    expect(material['refraction']).toBe(1);
    expect(material['refractionMap']).toBe(material.glossMap);
    expect(material['refractionMapChannel']).toBe('r');
    expect(material.glossMapChannel).toBe('g');
    expect(material.glossInvert).toBe(true);
    expect(material['useDynamicRefraction']).toBe(true);
    expect(material['thickness']).toBe(0);
    // The base colour tints transmitted light and colours the film.
    expect(material.diffuseMap).not.toBeNull();
    expect(material.aoMap).toBeNull();
    // Drawn after the opaque scene, depth tested, no depth write, one side.
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    expect(material.depthWrite).toBe(false);
    expect(material.depthTest).toBe(true);
    expect(material.cull).toBe(pc.CULLFACE_BACK);
    expect(castsShadow(resolution.set)).toBe(false);
    // Reflectance rises with angle: the engine's Schlick term is replaced for this material only.
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get(GLAZING_FRESNEL_CHUNK)).toBe(GLAZING_FRESNEL_GLSL);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).get(GLAZING_FRESNEL_CHUNK)).toBe(GLAZING_FRESNEL_WGSL);
    const opaque = await textures.resolve('fixture.opaque');
    if (opaque.state !== 'available') throw new Error('the opaque fixture draws');
    expect(opaque.material.hasShaderChunks).toBe(false);
    textures.destroy();
  });

  it('reflects ((n - 1) / (n + 1))^2 face on, rising to the gloss at grazing incidence', () => {
    const f0 = ((1.5 - 1) / (1.5 + 1)) ** 2;
    expect(glazingReflectance(1, 0.98, f0)).toBeCloseTo(0.04, 12);
    expect(glazingReflectance(0, 0.98, f0)).toBeCloseTo(0.98, 12);
    expect(glazingReflectance(Math.cos((70 * Math.PI) / 180), 0.98, f0)).toBeGreaterThan(0.15);
    // A rough film reflects less at grazing incidence, never less than face on.
    expect(glazingReflectance(0, 0.2, f0)).toBeCloseTo(0.2, 12);
    expect(glazingReflectance(0, 0.01, f0)).toBeCloseTo(f0, 12);
    // What the engine's own term gives the same glass: 0.04 at every angle.
    const engine = (cosTheta: number, gloss: number): number => f0 + (Math.max(gloss * gloss * f0, f0) - f0) * (1 - cosTheta) ** 5;
    expect(engine(0, 0.98)).toBeCloseTo(0.04, 12);
  });

  it('lays transmission in red and roughness in green', () => {
    expect([...transmissionRoughnessTexels(new Uint8Array([255, 5, 128, 200]))]).toEqual([255, 5, 0, 255, 128, 200, 0, 255]);
  });

  it('keeps shadows for every class but glazing', () => {
    for (const materialClass of ['opaque', 'cutout', 'decal'] as const) expect(castsShadow({ materialClass })).toBe(true);
    expect(castsShadow({ materialClass: 'glazing' })).toBe(false);
  });
});

describe('the scene colour copy glazing needs', () => {
  it('is off until glazing asks for it, and holds for a camera frame created later', () => {
    const now = app();
    const environment = applyTileEnvironment(now.app, now.camera, TILE_LOOK_V1);
    expect(environment.frame!.rendering.sceneColorMap).toBe(false);
    environment.requestSceneColor();
    expect(environment.frame!.rendering.sceneColorMap).toBe(true);
    environment.dispose();

    const later = app(0, 0);
    const deferred = applyTileEnvironment(later.app, later.camera, TILE_LOOK_V1);
    deferred.requestSceneColor();
    expect(deferred.frame).toBeNull();
    later.device.setResolution(640, 480);
    expect(deferred.frame!.rendering.sceneColorMap).toBe(true);
    deferred.dispose();
  });
});
