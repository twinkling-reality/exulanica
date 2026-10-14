// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { hazeEndChunk } from '../src/playcanvas/generated-tile/aerial-haze.js';
import { applyTileEnvironment } from '../src/playcanvas/generated-tile/environment.js';
import { TileLookError, validateRenderLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import { WaterRipples } from '../src/playcanvas/style-pack/water-material.js';

/*
 * The optional finish of a render look: haze and a water finish. Each is carried
 * only when a pack states it, so a look from a pack written before them is unchanged, and a water
 * material with no finish keeps the shader text it had.
 */

interface Case { readonly name: string; readonly manifest: StylePackManifest }
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as { cases: Case[] };
const caseNamed = (name: string): StylePackManifest => {
  const found = CASES.cases.find((c) => c.name === name);
  if (found === undefined) throw new Error(`no case ${name}`);
  return found.manifest;
};
const PLAIN = caseNamed('a complete pack with no base');
const FINISHED = caseNamed('a preset with haze and a pack with a water finish');
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

describe('a render look from a pack that states no finish', () => {
  it('carries no haze or water at all', () => {
    const look = lookOf(PLAIN);
    expect('haze' in look).toBe(false);
    expect('water' in look).toBe(false);
  });
});

describe('a render look from a pack that states a finish', () => {
  it('converts the pack\'s whole numbers to the look\'s units', () => {
    const look = lookOf(FINISHED);
    expect(look.haze).toEqual({ density: 0.0006, falloff: 0.001, baseM: -2, maxDepth: 3, colour: null });
    expect(look.water?.absorption).toEqual([0.38, 0.075, 0.06]);
    expect(look.water?.depthScaleM).toBe(6);
    expect(look.water?.foamWidthM).toBe(0.35);
    expect(look.water?.reflection).toBe(1);
    // Colours arrive linear: sRGB byte 154 is about 0.32 in linear light.
    expect(look.water!.shallow[1]).toBeCloseTo(0.3231, 3);
  });

  it('refuses a finish out of range, naming where', () => {
    const look = structuredClone(lookOf(FINISHED)) as unknown as Record<string, Record<string, unknown>>;
    look['haze']!['density'] = 0.01;
    expect(refused(look)).toBe('haze.density: must be within 0.000001 to 0.006');
    const water = structuredClone(lookOf(FINISHED)) as unknown as Record<string, Record<string, unknown>>;
    water['water']!['absorption'] = [0.38, 6, 0.06];
    expect(refused(water)).toBe('water.absorption: must be three numbers within 0 to 5');
  });
});

describe('the haze end chunk', () => {
  const END = [
    '    gl_FragColor.rgb = combineColor(litArgs_albedo, litArgs_sheen_specularity, litArgs_clearcoat_specularity);',
    '    gl_FragColor.rgb += litArgs_emission;',
    '    gl_FragColor.rgb = addFog(gl_FragColor.rgb);',
    '    gl_FragColor.rgb = toneMap(gl_FragColor.rgb);',
    '    gl_FragColor.rgb = gammaCorrectOutput(gl_FragColor.rgb);',
  ].join('\n');

  it('puts one guarded block before tone mapping and leaves every other line as it was', () => {
    const end = hazeEndChunk(END)!;
    expect(end.split('if (exuHaze.w > 0.0)').length).toBe(2);
    expect(end.indexOf('exuHaze.w > 0.0')).toBeLessThan(end.indexOf('toneMap('));
    // What was inserted starts where tone mapping used to and ends where it now is.
    const from = END.indexOf('gl_FragColor.rgb = toneMap(');
    const to = end.indexOf('gl_FragColor.rgb = toneMap(');
    expect(end.slice(0, from) + end.slice(to)).toBe(END);
    expect(end.slice(from, to)).toContain('exuHaze');
  });

  it('declines an end chunk with no tone mapping line', () => {
    expect(hazeEndChunk('gl_FragColor.rgb = vec3(1.0);')).toBeNull();
  });
});

describe('a water material', () => {
  const app = { on() {}, off() {}, graphicsDevice: { isWebGPU: false } } as unknown as pc.AppBase;
  const normalOf = (finish: Parameters<WaterRipples['add']>[1], options?: Parameters<WaterRipples['add']>[2]) => {
    const material = new pc.StandardMaterial();
    new WaterRipples(app).add(material, finish, options);
    return { material, glsl: material.getShaderChunks(pc.SHADERLANGUAGE_GLSL) };
  };

  it('with no finish keeps its ripples, declaring its own clock, and nothing else', () => {
    const { material, glsl } = normalOf(null);
    expect(glsl.get('normalMapPS')).toMatch(/^\nuniform float exuWaterTime;\n[\s\S]*void getNormal\(\) \{/);
    expect(glsl.has('opacityPS')).toBe(false);
    expect(glsl.has('emissivePS')).toBe(false);
    expect(material.blendType).toBe(pc.BLEND_NONE);
  });

  it('ripples alike with a finish or without one: the finish changes only how the clock is declared', () => {
    const plain = normalOf(null).glsl.get('normalMapPS') as string;
    const finished = normalOf(lookOf(FINISHED).water!).glsl.get('normalMapPS') as string;
    expect(finished).not.toBe(plain);
    expect(finished.replace('#ifndef EXU_WATER_TIME\n#define EXU_WATER_TIME\nuniform float exuWaterTime;\n#endif', 'uniform float exuWaterTime;')).toBe(plain);
  });

  it('gives the depth finish without ripples where asked, as a sea or a lake seen from afar', () => {
    const { glsl } = normalOf(lookOf(FINISHED).water!, { ripples: false });
    expect(glsl.has('normalMapPS')).toBe(false);
    expect(glsl.get('opacityPS')).toContain('getLinearScreenDepth');
  });

  it('with a finish blends over the scene by its depth and never reads the scene colour', () => {
    const material = new pc.StandardMaterial();
    new WaterRipples(app).add(material, lookOf(FINISHED).water!);
    const glsl = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    expect(glsl.get('opacityPS')).toContain('getLinearScreenDepth');
    expect([...glsl.values()].join('\n')).not.toContain('uSceneColorMap');
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    expect(material.depthWrite).toBe(false);
    // The clock is declared once, guarded, whichever chunk comes first.
    expect(glsl.get('normalMapPS')).toContain('#ifndef EXU_WATER_TIME');
    expect(glsl.get('opacityPS')).toContain('#ifndef EXU_WATER_TIME');
  });

  it('on a WebGPU device keeps its ripples alone', () => {
    const material = new pc.StandardMaterial();
    const gpu = { on() {}, off() {}, graphicsDevice: { isWebGPU: true } } as unknown as pc.AppBase;
    new WaterRipples(gpu).add(material, lookOf(FINISHED).water!);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('opacityPS')).toBe(false);
    expect(material.blendType).toBe(pc.BLEND_NONE);
  });
});

describe('the environment a look with haze builds', () => {
  const scene = (): { app: pc.AppBase; camera: pc.Entity } => {
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
    return { app, camera };
  };

  it('draws the haze in place of the fog and puts the fog back', () => {
    const { app, camera } = scene();
    const before = app.scene.fog.type;
    const environment = applyTileEnvironment(app, camera, lookOf(FINISHED));
    expect(app.scene.fog.type).toBe(pc.FOG_NONE);
    expect(pc.ShaderChunks.get(app.graphicsDevice, pc.SHADERLANGUAGE_GLSL).get('endPS')).toContain('exuHaze');
    expect(app.graphicsDevice.scope.resolve('exuHaze').getValue()).toEqual([0.0006, 0.001, -2, 3]);
    environment.dispose();
    expect(app.scene.fog.type).toBe(before);
    expect(app.graphicsDevice.scope.resolve('exuHaze').getValue()[3]).toBe(0);
  });

  it('leaves the fog and the end chunk alone for a look with no haze', () => {
    const { app, camera } = scene();
    const end = pc.ShaderChunks.get(app.graphicsDevice, pc.SHADERLANGUAGE_GLSL).get('endPS');
    const environment = applyTileEnvironment(app, camera, lookOf(PLAIN));
    expect(app.scene.fog.type).not.toBe(pc.FOG_NONE);
    expect(pc.ShaderChunks.get(app.graphicsDevice, pc.SHADERLANGUAGE_GLSL).get('endPS')).toBe(end);
    environment.dispose();
  });
});
