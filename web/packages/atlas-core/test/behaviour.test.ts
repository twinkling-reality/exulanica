import { describe, expect, it } from 'vitest';
import {
  BEHAVIOUR_REGISTRY,
  BOUNDED_MOTION_ID,
  BehaviourRegistry,
  BoundedMotion,
  NO_MOTION_OFFSET,
  motionOffsetAt,
  motionTransform,
  type BehaviourDefinition,
} from '../src/index.js';

/**
 * The behaviour contract, from the two sides the milestone names.
 *
 * "Unsupported behaviour fails visibly" is tested as a refusal that carries words, because the
 * failure mode this exists to prevent is an object that renders motionless while nothing on the
 * screen says why. And "reset restores the authored transform exactly" is tested as an IDENTITY,
 * not a tolerance: the authored numbers must come back untouched, which is only true if no
 * arithmetic was performed on them.
 */

const AUTHORED: readonly number[] = Object.freeze([
  0.5, 0, 0, 3.25,
  0, 0.5, 0, -0,
  0, 0, 0.5, -7.125,
  0, 0, 0, 1,
]);

const parameters = (over: Partial<{ axis: 'x' | 'y' | 'z'; amplitude: number; period: number }> = {}) =>
  ({ axis: 'y' as const, amplitude: 0.4, period: 4, ...over });

describe('the behaviour registry supports exactly one behaviour and refuses the rest visibly', () => {
  it('carries one definition, and it is bounded motion with three controls', () => {
    expect(BEHAVIOUR_REGISTRY.definitions).toHaveLength(1);
    const definition = BEHAVIOUR_REGISTRY.definitions[0]!;
    expect(definition.behaviourId).toBe(BOUNDED_MOTION_ID);
    expect(definition.controls).toEqual(['trigger', 'stop', 'reset']);
    expect(definition.resetIsExact).toBe(true);
    expect(definition.axes).toEqual(['x', 'y', 'z']);
    expect(Object.isFrozen(definition)).toBe(true);
    expect(Object.isFrozen(definition.ranges.amplitude)).toBe(true);
  });

  it('refuses an unknown id with a reason that names what is supported', () => {
    const resolution = BEHAVIOUR_REGISTRY.resolve('motion.orbit');
    expect(resolution.ok).toBe(false);
    if (resolution.ok) throw new Error('unreachable');
    expect(resolution.reason).toContain('motion.orbit');
    expect(resolution.reason).toContain(BOUNDED_MOTION_ID);
    expect(BEHAVIOUR_REGISTRY.has('motion.orbit')).toBe(false);
  });

  it('refuses parameters for an unknown id rather than reading them against a default', () => {
    const read = BEHAVIOUR_REGISTRY.readParameters('walk', parameters());
    expect(read.ok).toBe(false);
    if (read.ok) throw new Error('unreachable');
    expect(read.reason).toContain('walk');
  });

  it('rejects a duplicate id and a range whose fallback lies outside itself', () => {
    const base: BehaviourDefinition = {
      behaviourId: 'motion.bounded',
      version: 1,
      labelKey: 'k',
      axes: ['y'],
      ranges: { amplitude: { min: 0, max: 1, fallback: 0.5 }, period: { min: 1, max: 2, fallback: 1 } },
      controls: ['trigger', 'stop', 'reset'],
      resetIsExact: true,
    };
    expect(() => new BehaviourRegistry(1, [base, base])).toThrow(/duplicate behaviour id/);
    expect(() => new BehaviourRegistry(1, [{
      ...base,
      ranges: { ...base.ranges, amplitude: { min: 0, max: 1, fallback: 9 } },
    }])).toThrow(/fallback lies outside/);
    expect(() => new BehaviourRegistry(1, [{
      ...base,
      ranges: { ...base.ranges, period: { min: 0, max: 2, fallback: 1 } },
    }])).toThrow(/positive minimum period/);
    expect(() => new BehaviourRegistry(0, [base])).toThrow(/catalog version/);
  });
});

