// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { DATA_VIEW_STYLE, DATA_VIEW_STYLE_STREET, dataViewRgb } from '@exulanica/atlas-core';
import { dataViewClockSeconds } from '../../src/playcanvas/data-view/overlay.js';
import { dataViewGroundRgb } from '../../src/playcanvas/data-view/overlay.js';
import {
  DATA_VIEW_CLOCK_UNIFORM, DATA_VIEW_KEEP_UNIFORM, DATA_VIEW_VERTEX_BYTES, createDataViewPoints, dataViewDensityCode,
} from '../../src/playcanvas/data-view/points.js';
import { createDataViewSkinnedGroup } from '../../src/playcanvas/data-view/skinned-points.js';
import { POINT_FRAGMENT_GLSL, POINT_VERTEX_GLSL } from '../../src/playcanvas/point-shader.js';

function device() {
  const canvas = document.createElement('canvas');
  const graphics = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = graphics;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return { app, graphics };
}

describe('data view point draw', () => {
  it('uploads exactly the given samples in the point-map layout, under the borrowed node', () => {
    const { app, graphics } = device();
    const node = new pc.Entity('borrowed');
    app.root.addChild(node);
    const points = createDataViewPoints({
      device: graphics, node, positions: new Float32Array([0, 0, 0, 1, 2, 3]), style: DATA_VIEW_STYLE, subjectId: 's',
    })!;
    expect(points.pointCount).toBe(2);
    expect(points.byteLength).toBe(2 * DATA_VIEW_VERTEX_BYTES * 2);
    const child = node.findByName('data-view-points:s') as pc.Entity;
    const instance = child.render!.meshInstances[0]!;
    expect(instance.pick).toBe(false);
    expect(instance.mesh.primitive[0]!.type).toBe(pc.PRIMITIVE_POINTS);
    expect(instance.mesh.aabb.getMax().toString()).toBe('[1, 2, 3]');
    const material = instance.material as pc.ShaderMaterial;
    expect(material.blendType).toBe(pc.BLEND_ADDITIVEALPHA);
    expect(material.depthWrite).toBe(false);
    expect(instance.visible).toBe(false);
    points.setWeight(0.25);
    points.setLook?.({ colour: '#ff8000', treatment: 'dashes', gain: 1 });
    expect(instance.visible).toBe(true);
    const data = (name: string) => (material.getParameter(name) as { data: Float32Array }).data;
    const look = data('uDataViewLook');
    expect(look[1]).toBeCloseTo(Math.min(1, 0.25 * DATA_VIEW_STYLE.points.rise));
    expect(look[2]).toBeCloseTo(DATA_VIEW_STYLE.dashes.bandDepth);
    const shape = data('uDataView');
    expect(shape[3]).toBeCloseTo(DATA_VIEW_STYLE.dashes.halfWidth);
    expect(shape[0]).toBeCloseTo(DATA_VIEW_STYLE.points.sizeMetres * DATA_VIEW_STYLE.dashes.sizeScale);
    const palette = data('uPalette[0]');
    expect([...palette.slice(0, 3)]).toEqual([...dataViewRgb('#ff8000')].map(Math.fround));
    points.destroy();
    points.destroy();
    expect(node.findByName('data-view-points:s')).toBeNull();
    app.destroy();
  });

  it('refuses empty and non-finite buffers rather than drawing part of one', () => {
    const { app, graphics } = device();
    const node = new pc.Entity('borrowed');
    for (const positions of [new Float32Array(0), new Float32Array([0, Number.NaN, 0])]) {
      expect(createDataViewPoints({ device: graphics, node, positions, style: DATA_VIEW_STYLE, subjectId: 's' })).toBeNull();
    }
    app.destroy();
  });

  it('twinkles as its style says, on one clock and one kept share for every data view draw', () => {
    const { app, graphics } = device();
    const node = new pc.Entity('borrowed');
    app.root.addChild(node);
    const life = (style: typeof DATA_VIEW_STYLE) => {
      const points = createDataViewPoints({ device: graphics, node, positions: new Float32Array([0, 0, 0]), style, subjectId: `s${style.version}` })!;
      const instance = (node.findByName(`data-view-points:s${style.version}`) as pc.Entity).render!.meshInstances[0]!;
      const value = [...((instance.material as pc.ShaderMaterial).getParameter('uDataViewLife') as { data: Float32Array }).data];
      points.destroy();
      return value;
    };
    expect(life(DATA_VIEW_STYLE_STREET).map(Math.fround)).toEqual([0.12, 4, 0, 0].map(Math.fround));
    expect(life(DATA_VIEW_STYLE).map(Math.fround)).toEqual([0, 1, 0, 0]);
    // Filled once when missing (still, and every sample), never overwritten: the host owns both.
    expect(graphics.scope.resolve(DATA_VIEW_CLOCK_UNIFORM).value).toBe(0);
    expect(graphics.scope.resolve(DATA_VIEW_KEEP_UNIFORM).value).toBe(1);
    graphics.scope.resolve(DATA_VIEW_KEEP_UNIFORM).setValue(0.5);
    life(DATA_VIEW_STYLE_STREET);
    expect(graphics.scope.resolve(DATA_VIEW_KEEP_UNIFORM).value).toBe(0.5);
    // The clock runs only where a twinkling style shows points, and never under reduced motion.
    const shown = { subjects: [{ allocatedPoints: 10, resolved: { pointWeight: 0.5 } }] } as unknown as Parameters<typeof dataViewClockSeconds>[1];
    const hidden = { subjects: [{ allocatedPoints: 10, resolved: { pointWeight: 0 } }] } as unknown as Parameters<typeof dataViewClockSeconds>[1];
    expect(dataViewClockSeconds(DATA_VIEW_STYLE_STREET, shown, false, 2_500)).toBe(2.5);
    expect(dataViewClockSeconds(DATA_VIEW_STYLE_STREET, shown, false, 1_026_000)).toBe(2);
    expect(dataViewClockSeconds(DATA_VIEW_STYLE_STREET, shown, true, 2_500)).toBeNull();
    expect(dataViewClockSeconds(DATA_VIEW_STYLE_STREET, hidden, false, 2_500)).toBeNull();
    expect(dataViewClockSeconds(DATA_VIEW_STYLE, shown, false, 2_500)).toBeNull();
    app.destroy();
  });

  it('draws a stable share of samples and twinkles their brightness alone, never their place', () => {
    const data = POINT_VERTEX_GLSL.slice(POINT_VERTEX_GLSL.indexOf('if (dataViewHash(gl_VertexID) >= keep)'));
    expect(data).toContain('>= uDataViewKeep');
    const twinkle = data.slice(data.indexOf('lifePhase'), data.indexOf('#endif'));
    expect(twinkle).toContain('vDataGain *=');
    expect(twinkle).not.toMatch(/gl_Position|worldPos|gl_PointSize/);
  });

  it('carries a sample taken for the eye with its normal and first-drawn density, drawn over its reach', () => {
    const { app, graphics } = device();
    const node = new pc.Entity('borrowed');
    app.root.addChild(node);
    const made = (samples: Parameters<typeof createDataViewPoints>[0]['samples'], style = DATA_VIEW_STYLE_STREET) => createDataViewPoints({
      device: graphics, node, positions: new Float32Array([0, 0, 0, 1, 0, 0]), style, subjectId: 's', ...(samples ? { samples } : {}),
    });
    const points = made({ normals: new Float32Array([0, 1, 0, 0, -1, 0]), densities: new Float32Array([1, 256]), reach: [8, Infinity] })!;
    const instance = (node.findByName('data-view-points:s') as pc.Entity).render!.meshInstances[0]!;
    const bytes = new Uint8Array(instance.mesh.vertexBuffer.lock());
    const shorts = new Uint16Array(bytes.buffer);
    // The normal in the colour channels (0 to 1 for -1 to 1), the density on the shader's log scale in the second tag.
    expect([...bytes.slice(12, 16)]).toEqual([128, 255, 128, 255]);
    expect([...bytes.slice(32, 36)]).toEqual([128, 0, 128, 255]);
    expect([shorts[9], shorts[19]]).toEqual([32768, 32768 + 8 * 2048]);
    expect(dataViewDensityCode(2 ** -40)).toBe(0);
    const screen = DATA_VIEW_STYLE_STREET.points.screen!;
    const material = instance.material as pc.ShaderMaterial;
    expect([...(material.getParameter('uDataViewScreen') as { data: Float32Array }).data].map(Math.fround))
      .toEqual([screen.density, screen.facingFloor, screen.nearestMetres, Math.cos((screen.coneDegrees * Math.PI) / 180)].map(Math.fround));
    expect([...(material.getParameter('uDataViewReach') as { data: Float32Array }).data]).toEqual([8, 1e9]);
    points.destroy();
    // Samples of the wrong length are refused; a style without a screen density, or no samples, draws as before.
    expect(made({ normals: new Float32Array(3), densities: new Float32Array(2), reach: [0, 8] })).toBeNull();
    expect(made({ normals: new Float32Array(6), densities: new Float32Array([1, 0]), reach: [0, 8] })).toBeNull();
    for (const old of [made(undefined)!, made({ normals: new Float32Array(6), densities: new Float32Array([1, 1]), reach: [0, 8] }, DATA_VIEW_STYLE)!]) {
      const drawn = (node.findByName('data-view-points:s') as pc.Entity).render!.meshInstances[0]!;
      expect([...((drawn.material as pc.ShaderMaterial).getParameter('uDataViewScreen') as { data: Float32Array }).data]).toEqual([0, 0, 0, 0]);
      old.destroy();
    }
    app.destroy();
  });

  it('draws the dark ground as a lit surface of its colour ends up under a camera that draws through a frame', () => {
    expect(dataViewGroundRgb(DATA_VIEW_STYLE_STREET, false)).toEqual(dataViewRgb(DATA_VIEW_STYLE_STREET.ground.colour));
    const framed = dataViewGroundRgb(DATA_VIEW_STYLE_STREET, true);
    dataViewRgb(DATA_VIEW_STYLE_STREET.ground.colour).forEach((value, at) => {
      expect(framed[at]).toBeCloseTo(value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4, 9);
      expect(framed[at]).toBeLessThan(value);
    });
  });

  it('draws a walker as points by its own bones, and lets go of them the frame its skin is gone', () => {
    const { app, graphics } = device();
    const layer = app.scene.layers.getLayerById(pc.LAYERID_WORLD)!;
    const bone = new pc.Entity('bone');
    app.root.addChild(bone);
    const mesh = new pc.Mesh(graphics);
    mesh.setPositions([0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 2, 0]);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    mesh.skin = new pc.Skin(graphics, [new pc.Mat4()], ['bone']);
    const source = new pc.MeshInstance(mesh, new pc.StandardMaterial(), bone);
    const skin = new pc.SkinInstance(mesh.skin);
    skin.bones = [bone];
    source.skinInstance = skin;
    const group = createDataViewSkinnedGroup({ app, device: graphics, layer, colour: '#ffffff', style: DATA_VIEW_STYLE_STREET, pixels: 771, stride: 2 });
    expect(group.add(new pc.MeshInstance(mesh, new pc.StandardMaterial(), bone))).toBeNull();
    const points = group.add(source)!;
    expect(points.pointCount).toBe(3);
    const drawn = layer.meshInstances.find((one) => one.material?.name === 'data-view-skinned-points')!;
    expect(drawn.skinInstance).toBe(skin);
    expect(drawn.mesh.vertexBuffer).toBe(mesh.vertexBuffer);
    expect(drawn.mesh.primitive[0]!.type).toBe(pc.PRIMITIVE_POINTS);
    expect(drawn.visible).toBe(false);
    group.setWeight(1);
    expect(drawn.visible).toBe(true);
    points.setShown(false);
    expect(drawn.visible).toBe(false);
    // The walker goes: their skin with them. Before the next frame is drawn the points are let go of, and the walker's
    // own skin and vertices are untouched by it.
    source.skinInstance = null;
    app.fire('prerender');
    expect(points.gone).toBe(true);
    expect(layer.meshInstances.includes(drawn)).toBe(false);
    expect(mesh.vertexBuffer).not.toBeNull();
    expect(skin.boneTexture).not.toBeNull();
    group.destroy();
    app.destroy();
  });

  it('keeps the point-map program unchanged unless the data view asks for its define', () => {
    const strip = (source: string) => source.replace(/#ifdef DATA_VIEW[\s\S]*?#endif\n/g, '');
    for (const source of [POINT_VERTEX_GLSL, POINT_FRAGMENT_GLSL]) {
      expect(strip(source)).not.toContain('uDataView');
      expect(source.match(/#ifdef DATA_VIEW/g)!.length).toBeGreaterThan(0);
    }
  });
});
