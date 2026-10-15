// @vitest-environment happy-dom
/**
 * A look's wind: read from its pack's preset, held to its shape as a whole render look, and worked
 * into the engine's transform chunk of each swaying material once, its time kept while it sways.
 *
 * The pack is the shared case that states one (`assets/style-packs/manifest-cases.v1.json`).
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { TileLookError, validateRenderLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import { PlantWind, withWind } from '../src/playcanvas/style-pack/wind.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { cases: { name: string; manifest: StylePackManifest }[] };
const caseNamed = (name: string): StylePackManifest => CASES.cases.find((one) => one.name === name)!.manifest;
const WINDY = caseNamed('a pack growing grass and flowers on its lawns in a wind');
const STILL = caseNamed('a complete pack with no base');
const lookOf = (pack: StylePackManifest) => renderLookOfPreset(pack.light!.presets[pack.light!.default_preset]!, pack.shading!, pack.edge, 1, pack.water);

const refused = (value: unknown): string => {
  try {
    validateRenderLook(value);
  } catch (error) {
    if (error instanceof TileLookError) return error.message;
    throw error;
  }
  throw new Error('the look was accepted');
};

function application(webgpu = false): pc.AppBase {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  const device = new pc.NullGraphicsDevice(canvas);
  if (webgpu) Object.defineProperty(device, 'isWebGPU', { value: true });
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  return app;
}

/** A material's stated parameter's value. */
const parameter = (material: pc.StandardMaterial, name: string): unknown => (material.getParameter(name) as { data: unknown } | undefined)?.data;
const stockChunk = (app: pc.AppBase): string => pc.ShaderChunks.get(app.graphicsDevice, pc.SHADERLANGUAGE_GLSL).get('transformCoreVS') as string;

describe('a look\'s wind', () => {
  it('is the pack\'s preset wind in the look\'s units, and a pack that states none carries none', () => {
    const wind = lookOf(WINDY).wind!;
    expect(wind.direction).toBeCloseTo(Math.PI / 6, 6);
    expect([wind.swayM, wind.pace, wind.gustScaleM, wind.gustShare, wind.flutterM, wind.swayFamilies]).toEqual([0.12, 1.5, 24, 0.6, 0.015, ['plant']]);
    expect('wind' in lookOf(STILL)).toBe(false);
  });

  it('reads as a whole render look, and is refused out of range or with no family to sway, naming where', () => {
    const look = lookOf(WINDY);
    expect(validateRenderLook(look).wind).toEqual(look.wind);
    expect(refused({ ...look, wind: { ...look.wind!, swayM: 3 } })).toBe('wind.swayM: must be within 0 to 2');
    expect(refused({ ...look, wind: { ...look.wind!, swayFamilies: [] } })).toBe('wind.swayFamilies: must be a list of 1 to 8');
    expect(refused({ ...look, wind: { ...look.wind!, swayFamilies: ['Plant'] } })).toBe('wind.swayFamilies[0]: must be a key');
  });
});

describe('the wind\'s transform chunk', () => {
  it('wraps the engine\'s own local position once, keeping it under another name, and leaves every other line', () => {
    const stock = stockChunk(application());
    const windy = withWind(stock);
    expect(windy.split('vec3 getLocalPosition(vec3 vertexPosition) {').length).toBe(2);
    expect(windy).toContain('vec3 exuWindRestPosition(vec3 vertexPosition) {');
    expect(windy.replace('vec3 exuWindRestPosition(vec3 vertexPosition) {', 'vec3 getLocalPosition(vec3 vertexPosition) {').startsWith(stock)).toBe(true);
    expect(withWind(windy)).toBe(windy);
  });

  it('refuses a chunk with no local position to wrap', () => {
    expect(() => withWind('void main() {}')).toThrow(/no local position/);
  });
});

describe('the wind over a site', () => {
  it('sways a material by its piece\'s height, keeps its time while the app runs, and stops on dispose', () => {
    const app = application();
    const wind = new PlantWind(app, lookOf(WINDY).wind!);
    const material = new pc.StandardMaterial();
    expect(wind.add(material, 0.35)).toBe(true);
    expect(wind.add(material, 0.35)).toBe(false);
    expect([wind.animating, wind.materials]).toEqual([true, 1]);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('transformCoreVS')).toContain('exuWindRestPosition');
    expect(parameter(material, 'exuWindHeight')).toBe(0.35);
    expect((parameter(material, 'exuWind') as number[]).map((n) => Number(n.toFixed(4)))).toEqual([0.866, 0.5, 0.12, 1.5]);
    app.fire('update', 0.05);
    app.fire('update', 0.05);
    expect((parameter(material, 'exuWindGust') as number[]).map((n) => Number(n.toFixed(4)))).toEqual([0.0417, 0.6, 0.1, 0.015]);
    wind.dispose();
    app.fire('update', 0.05);
    expect((parameter(material, 'exuWindGust') as number[])[2]).toBeCloseTo(0.1, 6);
    expect(wind.add(new pc.StandardMaterial(), 1)).toBe(false);
  });

  it('sways nothing on WebGPU, where its working is not written', () => {
    const app = application(true);
    const wind = new PlantWind(app, lookOf(WINDY).wind!);
    const material = new pc.StandardMaterial();
    expect(wind.add(material, 1)).toBe(false);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('transformCoreVS')).toBeUndefined();
    expect(wind.animating).toBe(false);
  });
});
