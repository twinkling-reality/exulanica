// @vitest-environment happy-dom
// The layout under a painted world drawn as depth only (splat-occlusion.ts): what makes a wall cover
// a person behind it and leave its own splats drawn (no colour, depth tested and written, pushed
// back), that a library material is copied once and never changed, that glass and decals stay as
// they are, that it draws before the people its walls hide, that the sky draws before it, that the
// layout's depth reaches a frame's prepass, and that dispose gives everything back.
// Materials are compared by identity as booleans: a failed match then reports at once, where a
// diff of two engine materials would print the whole device.
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { SPLAT_OCCLUSION, SPLAT_OCCLUSION_PUSH_UNIFORM, layoutDepthOnly } from '../src/playcanvas/splat-occlusion.js';

function nullApp() {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  return app;
}

/** A box under `parent` drawn with `material`, returning its one mesh instance. */
function box(app: pc.AppBase, parent: pc.Entity, material: pc.Material): pc.MeshInstance {
  const entity = new pc.Entity('layout-piece', app);
  const instance = new pc.MeshInstance(pc.Mesh.fromGeometry(app.graphicsDevice, new pc.BoxGeometry()), material);
  entity.addComponent('render', { meshInstances: [instance] });
  parent.addChild(entity);
  return instance;
}

function colourWrites(material: pc.Material): boolean[] {
  return [material.redWrite, material.greenWrite, material.blueWrite, material.alphaWrite];
}

/** The copy's vertex-stage user code: its declarations and the end of its main. */
function vertexHooks(material: pc.Material): [string | undefined, string | undefined] {
  if (!material.hasShaderChunks) return [undefined, undefined];
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  return [chunks.get('litUserDeclarationVS'), chunks.get('litUserMainEndVS')];
}

/** The push the copy hands its shader, if any. */
function pushParameter(material: pc.Material): unknown {
  return (material.getParameter(SPLAT_OCCLUSION_PUSH_UNIFORM) as { data?: unknown } | undefined)?.data;
}

function layout() {
  const app = nullApp();
  const root = new pc.Entity('layout', app);
  app.root.addChild(root);
  return { app, root };
}