describe('parameters are clamped to declared ranges and unsupported axes are refused', () => {
  it('clamps out-of-range amplitude and period and names what it moved', () => {
    const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, {
      axis: 'x', amplitude: 500, period: 0.01,
    });
    expect(read.ok).toBe(true);
    if (!read.ok) throw new Error('unreachable');
    expect(read.parameters).toEqual({ axis: 'x', amplitude: 2, period: 0.5 });
    expect(read.clamped).toEqual(['amplitude', 'period']);
  });

  it('clamps a negative amplitude up to the declared floor rather than mirroring the motion', () => {
    const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, {
      axis: 'y', amplitude: -3, period: 4,
    });
    if (!read.ok) throw new Error('unreachable');
    expect(read.parameters.amplitude).toBe(0);
    expect(read.clamped).toEqual(['amplitude']);
  });

  it('reports no clamping and fills declared fallbacks when a parameter is absent', () => {
    const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, { axis: 'z' });
    if (!read.ok) throw new Error('unreachable');
    expect(read.parameters).toEqual({ axis: 'z', amplitude: 0.35, period: 4 });
    expect(read.clamped).toEqual([]);
  });

  it('refuses an axis the definition does not declare instead of substituting one', () => {
    for (const axis of ['w', 'up', '', 'Y']) {
      const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, { axis, amplitude: 1, period: 4 });
      expect(read.ok).toBe(false);
      if (read.ok) throw new Error('unreachable');
      expect(read.reason).toContain('not a supported motion axis');
    }
  });

  it('refuses a non-finite number rather than clamping it onto a bound', () => {
    for (const amplitude of [Number.NaN, Number.POSITIVE_INFINITY, '1' as unknown as number]) {
      const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, { axis: 'y', amplitude, period: 4 });
      expect(read.ok).toBe(false);
    }
    expect(BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, { axis: 'y', period: Number.NaN }).ok)
      .toBe(false);
    expect(BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, null).ok).toBe(false);
    expect(BEHAVIOUR_REGISTRY.readParameters(BOUNDED_MOTION_ID, [1, 2]).ok).toBe(false);
  });
});

describe('bounded motion moves along one declared axis, bounded by its amplitude', () => {
  it('starts at the authored position and never leaves the declared amplitude', () => {
    expect(motionOffsetAt(parameters(), 0)).toEqual([0, 0, 0]);
    for (let t = 0; t <= 8; t += 0.05) {
      const offset = motionOffsetAt(parameters({ axis: 'x', amplitude: 0.4 }), t);
      expect(Math.abs(offset[0])).toBeLessThanOrEqual(0.4 + 1e-12);
      expect(offset[1]).toBe(0);
      expect(offset[2]).toBe(0);
    }
  });

  it('displaces only the axis it was given', () => {
    const quarter = motionOffsetAt(parameters({ axis: 'z', amplitude: 1, period: 4 }), 1);
    expect(quarter[0]).toBe(0);
    expect(quarter[1]).toBe(0);
    expect(quarter[2]).toBeCloseTo(1, 12);
  });

  it('holds still when the amplitude is zero or the period is not positive', () => {
    expect(motionOffsetAt(parameters({ amplitude: 0 }), 1.7)).toBe(NO_MOTION_OFFSET);
    expect(motionOffsetAt(parameters({ period: 0 }), 1.7)).toBe(NO_MOTION_OFFSET);
    expect(motionOffsetAt(parameters(), Number.NaN)).toBe(NO_MOTION_OFFSET);
  });
});

