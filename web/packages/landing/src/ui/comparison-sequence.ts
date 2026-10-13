import { COMPARISON_FIGURE, COMPARISON_STAGES } from '../content/comparison-figure.js';

export const clampFigure = (value: number) => Math.max(0, Math.min(3, Number.isFinite(value) ? value : 0));
const smooth = (value: number) => { const x = Math.max(0, Math.min(1, value)); return x * x * (3 - 2 * x); };

/** All geometry, control values and readouts derive from the same explanatory position.
 * Position is figure time, never a simulated minute or a measured model result.
 */
export function comparisonPose(position: number) {
  const at = clampFigure(position);
  const stage = Math.min(2, Math.floor(at));
  const recording = Math.max(0, Math.min(1, at - 1));
  const replay = Math.max(0, Math.min(1, at - 2));
  return {
    position: at, stage,
    source: smooth(at / .65),
    recorded: recording,
    // Real rotation through depth disconnects the model inlet during replay.
    headAngle: smooth(replay / .23) * -68,
    reader: at < 2 ? recording : 1 - smooth((replay - .23) / .77),
    readout: COMPARISON_STAGES[stage]!.readout,
  };
}

/** Active time only; suspension discards hidden time instead of catching up. */
export function createComparisonSequence() {
  let position = .65;
  let last: number | null = null;
  return {
    get position() { return position; },
    seek(value: number) { position = clampFigure(value); last = null; return comparisonPose(position); },
    suspend() { last = null; },
    advance(now: number) {
      if (last !== null) position = clampFigure(position + Math.max(0, Math.min(100, now - last)) * 3 / COMPARISON_FIGURE.duration);
      last = now;
      return comparisonPose(position);
    },
  };
}
