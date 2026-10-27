// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { DATA_VIEW_STYLE, DATA_VIEW_STYLE_STREET, dataViewRgb } from '@exulanica/atlas-core';
import { dataViewClockSeconds } from '../../src/playcanvas/data-view/overlay.js';
import {
  DATA_VIEW_CLOCK_UNIFORM, DATA_VIEW_KEEP_UNIFORM, DATA_VIEW_VERTEX_BYTES, createDataViewPoints,
} from '../../src/playcanvas/data-view/points.js';
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

  it('keeps the point-map program unchanged unless the data view asks for its define', () => {
    const strip = (source: string) => source.replace(/#ifdef DATA_VIEW[\s\S]*?#endif\n/g, '');
    for (const source of [POINT_VERTEX_GLSL, POINT_FRAGMENT_GLSL]) {
      expect(strip(source)).not.toContain('uDataView');
      expect(source.match(/#ifdef DATA_VIEW/g)!.length).toBeGreaterThan(0);
    }
  });
});
