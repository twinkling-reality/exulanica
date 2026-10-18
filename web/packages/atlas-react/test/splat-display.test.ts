// @vitest-environment happy-dom
// The painted splat drawn after tone mapping (splat-display.ts): its own layer right after the
// Immediate layer, which a camera frame's after pass draws; the splats moved there only while the
// camera's frame leaves the scene's depth, and back in the scene otherwise; the display layer's splat
// material given an output with no tone curve, a test against the scene's depth and a whole-splat
// test in the vertex stage (perspective cameras only), and no other layer's; and dispose giving every splat its own layers back.
// Materials and layers are compared by identity as booleans: a failed match then reports at once,
// where a diff of two engine objects would print the whole device.
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  SPLAT_DISPLAY, SPLAT_DISPLAY_BIAS_UNIFORM, SPLAT_DISPLAY_CULL_UNIFORM, SPLAT_DISPLAY_LAYER, splatsAfterToneMapping,
} from '../src/playcanvas/splat-display.js';

function nullApp() {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.GSplatComponentSystem];
  app.init(options);
  return app;
}

function scene() {
  const app = nullApp();
  const eye = new pc.Entity('eye', app);
  eye.addComponent('camera');
  app.root.addChild(eye);
  const painted = new pc.Entity('painted', app);
  app.root.addChild(painted);
  const splat = new pc.Entity('splat', app);
  splat.addComponent('gsplat', {});
  painted.addChild(splat);
  return { app, camera: eye.camera!, painted, splat: splat.gsplat! };
}

/** Gives `camera` a frame that draws a depth prepass, or one that draws none. */
function frame(camera: pc.CameraComponent, prepass: boolean): void {
  camera.framePasses = [{ prePass: prepass ? {} : null } as unknown as pc.RenderPass];
}

/** Each sublayer's name, O for opaque and T for transparent, in draw order. */
function order(app: pc.AppBase): string[] {
  const { layerList, subLayerList } = app.scene.layers;
  return layerList.map((layer, index) => `${layer.name}${subLayerList[index] ? 'T' : 'O'}`);
}

/** The engine fires this when it makes the splat material for a camera and layer. */
function materialCreated(app: pc.AppBase, material: pc.Material, camera: pc.CameraComponent, layer: pc.Layer): void {
  (app.systems.gsplat as unknown as pc.EventHandler).fire('material:created', material, camera.camera, layer);
}

