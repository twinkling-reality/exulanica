/**
 * Bounded reversing travel along one axis, and the three controls over it.
 *
 * The reviewed registry row names this "bounded reversing travel along one axis, with renderer
 * trigger, stop and reset controls", and that sentence is the specification. The path is bounded
 * by `travel_mm`, it reverses, and the controls are the renderer's rather than stored state.
 *
 * **The object travels `travel_mm` from where it was placed and comes back.** Displacement runs
 * over `[0, travel_mm]` rather than `±travel_mm/2`, so the authored transform is one END of the
 * path and not its midpoint. A person who puts a lantern on a table and gives it a metre of travel
 * means it goes a metre from the table, not half a metre either side of it, and reset means the
 * table. Both easings start at exactly zero displacement, which is what makes the next paragraph
 * true.
 *
 * **The behaviour produces an OFFSET, never a transform of its own.** That single decision is what
 * makes "reset restores the authored transform exactly" true rather than approximately true. A
 * behaviour that owned the transform would rebuild it on reset from a position, a rotation and a
 * scale it had decomposed on trigger, and a decomposed-then-recomposed similarity does not come
 * back bit for bit. An offset composes with the authored transform, and when the offset is exactly
 * zero `motionTransform` returns THE AUTHORED ARRAY ITSELF. Reset is exact by construction rather
 * than by tolerance, and the test for it is an identity check rather than an epsilon.
 *
 * **The offset is in millimetres, because the contract's transforms are.** Every coordinate on
 * this plane is a fixed-point integer: "No IEEE-754 value reaches a digest." The displacement is a
 * real-valued position between two integer endpoints, so it is not itself quantised, but it is
 * expressed in the same unit so that nothing has to remember a conversion factor twice.
 *
 * **Motion is presentation, and it is not stored.** The contract is explicit that trigger, stop
 * and reset are "the runtime's contract, not a stored parameter", so an object reopens at the
 * transform its author placed, at rest. A phase in a sine is not a property of a world.
 */

import type { BehaviourParameters } from './registry.js';

export type MotionAxis = 'x' | 'y' | 'z';
export type MotionEasing = 'linear' | 'smooth';
export type MotionState = 'at-rest' | 'running' | 'held';

/** Displacement along each axis, in millimetres. */
export type MotionOffset = readonly [number, number, number];

/** Exactly zero on every axis. Compared by value, produced by reference. */
export const NO_MOTION_OFFSET: MotionOffset = Object.freeze([0, 0, 0] as [number, number, number]);

const AXIS_INDEX: Readonly<Record<MotionAxis, 0 | 1 | 2>> = Object.freeze({ x: 0, y: 1, z: 2 });

/** The reviewed parameters, read out of a validated parameter bag. */
export interface BoundedPath {
  readonly travelMm: number;
  readonly periodMilliseconds: number;
  readonly axis: MotionAxis;
  readonly easing: MotionEasing;
}

/**
 * Read a validated parameter bag into the shape the motion runs on.
 *
 * Takes the output of `BehaviourRegistry.readParameters`, which has already refused an unknown
 * name, an unknown choice and a wrong kind, and clamped every integer to its declared bound. This
 * only renames.
 */
export function boundedPathOf(parameters: BehaviourParameters): BoundedPath {
  return Object.freeze({
    travelMm: parameters['travel_mm'] as number,
    periodMilliseconds: parameters['period_milliseconds'] as number,
    axis: parameters['axis'] as MotionAxis,
    easing: parameters['easing'] as MotionEasing,
  });
}

/**
 * How far along its travel the object is at a phase, as a fraction in `[0, 1]`.
 *
 * Both easings are exactly `0` at phase `0` and exactly `0` again at phase `1`, which is what lets
 * a reset and a completed cycle both land on the authored transform without a tolerance.
 *
 * `smooth` is a raised cosine, which starts and ends each traverse at rest: `(1 - cos 2πp)/2`.
 * `linear` is a triangle, which travels at a constant rate and reverses instantly at each end.
 * The registry offers both, so both are implemented; a build that ran one for the other would be
 * ignoring a reviewed choice while the interface said it had honoured it.
 */
