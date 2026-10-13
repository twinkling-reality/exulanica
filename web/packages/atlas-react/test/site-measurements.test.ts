// @vitest-environment happy-dom
import * as pc from 'playcanvas';
import { expect, it } from 'vitest';
import { measureSite } from '../src/playcanvas/generated-site/site-measurements.js';

it('bounds valid frame samples and keeps viewpoint and partial byte accounting explicit', () => {
  const canvas = document.createElement('canvas');
  canvas.width = 1280; canvas.height = 720;
  const app = Object.assign(new pc.EventHandler(), { graphicsDevice: { canvas, deviceType: 'webgl2' }, stats: { drawCalls: { total: 12 } } });
  const stop = measureSite(app as unknown as pc.AppBase, { transferredBytes: 100, decodedTextureBytes: 400, unavailableSurfaces: 1 }, 800,
    () => ({ positionM: [40, 1.62, -16], forward: [-1, 0, 0] }));
  for (let i = 0; i < 330; i++) app.fire('frameupdate', 8);
  app.fire('frameupdate', NaN);
  app.fire('frameupdate', -5);
  const measured = JSON.parse(canvas.dataset['siteMeasurements']!);
  expect(measured).toMatchObject({ frameIntervalsMs: { samples: 300, p50: 8, p95: 8, max: 8 }, canvasPixels: [1280, 720], drawCalls: 12,
    view: { positionM: [40, 1.62, -16], forward: [-1, 0, 0] }, textureBytesAccounted: 400, environmentBytesAccounted: 800 });
  stop();
  expect(canvas.dataset['siteMeasurements']).toBeUndefined();
  canvas.dataset['siteMeasurements'] = 'another mount';
  stop();
  for (let i = 0; i < 30; i++) app.fire('frameupdate', 99);
  expect(canvas.dataset['siteMeasurements']).toBe('another mount');
});