describe('the painted splat drawn after tone mapping', () => {
  it('has its own layer right after the Immediate layer, drawn by the camera, before the interface', () => {
    const { app, camera, painted } = scene();
    splatsAfterToneMapping(painted, camera);
    const names = order(app);
    const immediate = names.indexOf('ImmediateT');
    expect(names.slice(immediate + 1, immediate + 3)).toEqual([`${SPLAT_DISPLAY_LAYER}O`, `${SPLAT_DISPLAY_LAYER}T`]);
    expect(names.indexOf('UIT')).toBeGreaterThan(immediate + 2);
    const layer = app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    expect(camera.layers.includes(layer.id)).toBe(true);
  });

  it('moves the splats onto it only while the camera\'s frame leaves the scene\'s depth', () => {
    const { app, camera, painted, splat } = scene();
    splat.layers = [pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE];
    const display = splatsAfterToneMapping(painted, camera);
    const layer = app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    expect(display.splats).toBe(1);
    // No frame: the splats stay in the scene, on their own layers.
    app.fire('prerender');
    expect(display.active).toBe(false);
    expect(splat.layers).toEqual([pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE]);
    // A frame with a depth prepass: on the display layer alone.
    frame(camera, true);
    app.fire('prerender');
    expect(display.active).toBe(true);
    expect(splat.layers).toEqual([layer.id]);
    // A frame that draws no prepass leaves no depth to test against: back in the scene.
    frame(camera, false);
    app.fire('prerender');
    expect(display.active).toBe(false);
    expect(splat.layers).toEqual([pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE]);
  });

  it('stays in the scene where the device cannot render float depth or runs WebGPU', () => {
    for (const device of [{ textureFloatRenderable: false }, { isWebGPU: true }]) {
      const { app, camera, painted, splat } = scene();
      Object.defineProperties(app.graphicsDevice, Object.fromEntries(Object.entries(device).map(([key, value]) => [key, { value, configurable: true }])));
      const display = splatsAfterToneMapping(painted, camera);
      frame(camera, true);
      app.fire('prerender');
      expect(display.active).toBe(false);
      expect(splat.layers).toEqual([pc.LAYERID_WORLD]);
    }
  });

  it('takes in splats added since when refreshed', () => {
    const { app, camera, painted } = scene();
    const display = splatsAfterToneMapping(painted, camera);
    frame(camera, true);
    app.fire('prerender');
    const later = new pc.Entity('later', app);
    later.addComponent('gsplat', {});
    painted.addChild(later);
    expect(later.gsplat!.layers).toEqual([pc.LAYERID_WORLD]);
    display.refresh();
    expect(display.splats).toBe(2);
    expect(later.gsplat!.layers).toEqual([app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!.id]);
  });

  it('gives the display layer\'s splat material no tone curve and a test against the scene\'s depth, and no other layer\'s', () => {
    const { app, camera, painted } = scene();
    splatsAfterToneMapping(painted, camera, { look: { ...SPLAT_DISPLAY, depthBiasMetres: 0.07, depthBiasShare: 0.004 } });
    const layer = app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    const dressed = new pc.ShaderMaterial();
    materialCreated(app, dressed, camera, layer);
    const chunks = dressed.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    const output = chunks.get('gsplatOutputVS')!;
    expect(output.includes('prepareOutputFromGamma')).toBe(true);
    expect(output.includes('toneMap(')).toBe(false);
    expect(output.includes('vSplatViewZ = depth')).toBe(true);
    const test = chunks.get('gsplatModifyPS')!;
    expect(test.includes('uSceneDepthMap')).toBe(true);
    expect(test.includes('discard')).toBe(true);
    expect(Array.from((dressed.getParameter(SPLAT_DISPLAY_BIAS_UNIFORM) as { data: number[] }).data)).toEqual([0.07, 0.004]);
    // The world layer's splat material keeps the engine's code.
    const world = new pc.ShaderMaterial();
    materialCreated(app, world, camera, app.scene.layers.getLayerById(pc.LAYERID_WORLD)!);
    expect(world.hasShaderChunks && world.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('gsplatModifyPS') !== undefined).toBe(false);
  });

  it('drops whole splats behind the scene in the vertex stage, under a perspective camera only', () => {
    const { app, camera, painted } = scene();
    const layer = () => app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    const cull = (material: pc.Material) => Array.from((material.getParameter(SPLAT_DISPLAY_CULL_UNIFORM) as { data: number[] }).data);
    const display = splatsAfterToneMapping(painted, camera, { look: { ...SPLAT_DISPLAY, vertexCullMaxPixels: 30 } });
    const dressed = new pc.ShaderMaterial();
    materialCreated(app, dressed, camera, layer());
    const vertex = dressed.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('gsplatModifyVS')!;
    // The engine's vertex stage calls all three; the splat's alpha set to zero is what it refuses.
    for (const hook of ['void modifySplatCenter(', 'void modifySplatRotationScale(', 'void modifySplatColor(vec3 center']) {
      expect(vertex.includes(hook)).toBe(true);
    }
    expect(vertex.includes('uSceneDepthMap')).toBe(true);
    expect(vertex.includes('color.a = 0.0')).toBe(true);
    expect(cull(dressed)).toEqual([1, 30]);
    // An orthographic camera: off, set again before the next frame.
    camera.projection = pc.PROJECTION_ORTHOGRAPHIC;
    frame(camera, true);
    (app.systems.gsplat as unknown as { getMaterial: unknown }).getMaterial = () => dressed;
    app.fire('prerender');
    expect(cull(dressed)).toEqual([0, 30]);
    display.dispose();
    // Turned off by the look.
    camera.projection = pc.PROJECTION_PERSPECTIVE;
    splatsAfterToneMapping(painted, camera, { look: { ...SPLAT_DISPLAY, vertexCull: false } });
    const off = new pc.ShaderMaterial();
    materialCreated(app, off, camera, layer());
    expect(cull(off)[0]).toBe(0);
    // The world layer's splat material keeps the engine's vertex code.
    const world = new pc.ShaderMaterial();
    materialCreated(app, world, camera, app.scene.layers.getLayerById(pc.LAYERID_WORLD)!);
    expect(world.hasShaderChunks && world.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('gsplatModifyVS') !== undefined).toBe(false);
  });

  it('takes fog only when asked, as the engine adds it, without the tone curve', () => {
    const { app, camera, painted } = scene();
    const layer = () => app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    const without = splatsAfterToneMapping(painted, camera);
    const plain = new pc.ShaderMaterial();
    materialCreated(app, plain, camera, layer());
    expect(plain.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('gsplatOutputVS')!.includes('#define GSPLAT_FOG')).toBe(false);
    without.dispose();
    splatsAfterToneMapping(painted, camera, { look: { ...SPLAT_DISPLAY, fog: true } });
    const fogged = new pc.ShaderMaterial();
    materialCreated(app, fogged, camera, layer());
    const output = fogged.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('gsplatOutputVS')!;
    expect(output.includes('#define GSPLAT_FOG')).toBe(true);
    expect(output.includes('toneMap(')).toBe(false);
  });

  it('gives every splat its own layers back when disposed, and removes the layer once no one uses it', () => {
    const { app, camera, painted, splat } = scene();
    splat.layers = [pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE];
    const first = splatsAfterToneMapping(painted, camera);
    const second = splatsAfterToneMapping(new pc.Entity('empty', app), camera);
    frame(camera, true);
    app.fire('prerender');
    const layer = app.scene.layers.getLayerByName(SPLAT_DISPLAY_LAYER)!;
    expect(order(app).filter((name) => name.startsWith(SPLAT_DISPLAY_LAYER))).toHaveLength(2);
    first.dispose();
    expect(first.active).toBe(false);
    expect(splat.layers).toEqual([pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE]);
    // Disposed, it moves nothing on later frames.
    app.fire('prerender');
    expect(splat.layers).toEqual([pc.LAYERID_WORLD, pc.LAYERID_IMMEDIATE]);
    // The other display still holds the layer.
    expect(app.scene.layers.layerList.includes(layer)).toBe(true);
    second.dispose();
    expect(app.scene.layers.layerList.includes(layer)).toBe(false);
    expect(camera.layers.includes(layer.id)).toBe(false);
    // A dressed material made after dispose is left alone.
    const late = new pc.ShaderMaterial();
    materialCreated(app, late, camera, layer);
    expect(late.hasShaderChunks).toBe(false);
  });
});
