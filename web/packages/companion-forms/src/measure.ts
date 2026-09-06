/**
 * Frame timing, sampled the same way ADR-0003's harness samples it.
 *
 * The numbers only mean something in a visible, foreground window. A hidden pane throttles
 * requestAnimationFrame to nothing, so a run taken behind another window is not a slow result, it
 * is an invalid one. `sample` refuses rather than reporting a fiction.
 */

export interface FrameSample {
  readonly frames: number;
  readonly meanMs: number;
  readonly p50Ms: number;
  readonly p95Ms: number;
  readonly worstMs: number;
  /** The mean of the slowest one percent of frames, as frames per second. */
  readonly onePercentLowFps: number;
}

export class HiddenWindowError extends Error {
  constructor() {
    super('The window was hidden during the sample, so the frame times are not measurements.');
    this.name = 'HiddenWindowError';
  }
}

export async function sample(durationMs: number): Promise<FrameSample> {
  if (document.visibilityState !== 'visible') throw new HiddenWindowError();

  const deltas: number[] = [];
  await new Promise<void>((resolve) => {
    let last = performance.now();
    const started = last;
    const tick = (now: number): void => {
      deltas.push(now - last);
      last = now;
      if (now - started < durationMs) requestAnimationFrame(tick);
      else resolve();
    };
    requestAnimationFrame(tick);
  });

  if (document.visibilityState !== 'visible') throw new HiddenWindowError();
  // The first interval spans the call rather than a frame.
  deltas.shift();
  if (deltas.length === 0) throw new HiddenWindowError();

  const sorted = [...deltas].sort((a, b) => a - b);
  const at = (fraction: number): number => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))]!;
  const slowestCount = Math.max(1, Math.round(sorted.length * 0.01));
  const slowest = sorted.slice(-slowestCount);
  const slowestMean = slowest.reduce((total, value) => total + value, 0) / slowest.length;

  return {
    frames: deltas.length,
    meanMs: round(deltas.reduce((total, value) => total + value, 0) / deltas.length),
    p50Ms: round(at(0.5)),
    p95Ms: round(at(0.95)),
    worstMs: round(sorted[sorted.length - 1]!),
    onePercentLowFps: round(1000 / slowestMean),
  };
}

const round = (value: number): number => Math.round(value * 100) / 100;
