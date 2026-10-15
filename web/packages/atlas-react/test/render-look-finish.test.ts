// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { StylePackManifest } from '@exulanica/atlas-core';
import { hazeEndChunk } from '../src/playcanvas/generated-tile/aerial-haze.js';
import { applyTileEnvironment } from '../src/playcanvas/generated-tile/environment.js';
import { TileLookError, validateRenderLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';
import { WATER_CONTACT_TAPS, WATER_RIPPLE_DEFAULTS, WaterRipples } from '../src/playcanvas/style-pack/water-material.js';

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
const SHARPENED = caseNamed('a stiff plant taking a share of its wind, in a sharpened frame');
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

describe('a render look\'s sharpness', () => {
  it('is the preset\'s in the look\'s units, absent where the preset states none, and read as a whole look within 0 to 1', () => {
    const look = lookOf(SHARPENED);
    expect(look.post.sharpness).toBe(1);
    expect('sharpness' in lookOf(PLAIN).post).toBe(false);
    expect(validateRenderLook(look).post.sharpness).toBe(1);
    expect(refused({ ...look, post: { ...look.post, sharpness: 1.5 } })).toBe('post.sharpness: must be within 0 to 1');
  });
});

describe('a render look\'s lit windows', () => {
  it('is the preset\'s share in the look\'s units, absent where the preset states none, and read as a whole look within 0 to 1', () => {
    const look = lookOf(caseNamed('a night light lighting its windows whatever its sun'));
    expect(look.litWindows).toBe(0.65);
    expect('litWindows' in lookOf(caseNamed('a pack drawing windows on its building walls'))).toBe(false);
    expect(validateRenderLook(look).litWindows).toBe(0.65);
    expect(refused({ ...look, litWindows: 1.5 })).toBe('litWindows: must be within 0 to 1');
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

  it('ripples as today where its look states no ripple, and as a look that states today\'s figures', () => {
    const finish = lookOf(FINISHED).water!;
    expect(finish.ripples).toBeUndefined();
    const stated = normalOf({ ...finish, ripples: WATER_RIPPLE_DEFAULTS }).glsl.get('normalMapPS');
    expect(normalOf(finish).glsl.get('normalMapPS')).toBe(stated);
  });

  it('ripples in a look\'s own octaves: as many as it states, at its cells, faded where it says', () => {
    const one = { octaves: [{ angle: 0, cellM: 4, tilt: 0.05, drift: [0.4, 0] as const }], fadeFrom: 0.2, fadeTo: 0.5 };
    const chunk = normalOf({ ...lookOf(FINISHED).water!, ripples: one }).glsl.get('normalMapPS') as string;
    expect(chunk).toContain('vec2 q0 = vec2(vPositionW.x * 0.2500');
    expect(chunk).not.toContain('q1');
    expect(chunk).toContain('smoothstep(0.2000, 0.5000');
  });

  it('reads as a whole render look with its own ripple and caustics, and refuses a fade that ends where it starts', () => {
    const base = lookOf(FINISHED);
    const ripples = { octaves: [{ angle: 0.6, cellM: 2.4, tilt: 0.07, drift: [0.24, 0.096] as const }], fadeFrom: 0.15, fadeTo: 0.4 };
    const caustics = { strength: 0.6, cellM: 1.5, pace: 0.8, reachM: 1.5 };
    expect(validateRenderLook({ ...base, water: { ...base.water!, ripples, caustics } }).water?.caustics).toEqual(caustics);
    expect(() => validateRenderLook({ ...base, water: { ...base.water!, ripples: { ...ripples, fadeTo: 0.15 } } })).toThrow(/fadeTo must lie beyond fadeFrom/);
  });

  it('gathers caustics under shallow water only where its look states them', () => {
    const finish = lookOf(FINISHED).water!;
    const strength = (water: typeof finish) => (normalOf(water).material.getParameter('exuWaterCaustics') as { data: Float32Array }).data[0];
    expect(strength(finish)).toBe(0);
    expect(strength({ ...finish, caustics: { strength: 0.6, cellM: 1.5, pace: 0.8, reachM: 1.2 } })).toBeCloseTo(0.6, 6);
    expect(normalOf(finish).glsl.get('opacityPS')).toContain('exuWaterCaustics.x > 0.0');
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

  it('sharpens the frame by the look\'s sharpness, and not at all for a look that states none', () => {
    const { app, camera } = scene();
    const sharpened = applyTileEnvironment(app, camera, lookOf(SHARPENED));
    expect(sharpened.frame?.rendering.sharpness).toBe(1);
    expect(sharpened.frame?.taa.enabled).toBe(true);
    sharpened.dispose();
    const plain = applyTileEnvironment(app, camera, lookOf(PLAIN));
    expect(plain.frame?.rendering.sharpness).toBe(0);
    plain.dispose();
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

describe('a water meeting what stands in it and lies under it', () => {
  const MET = caseNamed('a water finish meeting solids: wet, lit from above, shallow where faces turn up, foam on the sea');
  const world = (): { app: pc.AppBase; camera: pc.Entity } => {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 200;
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    return { app, camera };
  };
  const contactOf = (material: pc.StandardMaterial): number[] => Array.from((material.getParameter('exuWaterContact') as { data: Float32Array }).data);

  it('carries its contact into the render look in shares and metres, and reads as a whole render look', () => {
    const water = lookOf(MET).water!;
    expect(water.contact).toEqual({ wetKeep: 0.6, lightDown: 0.5, shallowFacing: 1, foamReachM: { 'water.sea': 2.5, 'water.lake': 1.2 } });
    expect(validateRenderLook(lookOf(MET)).water?.contact).toEqual(water.contact);
    expect('contact' in lookOf(FINISHED).water!).toBe(false);
  });

  it('refuses foam on a key that is no look role, more roles than it holds, a reach too far and a share above one', () => {
    const base = lookOf(MET);
    const contact = base.water!.contact!;
    const stating = (change: Partial<typeof contact>) => ({ ...base, water: { ...base.water!, contact: { ...contact, ...change } } });
    expect(refused(stating({ foamReachM: { sea: 2 } }))).toBe('water.contact.foamReachM: has "sea", not a look role');
    expect(refused(stating({ foamReachM: { 'water.sea': 6 } }))).toBe('water.contact.foamReachM.water.sea: must be within 0.1 to 5');
    const many = Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`water.w${i}`, 1]));
    expect(refused(stating({ foamReachM: many }))).toBe('water.contact.foamReachM: must hold at most 16 entries');
    expect(refused(stating({ wetKeep: 1.2 }))).toBe('water.contact.wetKeep: must be within 0 to 1');
  });

  it('meets solids as today where its look states no contact, and where no eye places the depth map in the world', () => {
    const { app, camera } = world();
    const today = new pc.StandardMaterial();
    new WaterRipples(app, camera).add(today, lookOf(FINISHED).water!, { role: 'water.sea' });
    const blind = new pc.StandardMaterial();
    new WaterRipples(app).add(blind, lookOf(MET).water!, { role: 'water.sea' });
    const chunk = today.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('opacityPS') as string;
    expect(chunk).not.toContain('exuWaterContact');
    expect(blind.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('opacityPS')).toBe(chunk);
    expect(blind.getParameter('exuWaterContact')).toBeUndefined();
  });

  it('with an eye: darkens what lies under, keeps the shallow colour for faces turned up, and foams for the roles it names', () => {
    const { app, camera } = world();
    const ripples = new WaterRipples(app, camera);
    const water = (role: string | null): pc.StandardMaterial => {
      const material = new pc.StandardMaterial();
      ripples.add(material, lookOf(MET).water!, { role });
      return material;
    };
    const sea = water('water.sea');
    const chunk = sea.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('opacityPS') as string;
    expect(chunk).toContain('float shown = through * dot(exp(-exuWaterAbsorb * depth * exuWaterContact.y)');
    expect(chunk).toContain('exp(-depth / exuWaterFinish.x) * mix(1.0, facingUp, exuWaterContact.w)');
    expect(chunk).toContain(`for (int i = 0; i < ${WATER_CONTACT_TAPS}; i++)`);
    expect(chunk).toContain('gathered * shown * (1.0 - foam)');
    expect(chunk).not.toContain('dAlpha = 1.0 - through * (1.0 - foam);');
    const [wet, down, reach, facing] = contactOf(sea);
    expect([wet, down, reach, facing].map((n) => Math.round(n! * 1000) / 1000)).toEqual([0.6, 0.5, 2.5, 1]);
    expect(contactOf(water('water.pond'))[2]).toBe(0);
    expect(contactOf(water(null))[2]).toBe(0);
  });

  it('places the depth map in the world from the eye\'s camera before each frame, and stops when let go', () => {
    const { app, camera } = world();
    camera.setPosition(3, 4, 5);
    camera.setEulerAngles(-20, 30, 0);
    const ripples = new WaterRipples(app, camera);
    ripples.add(new pc.StandardMaterial(), lookOf(MET).water!, { role: 'water.sea' });
    app.fire('prerender');
    const scope = app.graphicsDevice.scope;
    const expected = new pc.Mat4().mul2(camera.camera!.projectionMatrix, camera.camera!.viewMatrix).invert();
    Array.from(scope.resolve('exuWaterInverse').getValue() as Float32Array).forEach((n, i) => expect(n).toBeCloseTo(expected.data[i]!, 5));
    expect(scope.resolve('exuWaterYScale').getValue()).toBeCloseTo(camera.camera!.projectionMatrix.data[5]!, 6);
    expect(scope.resolve('exuWaterForward').getValue()).toEqual([camera.forward.x, camera.forward.y, camera.forward.z]);
    ripples.dispose();
    scope.resolve('exuWaterYScale').setValue(-1);
    app.fire('prerender');
    expect(scope.resolve('exuWaterYScale').getValue()).toBe(-1);
  });
});
