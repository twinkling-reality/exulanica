// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { DATA_VIEW_STYLE, dataViewRgb } from '@exulanica/atlas-core';
import { DATA_VIEW_VERTEX_BYTES, createDataViewPoints } from '../../src/playcanvas/data-view/points.js';
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

  it('keeps the point-map program unchanged unless the data view asks for its define', () => {
    const strip = (source: string) => source.replace(/#ifdef DATA_VIEW[\s\S]*?#endif\n/g, '');
    for (const source of [POINT_VERTEX_GLSL, POINT_FRAGMENT_GLSL]) {
      expect(strip(source)).not.toContain('uDataView');
      expect(source.match(/#ifdef DATA_VIEW/g)!.length).toBeGreaterThan(0);
    }
  });
});
