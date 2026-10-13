import type * as pc from 'playcanvas';
import type { SiteTextureMetrics } from '../style-pack/site-textures.js';

/** Bounded frame-interval evidence for an opt-in site review, exposed on its existing canvas. */
export function measureSite(app: pc.AppBase, textures: SiteTextureMetrics | undefined, environmentBytes: number, view?: () => { readonly positionM: readonly number[]; readonly forward: readonly number[] }): () => void {
  const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
  const intervals: number[] = [];
  let frames = 0;
  let stopped = false;
  const frame = (ms: number): void => {
    if (Number.isFinite(ms) && ms > 0) intervals.push(ms);
    if (intervals.length > 300) intervals.shift();
    frames += 1;
    if (frames % 30 !== 0) return;
    const ordered = [...intervals].sort((a, b) => a - b);
    const percentile = (p: number): number | null => ordered.length === 0 ? null : ordered[Math.floor((ordered.length - 1) * p)]!;
    canvas.dataset['siteMeasurements'] = JSON.stringify({
      view: view?.(),
      frameIntervalsMs: { samples: ordered.length, p50: percentile(.5), p95: percentile(.95), max: ordered.at(-1) ?? null },
      drawCalls: app.stats.drawCalls.total,
      canvasPixels: [canvas.width, canvas.height],
      deviceType: app.graphicsDevice.deviceType,
      textureBytesAccounted: textures?.decodedTextureBytes ?? 0,
      textureBytesTransferred: textures?.transferredBytes ?? 0,
      environmentBytesAccounted: environmentBytes,
      unavailableSurfaces: textures?.unavailableSurfaces ?? 0,
    });
  };
  app.on('frameupdate', frame);
  return () => {
    if (stopped) return;
    stopped = true;
    app.off('frameupdate', frame);
    delete canvas.dataset['siteMeasurements'];
  };
}
