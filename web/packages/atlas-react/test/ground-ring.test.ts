// @vitest-environment happy-dom
// The ring at a chosen character's feet, drawn in the world (ground-ring.ts): what makes walls and
// legs cover it (a transparent material drawn after solid surfaces, depth-tested, writing no depth),
// that it moves by its transform alone and asks for a frame only when it moves, and that it goes
// whole when disposed. Its look is a shader; a picture of it is the check of the look.
import * as pc from 'playcanvas';
import { describe, expect, it, vi } from 'vitest';
import { GROUND_RING, createGroundRing, groundRingMaterial } from '../src/playcanvas/ground-ring.js';

function nullApp() {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  return app;
}

describe('a ring drawn on the ground', () => {
  it('is covered by what stands in front and covers nothing: depth-tested, no depth written, blended after solids', () => {
    const material = groundRingMaterial();
    expect(material.depthTest).toBe(true);
    expect(material.depthWrite).toBe(false);
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    expect(material.transparent).toBe(true);
    expect(material.cull).toBe(pc.CULLFACE_NONE);
  });

  it('lies hidden until placed, then stands on its point, lifted a little, and casts no shadow', () => {
    const app = nullApp();
    const invalidate = vi.fn();
    const ring = createGroundRing(app, { invalidate });
    expect(ring.drawn).toBe(true);
    expect(ring.entity.enabled).toBe(false);
    expect(ring.entity.parent).toBe(app.root);
    ring.place({ x: 4, y: 1.5, z: -2 }, 0.44);
    expect(ring.entity.enabled).toBe(true);
    const at = ring.entity.getPosition();
    expect([at.x, at.y, at.z]).toEqual([4, 1.5 + GROUND_RING.liftMetres, -2].map((value) => Math.fround(value)));
    const instance = ring.entity.render!.meshInstances[0]!;
    expect(instance.castShadow).toBe(false);
    expect((instance.material.getParameter('uRing') as { data: Float32Array } | undefined)?.data).toEqual(new Float32Array([0.44, 0.44 * (1 + GROUND_RING.reachShare), 0, 0]));
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('asks for a frame only when it moves or hides, and keeps its mesh while it moves', () => {
    const app = nullApp();
    const invalidate = vi.fn();
    const ring = createGroundRing(app, { invalidate });
    ring.place({ x: 0, y: 0, z: 0 }, 0.44);
    const mesh = ring.entity.render!.meshInstances[0]!.mesh;
    ring.place({ x: 0, y: 0, z: 0 }, 0.44);
    expect(invalidate).toHaveBeenCalledTimes(1);
    ring.place({ x: 1, y: 0, z: 0 }, 0.44);
    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(ring.entity.render!.meshInstances[0]!.mesh).toBe(mesh);
    ring.hide();
    ring.hide();
    expect(ring.entity.enabled).toBe(false);
    expect(invalidate).toHaveBeenCalledTimes(3);
    // Placed again at the same point after hiding, it shows again.
    ring.place({ x: 1, y: 0, z: 0 }, 0.44);
    expect(ring.entity.enabled).toBe(true);
  });

  it('holds its widths in CSS pixels, at the canvas\'s pixels per CSS pixel, and follows a resize', () => {
    const canvas = document.createElement('canvas');
    canvas.width = 1200;
    let shown = 800;
    Object.defineProperty(canvas, 'clientWidth', { get: () => shown });
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
    app.init(options);
    const invalidate = vi.fn();
    const ring = createGroundRing(app, { invalidate });
    const material = ring.entity.render!.meshInstances[0]!.material;
    const drawnWidths = () => Array.from((material.getParameter('uWidths') as { data: Float32Array }).data);
    const at = (ratio: number) => [GROUND_RING.linePx * ratio, GROUND_RING.glowPx * ratio, GROUND_RING.glowBlurPx * ratio, GROUND_RING.glowAlpha].map((value) => Math.fround(value));
    expect(drawnWidths()).toEqual(at(1.5));
    ring.place({ x: 0, y: 0, z: 0 }, 0.44);
    shown = 600;
    app.graphicsDevice.fire(pc.GraphicsDevice.EVENT_RESIZE, 1200, 900);
    expect(drawnWidths()).toEqual(at(2));
    expect(invalidate).toHaveBeenCalledTimes(2);
    ring.dispose();
    shown = 1200;
    app.graphicsDevice.fire(pc.GraphicsDevice.EVENT_RESIZE, 1200, 900);
    expect(drawnWidths()).toEqual(at(2));
  });

  it('goes whole when disposed, and draws nothing on a device that runs WebGPU', () => {
    const app = nullApp();
    const ring = createGroundRing(app);
    ring.place({ x: 0, y: 0, z: 0 }, 0.44);
    ring.dispose();
    expect(app.root.findByName('ground-ring')).toBeNull();
    const gpu = nullApp();
    Object.defineProperty(gpu.graphicsDevice, 'isWebGPU', { value: true });
    const none = createGroundRing(gpu);
    expect(none.drawn).toBe(false);
    none.place({ x: 0, y: 0, z: 0 }, 0.44);
    expect(none.entity.enabled).toBe(false);
  });
});