describe('the layout under a painted world, drawn as depth only', () => {
  it('writes no colour, tests and writes depth, draws opaque, and is pushed back by the look', () => {
    const { app, root } = layout();
    const wall = new pc.StandardMaterial();
    const instance = box(app, root, wall);
    instance.castShadow = true;
    const occlusion = layoutDepthOnly(root, { look: { ...SPLAT_OCCLUSION, depthBias: 3, slopeDepthBias: 5 } });
    expect(occlusion.instances).toBe(1);
    const copy = instance.material;
    expect(copy === wall).toBe(false);
    expect(colourWrites(copy)).toEqual([false, false, false, false]);
    expect(copy.depthTest).toBe(true);
    expect(copy.depthWrite).toBe(true);
    expect(copy.blendType).toBe(pc.BLEND_NONE);
    expect(copy.transparent).toBe(false);
    expect([copy.depthBias, copy.slopeDepthBias]).toEqual([3, 5]);
    expect(instance.castShadow).toBe(true);
    // Unless told otherwise, the defaults.
    const other = layout();
    const plain = box(other.app, other.root, new pc.StandardMaterial());
    layoutDepthOnly(other.root);
    expect([plain.material.depthBias, plain.material.slopeDepthBias]).toEqual([SPLAT_OCCLUSION.depthBias, SPLAT_OCCLUSION.slopeDepthBias]);
  });

  it('pushes the copy back from the eye in metres, in the vertex stage, outside the shadow and pick passes', () => {
    const { app, root } = layout();
    const wall = new pc.StandardMaterial();
    const instance = box(app, root, wall);
    layoutDepthOnly(root, { look: { ...SPLAT_OCCLUSION, pushMetres: 0.45 } });
    const copy = instance.material;
    expect(pushParameter(copy)).toBe(0.45);
    const [declaration, mainEnd] = vertexHooks(copy);
    expect(declaration).toContain(`uniform float ${SPLAT_OCCLUSION_PUSH_UNIFORM};`);
    expect(declaration).toContain('uniform vec3 view_position;');
    // Away from the eye along the view ray, then projected again, and the prepass's linear depth with it.
    expect(mainEnd).toContain(`vPositionW += normalize(vPositionW - view_position) * ${SPLAT_OCCLUSION_PUSH_UNIFORM};`);
    expect(mainEnd).toContain('gl_Position = matrix_viewProjection * vec4(vPositionW, 1.0);');
    expect(mainEnd).toContain('vLinearDepth = -(matrix_view * vec4(vPositionW, 1.0)).z;');
    expect(mainEnd).toMatch(/#if !defined\(SHADOW_PASS\) && !defined\(PICK_PASS\)/);
    // The library material gains no chunks.
    expect(wall.hasShaderChunks).toBe(false);
    // Unless told otherwise, the default push.
    const other = layout();
    const plain = box(other.app, other.root, new pc.StandardMaterial());
    layoutDepthOnly(other.root);
    expect(pushParameter(plain.material)).toBe(SPLAT_OCCLUSION.pushMetres);
  });

  it('reaches the vertex shaders the engine builds for the forward pass and the prepass, and not the shadow or pick passes', () => {
    const { app, root } = layout();
    // The clustered lights' chunks a running app registers, so every stage of the shader builds.
    new pc.WorldClusters(app.graphicsDevice).destroy();
    const eye = new pc.Entity('eye', app);
    eye.addComponent('camera');
    app.root.addChild(eye);
    const instance = box(app, root, new pc.StandardMaterial());
    layoutDepthOnly(root, { app });
    const vertexOf = (pass: number): string => {
      const shader = instance.getShaderInstance(pass, 0, app.scene, eye.camera!.camera.shaderParams, undefined, [[], [], []]).shader;
      const vertex: string = shader?.definition.vshader ?? '';
      expect(vertex).toContain('void main');
      return vertex;
    };
    const count = (text: string, part: string): number => text.split(part).length - 1;
    const pushes = (pass: number): number => count(vertexOf(pass), 'normalize(vPositionW - view_position)');
    const shadow = pc.ShaderPass.get(app.graphicsDevice).allocate('ShadowPass_0_0', {
      isShadow: true, lightType: pc.LIGHTTYPE_DIRECTIONAL, shadowType: pc.SHADOW_PCF3_32F,
    }).index;
    expect([pushes(pc.SHADER_FORWARD), pushes(pc.SHADER_PREPASS), pushes(pc.SHADER_PICK), pushes(shadow)]).toEqual([1, 1, 0, 0]);
    // The prepass's linear depth is taken again from the pushed position, after the engine's own.
    expect(count(vertexOf(pc.SHADER_PREPASS), 'vLinearDepth = -(matrix_view * vec4(vPositionW, 1.0)).z;')).toBe(2);
  });

  it('adds no push at zero metres, and keeps a material\'s own vertex code ahead of the push', () => {
    const { app, root } = layout();
    const still = box(app, root, new pc.StandardMaterial());
    layoutDepthOnly(root, { look: { ...SPLAT_OCCLUSION, pushMetres: 0 } });
    expect(vertexHooks(still.material)).toEqual([undefined, undefined]);
    expect(still.material.getParameter(SPLAT_OCCLUSION_PUSH_UNIFORM)).toBe(undefined);
    const other = layout();
    const swaying = new pc.StandardMaterial();
    swaying.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('litUserMainEndVS', '\n// sway\n');
    const tree = box(other.app, other.root, swaying);
    layoutDepthOnly(other.root);
    const [, mainEnd] = vertexHooks(tree.material);
    expect(mainEnd?.startsWith('\n// sway\n')).toBe(true);
    expect(mainEnd).toContain('normalize(vPositionW - view_position)');
    expect(vertexHooks(swaying)).toEqual([undefined, '\n// sway\n']);
    expect(swaying.getParameter(SPLAT_OCCLUSION_PUSH_UNIFORM)).toBe(undefined);
  });

  it('copies a shared material once and leaves the library material untouched', () => {
    const { app, root } = layout();
    const shared = new pc.StandardMaterial();
    const before = { colour: colourWrites(shared), bias: shared.depthBias, slope: shared.slopeDepthBias };
    const a = box(app, root, shared);
    const b = box(app, root, shared);
    const c = box(app, root, new pc.StandardMaterial());
    layoutDepthOnly(root);
    expect(a.material === b.material).toBe(true);
    expect(a.material === shared).toBe(false);
    expect(c.material === a.material).toBe(false);
    expect({ colour: colourWrites(shared), bias: shared.depthBias, slope: shared.slopeDepthBias }).toEqual(before);
  });

  it('leaves transparent materials, and what the filter leaves out, as they are', () => {
    const { app, root } = layout();
    const glass = new pc.StandardMaterial();
    glass.blendType = pc.BLEND_NORMAL;
    const decal = new pc.StandardMaterial();
    decal.depthWrite = false;
    const kept = new pc.StandardMaterial();
    const glassy = box(app, root, glass);
    const decalled = box(app, root, decal);
    const left = box(app, root, kept);
    const occlusion = layoutDepthOnly(root, { filter: (instance) => instance !== left });
    expect(glassy.material === glass).toBe(true);
    expect(decalled.material === decal).toBe(true);
    expect(left.material === kept).toBe(true);
    expect(occlusion.instances).toBe(0);
    expect(glass.depthWrite).toBe(true);
    expect(decal.depthWrite).toBe(false);
  });

  it('gives every instance its own material and bucket back on dispose', () => {
    const { app, root } = layout();
    const shared = new pc.StandardMaterial();
    const own = new pc.StandardMaterial();
    const a = box(app, root, shared);
    const b = box(app, root, shared);
    const c = box(app, root, own);
    c.drawBucket = 50;
    const occlusion = layoutDepthOnly(root);
    occlusion.dispose();
    expect([a.material === shared, b.material === shared, c.material === own]).toEqual([true, true, true]);
    expect([a.drawBucket, b.drawBucket, c.drawBucket]).toEqual([127, 127, 50]);
    expect(occlusion.instances).toBe(0);
    // A second dispose changes nothing.
    occlusion.dispose();
    expect(a.material === shared).toBe(true);
  });

  it('picks up instances added under the root since, without copying a material twice', () => {
    const { app, root } = layout();
    const shared = new pc.StandardMaterial();
    const first = box(app, root, shared);
    const occlusion = layoutDepthOnly(root);
    const copy = first.material;
    const tile = new pc.Entity('tile', app);
    root.addChild(tile);
    const streamed = box(app, tile, shared);
    expect(streamed.material === shared).toBe(true);
    occlusion.refresh();
    expect(streamed.material === copy).toBe(true);
    expect(first.material === copy).toBe(true);
    expect(occlusion.instances).toBe(2);
    occlusion.refresh();
    expect(occlusion.instances).toBe(2);
    occlusion.dispose();
    expect(streamed.material === shared).toBe(true);
  });

  it('draws before the people its walls hide, in whichever order its layer sorts, or in the bucket asked for', () => {
    const { app, root } = layout();
    const eye = new pc.Entity('eye', app);
    eye.addComponent('camera');
    app.root.addChild(eye);
    const wall = box(app, root, new pc.StandardMaterial());
    const person = box(app, app.root, new pc.StandardMaterial());
    const world = app.scene.layers.getLayerById(pc.LAYERID_WORLD)!;
    const drawn = (): boolean[] => {
      const culled = world.getCulledInstances(eye.camera!.camera);
      culled.opaque.length = 0;
      culled.opaque.push(person, wall);
      world.sortVisible(eye.camera!.camera, false);
      return culled.opaque.map((instance) => instance === wall);
    };
    const occlusion = layoutDepthOnly(root);
    expect(world.opaqueSortMode).toBe(pc.SORTMODE_MATERIALMESH);
    expect(wall.drawBucket).toBe(255);
    expect(drawn()).toEqual([true, false]);
    occlusion.dispose();
    world.opaqueSortMode = pc.SORTMODE_FRONT2BACK;
    const nearFirst = layoutDepthOnly(root);
    expect(wall.drawBucket).toBe(0);
    expect(drawn()).toEqual([true, false]);
    nearFirst.dispose();
    layoutDepthOnly(root, { look: { ...SPLAT_OCCLUSION, drawBucket: 40 } });
    expect(wall.drawBucket).toBe(40);
  });

  it('draws the sky before the world while held, and puts it back where it was', () => {
    const { app, root } = layout();
    box(app, root, new pc.StandardMaterial());
    const layers = app.scene.layers;
    const sky = layers.getLayerById(pc.LAYERID_SKYBOX)!;
    const world = layers.getLayerById(pc.LAYERID_WORLD)!;
    const order = () => layers.layerList.map((layer, index) => `${layer.name}:${layers.subLayerList[index] ? 't' : 'o'}`);
    const before = order();
    expect(layers.getOpaqueIndex(sky)).toBeGreaterThan(layers.getOpaqueIndex(world));
    const eye = new pc.Entity('eye', app);
    eye.addComponent('camera');
    app.root.addChild(eye);
    let relaid = 0;
    eye.camera!.on('set:layers', () => { relaid += 1; });
    const first = layoutDepthOnly(root);
    expect(layers.getOpaqueIndex(sky)).toBeLessThan(layers.getOpaqueIndex(world));
    expect(relaid).toBe(1);
    // A second layout holds it too: the sky goes back only when both are gone.
    const second = layoutDepthOnly(root);
    first.dispose();
    expect(layers.getOpaqueIndex(sky)).toBeLessThan(layers.getOpaqueIndex(world));
    second.dispose();
    expect(order()).toEqual(before);
    expect(relaid).toBe(2);
    layoutDepthOnly(root, { skyFirst: false });
    expect(order()).toEqual(before);
  });

  it('takes several roots in one call, and finds the app from them', () => {
    const { app, root } = layout();
    const scenery = new pc.Entity('site-scenery', app);
    app.root.addChild(scenery);
    const land = box(app, root, new pc.StandardMaterial());
    const tree = box(app, scenery, new pc.StandardMaterial());
    const occlusion = layoutDepthOnly([root, scenery]);
    expect(occlusion.instances).toBe(2);
    expect(colourWrites(land.material)).toEqual([false, false, false, false]);
    app.fire('prerender');
    expect(colourWrites(tree.material)).toEqual([true, true, true, true]);
  });

  it('given the app, writes colour only outside the scene layers, so a frame\'s prepass leaves the layout\'s depth', () => {
    const { app, root } = layout();
    const instance = box(app, root, new pc.StandardMaterial());
    const occlusion = layoutDepthOnly(root, { app });
    const copy = instance.material;
    expect(colourWrites(copy)).toEqual([false, false, false, false]);
    // A frame starts: the prepass draws before any scene layer and writes linear depth as colour.
    app.fire('prerender');
    expect(colourWrites(copy)).toEqual([true, true, true, true]);
    // A scene layer draws: no colour. After it, a second camera's prepass may follow.
    app.scene.fire(pc.EVENT_PRERENDER_LAYER);
    expect(colourWrites(copy)).toEqual([false, false, false, false]);
    app.scene.fire(pc.EVENT_POSTRENDER_LAYER);
    expect(colourWrites(copy)).toEqual([true, true, true, true]);
    app.fire('postrender');
    expect(colourWrites(copy)).toEqual([false, false, false, false]);
    occlusion.dispose();
    app.fire('prerender');
    expect(colourWrites(copy)).toEqual([false, false, false, false]);
  });
});