export function travelFraction(easing: MotionEasing, phase: number): number {
  if (!Number.isFinite(phase)) return 0;
  const p = phase - Math.floor(phase);
  if (p === 0) return 0;
  if (easing === 'linear') return p < 0.5 ? 2 * p : 2 * (1 - p);
  return (1 - Math.cos(2 * Math.PI * p)) / 2;
}

/** Displacement at an elapsed time, in millimetres along the declared axis. */
export function motionOffsetAt(path: BoundedPath, elapsedMilliseconds: number): MotionOffset {
  if (
    !Number.isFinite(elapsedMilliseconds)
    || elapsedMilliseconds === 0
    || path.travelMm === 0
    || !(path.periodMilliseconds > 0)
  ) {
    return NO_MOTION_OFFSET;
  }
  const displacement = path.travelMm
    * travelFraction(path.easing, elapsedMilliseconds / path.periodMilliseconds);
  if (displacement === 0) return NO_MOTION_OFFSET;
  const offset: [number, number, number] = [0, 0, 0];
  offset[AXIS_INDEX[path.axis]] = displacement;
  return Object.freeze(offset);
}

export function isAtAuthoredOffset(offset: MotionOffset): boolean {
  return offset[0] === 0 && offset[1] === 0 && offset[2] === 0;
}

/**
 * The authored translation displaced by an offset, in millimetres.
 *
 * Returns the authored triple ITSELF when the offset is zero on every axis. That is the exactness
 * guarantee in one line: no arithmetic is performed on the authored numbers, so none of them can
 * change. (`-0 + 0` is `+0`, which is why adding zero would not have been good enough, and the
 * authored values are integers off the wire, which is why nothing else needs to round.)
 */
export function motionTransform(
  authoredMm: readonly [number, number, number],
  offset: MotionOffset,
): readonly [number, number, number] {
  if (isAtAuthoredOffset(offset)) return authoredMm;
  return Object.freeze([
    authoredMm[0] + offset[0],
    authoredMm[1] + offset[1],
    authoredMm[2] + offset[2],
  ] as [number, number, number]);
}

/**
 * The runtime state of one object's motion: a phase, a control, and nothing else.
 *
 * It holds no transform and no clock. The caller advances it with the frame's delta and asks for
 * the offset; that keeps the class testable with no renderer and makes the reset guarantee a
 * property of this file rather than of whichever loop happens to drive it.
 */
export class BoundedMotion {
  readonly path: BoundedPath;
  #state: MotionState = 'at-rest';
  #elapsed = 0;

  constructor(path: BoundedPath) {
    this.path = Object.freeze({ ...path });
  }

  get state(): MotionState {
    return this.#state;
  }

  /** Milliseconds of motion accumulated since the last reset. Zero exactly when at rest. */
  get elapsedMilliseconds(): number {
    return this.#elapsed;
  }

  get offset(): MotionOffset {
    return this.#state === 'at-rest' ? NO_MOTION_OFFSET : motionOffsetAt(this.path, this.#elapsed);
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
   * resolution in the easing's argument, and so `elapsedMilliseconds` stays a small number a test
   * can reason about. A non-finite or negative delta is ignored rather than propagated: a tab
   * restored from the background reports one, and a `NaN` phase would freeze the object at an
   * offset no control could clear except reset.
   */
  advance(deltaMilliseconds: number): void {
    if (this.#state !== 'running') return;
    if (!Number.isFinite(deltaMilliseconds) || deltaMilliseconds <= 0) return;
    const period = this.path.periodMilliseconds;
    const next = this.#elapsed + deltaMilliseconds;
    this.#elapsed = period > 0 ? next % period : next;
  }
}