describe('trigger, stop and reset', () => {
  it('does not move until it is triggered', () => {
    const motion = new BoundedMotion(parameters());
    motion.advance(1);
    expect(motion.state).toBe('at-rest');
    expect(motion.offset).toBe(NO_MOTION_OFFSET);
  });

  it('moves after trigger, holds its phase on stop, and resumes on the next trigger', () => {
    const motion = new BoundedMotion(parameters({ axis: 'y', amplitude: 1, period: 4 }));
    motion.trigger();
    motion.advance(1);
    expect(motion.state).toBe('running');
    expect(motion.offset[1]).toBeCloseTo(1, 12);

    motion.stop();
    expect(motion.state).toBe('held');
    const held = motion.offset;
    motion.advance(2);
    expect(motion.offset).toEqual(held);
    expect(motion.elapsedSeconds).toBe(1);

    motion.trigger();
    motion.advance(1);
    expect(motion.elapsedSeconds).toBe(2);
  });

  it('ignores a non-finite, zero or negative frame delta', () => {
    const motion = new BoundedMotion(parameters());
    motion.trigger();
    for (const dt of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1]) motion.advance(dt);
    expect(motion.elapsedSeconds).toBe(0);
    expect(motion.offset).toBe(NO_MOTION_OFFSET);
  });

  it('keeps the phase inside one period however long it runs', () => {
    const motion = new BoundedMotion(parameters({ period: 4 }));
    motion.trigger();
    for (let i = 0; i < 10_000; i += 1) motion.advance(0.5);
    expect(motion.elapsedSeconds).toBeGreaterThanOrEqual(0);
    expect(motion.elapsedSeconds).toBeLessThan(4);
  });

  it('restores the authored transform EXACTLY on reset, by returning the authored array itself', () => {
    const motion = new BoundedMotion(parameters({ axis: 'y', amplitude: 1.5, period: 3 }));
    motion.trigger();
    for (const dt of [0.37, 0.11, 0.9, 0.25, 1.4]) motion.advance(dt);
    const moved = motionTransform(AUTHORED, motion.offset);
    expect(moved).not.toBe(AUTHORED);
    expect(moved[7]).not.toBe(AUTHORED[7]);

    motion.reset();
    expect(motion.state).toBe('at-rest');
    expect(motion.elapsedSeconds).toBe(0);
    const restored = motionTransform(AUTHORED, motion.offset);
    // Identity, not equality: no arithmetic touched the authored numbers.
    expect(restored).toBe(AUTHORED);
    for (let i = 0; i < 16; i += 1) expect(Object.is(restored[i], AUTHORED[i])).toBe(true);
  });

  it('preserves a negative zero in the authored transform, which adding zero would not', () => {
    expect(Object.is(AUTHORED[7], -0)).toBe(true);
    expect(Object.is(motionTransform(AUTHORED, NO_MOTION_OFFSET)[7], -0)).toBe(true);
    // The contrast: the arithmetic this module avoids turns -0 into +0.
    expect(Object.is(AUTHORED[7]! + 0, -0)).toBe(false);
  });

  it('resets exactly from every reachable state, including one never triggered', () => {
    for (const script of [
      () => undefined,
      (m: BoundedMotion) => { m.trigger(); },
      (m: BoundedMotion) => { m.trigger(); m.advance(0.7); },
      (m: BoundedMotion) => { m.trigger(); m.advance(0.7); m.stop(); },
      (m: BoundedMotion) => { m.trigger(); m.advance(0.7); m.stop(); m.trigger(); m.advance(0.3); },
      (m: BoundedMotion) => { m.reset(); m.trigger(); m.advance(2.2); m.reset(); m.trigger(); },
    ]) {
      const motion = new BoundedMotion(parameters());
      script(motion);
      motion.reset();
      expect(motionTransform(AUTHORED, motion.offset)).toBe(AUTHORED);
    }
  });

  it('stays at rest when stop arrives before the phase has advanced', () => {
    const motion = new BoundedMotion(parameters());
    motion.trigger();
    motion.stop();
    expect(motion.state).toBe('at-rest');
    expect(motionTransform(AUTHORED, motion.offset)).toBe(AUTHORED);
  });

  it('displaces only the translation column, leaving the authored basis untouched', () => {
    const moved = motionTransform(AUTHORED, [0.25, -0.5, 2]);
    expect(moved[3]).toBe(3.5);
    expect(moved[7]).toBe(-0.5);
    expect(moved[11]).toBe(-5.125);
    for (const i of [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14, 15]) {
      expect(moved[i]).toBe(AUTHORED[i]);
    }
  });
});
