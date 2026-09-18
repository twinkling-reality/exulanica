/**
 * Stepping the runtime a stated frame at a time, for a capture that does not depend on a clock.
 *
 * DEVELOPMENT ONLY. Nothing in the shipped app reaches this: the one caller is the app's development
 * capture module, which is imported only behind `import.meta.env.DEV` and only on the preview route,
 * the same two guards the tile evaluation itself sits behind.
 *
 * WHY IT EXISTS, measured rather than assumed. Driving the page from outside with Chrome's virtual
 * clock captures a light tile perfectly (240 frames, no stalls, on a 596 triangle bake) and dies on a
 * real street: the tessellator-13 corridor tile, 32,834 triangles in a 9.4 MB container, hands over
 * three frames and then stops, whatever the nudge budget, the patience, the virtual time policy or
 * the settle. A single screenshot of that same tile works when the clock is not virtualised, so the
 * fault is the pairing rather than the tile. This removes the clock from the problem instead of
 * treating the deadlock: the caller states dt, the engine's own loop is cancelled, and each frame is
 * updated, rendered and read in ONE synchronous task.
 *
 * THE PATTERN IS THE BENCH'S, not a second one invented here: `autoRender` off, pump the frame,
 * read in the same task as the render it reads, because this device keeps no preserved drawing
 * buffer and a read in a later task would find it cleared.
 */

import * as pc from 'playcanvas';

export interface TileCaptureSession {
  /** How many frames this session has stepped. */
  readonly frames: number;
  /** Advance by exactly `dtSeconds`, draw, and answer the frame as a PNG data URL. */
  step(dtSeconds: number): string;
  /** Hand the engine back its own loop. */
  end(): void;
}

/**
 * Take over the running application's frame loop, or answer a sentence saying why not.
 *
 * A refusal is a string rather than an exception because the caller is a capture driver reading the
 * answer over a debugging protocol, and a sentence survives that trip where a stack does not.
 */
export function beginTileCapture(): TileCaptureSession | string {
  const app = pc.AppBase.getApplication();
  if (app === undefined) return 'no application is running on this page, so there is nothing to step';
  const canvas = app.graphicsDevice?.canvas ?? null;
  if (canvas === null) return 'the application has no canvas, so there is nothing to read';

  // The engine's own tick is a clock. Cancelling it is what makes the stepping deterministic: from
  // here the only thing that advances this world is a caller stating a dt.
  pc.AppBase.cancelTick(app);
  const wasAutoRender = app.autoRender;
  app.autoRender = false;
  let stepped = 0;
  let ended = false;

  return {
    get frames(): number {
      return stepped;
    },
    step(dtSeconds: number): string {
      if (ended) throw new Error('this capture session has ended');
      if (!Number.isFinite(dtSeconds) || dtSeconds <= 0) throw new Error(`a frame needs a positive dt, not ${dtSeconds}`);
      // Update, draw and read in one task. The draw is forced rather than requested: the host draws
      // only frames its binding asks for, and a capture wants every frame it stepped.
      app.update(dtSeconds);
      app.renderNextFrame = true;
      app.render();
      stepped += 1;
      return canvas.toDataURL('image/png');
    },
    end(): void {
      if (ended) return;
      ended = true;
      app.autoRender = wasAutoRender;
      // Give the engine its loop back, so a page that was captured is a page that still runs.
      app.tick();
    },
  };
}
