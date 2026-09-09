/**
 * Bounded motion: the one supported behaviour, and the three controls over it.
 *
 * **The behaviour produces an OFFSET, never a transform of its own.** That single decision is
 * what makes "reset restores the authored transform exactly" true rather than approximately
 * true. A behaviour that owned the transform would have to rebuild it on reset out of a position,
 * a rotation and a scale it had decomposed on trigger, and a decomposed-then-recomposed
 * similarity does not come back bit for bit. An offset composes with the authored matrix and,
 * when the offset is exactly zero, `motionTransform` returns THE AUTHORED ARRAY ITSELF. Reset is
 * therefore exact by construction and not by tolerance, and the test for it is an identity check
 * rather than an epsilon.
 *
 * The offset displaces the object in the region's display frame, which is the space the placed
 * geometry is already drawn in, so `y` is the up a visitor sees and `x`/`z` lie in the ground
 * plane the display frame levelled. It is a displacement in display units, at the walking scale
 * `display-frame.ts` fits the recovered cameras to. That scale is an exhibit scale: the frame
 * reports `metric: false` and an amplitude here inherits that, so nothing in this module is a
 * measurement of anything in the world the capture came from.
 *
 * **Motion starts where the object stands.** The cycle is a sine, so phase zero is displacement
 * zero: triggering never teleports the object to the top of its travel, and an object that has
 * never been triggered is at its authored transform for the same reason.
 *
 * **Stop holds; reset returns.** Stop freezes the phase where the visitor pressed it, which is
 * what makes stop legible as an act on a moving thing rather than a second reset. Reset is the
 * one that undoes the interaction, and it is the control the milestone requires to be exact.
 */

import type { BoundedMotionParameters } from './registry.js';

export type MotionState = 'at-rest' | 'running' | 'held';

export type MotionOffset = readonly [number, number, number];

/** Exactly zero on every axis. Compared by value, produced by reference. */
export const NO_MOTION_OFFSET: MotionOffset = Object.freeze([0, 0, 0] as [number, number, number]);

const AXIS_INDEX: Readonly<Record<BoundedMotionParameters['axis'], 0 | 1 | 2>> = Object.freeze({
  x: 0,
  y: 1,
  z: 2,
});

/**
 * Displacement at a phase, in region display units.
 *
 * `Math.sin(0)` is exactly `0` and `elapsedSeconds` of zero produces exactly `[0, 0, 0]`, which
 * is what the at-rest and just-triggered cases rely on.
 */
export function motionOffsetAt(
  parameters: BoundedMotionParameters,
  elapsedSeconds: number,
): MotionOffset {
  if (
    !Number.isFinite(elapsedSeconds) ||
    elapsedSeconds === 0 ||
    parameters.amplitude === 0 ||
    !(parameters.period > 0)
  ) {
    return NO_MOTION_OFFSET;
  }
  const displacement =
    parameters.amplitude * Math.sin((2 * Math.PI * elapsedSeconds) / parameters.period);
  const offset: [number, number, number] = [0, 0, 0];
  offset[AXIS_INDEX[parameters.axis]] = displacement;
  return Object.freeze(offset);
}

export function isAtAuthoredOffset(offset: MotionOffset): boolean {
  return offset[0] === 0 && offset[1] === 0 && offset[2] === 0;
}

/**
 * The authored transform displaced by an offset.
 *
 * Returns the authored array ITSELF when the offset is zero on every axis. That is the exactness
 * guarantee in one line: no arithmetic is performed on the authored numbers, so none of them can
 * change. (`-0 + 0` is `+0`, which is why adding zero would not have been good enough.)
 */
export function motionTransform(
  authoredRowMajor: readonly number[],
  offset: MotionOffset,
): readonly number[] {
  if (isAtAuthoredOffset(offset)) return authoredRowMajor;
  const out = [...authoredRowMajor];
  out[3] = authoredRowMajor[3]! + offset[0];
  out[7] = authoredRowMajor[7]! + offset[1];
  out[11] = authoredRowMajor[11]! + offset[2];
  return out;
}

/**
 * The runtime state of one object's motion: a phase, a control, and nothing else.
 *
 * It holds no transform and no clock. The caller advances it with the frame's delta and asks for
 * the offset; that keeps the class testable with no renderer and makes the reset guarantee a
 * property of this file rather than of whichever loop happens to drive it.
 */
export class BoundedMotion {
  readonly parameters: BoundedMotionParameters;
  #state: MotionState = 'at-rest';
  #elapsed = 0;

  constructor(parameters: BoundedMotionParameters) {
    this.parameters = Object.freeze({ ...parameters });
  }

  get state(): MotionState {
    return this.#state;
  }

  /** Seconds of motion accumulated since the last reset. Zero exactly when at rest. */
  get elapsedSeconds(): number {
    return this.#elapsed;
  }

  get offset(): MotionOffset {
    return this.#state === 'at-rest'
      ? NO_MOTION_OFFSET
      : motionOffsetAt(this.parameters, this.#elapsed);
  }

  /** Start, or resume from where stop held it. Triggering while running changes nothing. */
  trigger(): void {
    this.#state = 'running';
  }

  /** Hold the phase where it is. An object that never moved stays at rest rather than held. */
  stop(): void {
    if (this.#state === 'running') this.#state = this.#elapsed === 0 ? 'at-rest' : 'held';
  }

  /** Return to the authored transform, exactly, and stop. */
  reset(): void {
    this.#state = 'at-rest';
    this.#elapsed = 0;
  }

  /**
   * Advance the phase by one frame.
   *
   * The phase is reduced modulo the period so a session left running for hours does not lose
   * resolution in the sine's argument, and so `elapsedSeconds` stays a small number a test can
   * reason about. A non-finite or negative delta is ignored rather than propagated: a tab
   * restored from the background reports one, and a `NaN` phase would freeze the object at an
   * offset no control could clear except reset.
   */
  advance(deltaSeconds: number): void {
    if (this.#state !== 'running') return;
    if (!Number.isFinite(deltaSeconds) || deltaSeconds <= 0) return;
    const period = this.parameters.period;
    const next = this.#elapsed + deltaSeconds;
    this.#elapsed = period > 0 ? next % period : next;
  }
}
