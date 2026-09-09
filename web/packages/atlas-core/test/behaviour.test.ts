import { describe, expect, it } from 'vitest';
import {
  BEHAVIOUR_REGISTRY,
  BOUNDED_PATH_KEY,
  BOUNDED_PATH_VERSION,
  BehaviourRegistry,
  BoundedMotion,
  NO_MOTION_OFFSET,
  boundedPathOf,
  motionOffsetAt,
  motionTransform,
  travelFraction,
  type BehaviourDefinition,
  type BoundedPath,
} from '../src/index.js';

/**
 * The behaviour contract, from the three sides that matter.
 *
 * The bounds are NOT invented here. They are migration 0042's seeded row for
 * `motion.bounded-path@1`, and the first test asserts they are still it: a browser build that
 * offered a wider range than the server admits would make every extreme a round trip to a refusal,
 * and one that offered a narrower range would hide a reviewed capability. This test is the thing
 * that fails when the two drift.
 *
 * "Unsupported behaviour fails visibly" is tested as a refusal that carries words, because the
 * failure mode it exists to prevent is an object that renders motionless while nothing on the
 * screen says why. And "reset restores the authored transform exactly" is tested as an IDENTITY,
 * not a tolerance.
 */

/** Region-local millimetres, with a negative zero to prove no arithmetic touches them. */
const AUTHORED: readonly [number, number, number] = Object.freeze([1200, -0, -450] as [number, number, number]);

const path = (over: Partial<BoundedPath> = {}): BoundedPath => Object.freeze({
  travelMm: 1000, periodMilliseconds: 4000, axis: 'y', easing: 'smooth', ...over,
});

describe('the registry mirrors the one reviewed behaviour and refuses everything else', () => {
  it('carries motion.bounded-path version 1 with the seeded bounds', () => {
    expect(BEHAVIOUR_REGISTRY.definitions).toHaveLength(1);
    const definition = BEHAVIOUR_REGISTRY.definitions[0]!;
    expect(definition.behaviourKey).toBe('motion.bounded-path');
    expect(definition.behaviourVersion).toBe(1);
    expect(definition.controls).toEqual(['trigger', 'stop', 'reset']);
    expect(definition.resetIsExact).toBe(true);
    // Migration 0042, verbatim. If this fails, the server's registry moved and this build's copy
    // has to move with it.
    expect(definition.parameters).toEqual({
      travel_mm: { kind: 'integer', minimum: 100, maximum: 10_000, default: 1000 },
      period_milliseconds: { kind: 'integer', minimum: 500, maximum: 60_000, default: 4000 },
      axis: { kind: 'choice', choices: ['x', 'y', 'z'], default: 'x' },
      easing: { kind: 'choice', choices: ['linear', 'smooth'], default: 'smooth' },
    });
    expect(Object.isFrozen(definition)).toBe(true);
  });

  it('refuses an unknown key with a reason naming what it does run', () => {
    const resolution = BEHAVIOUR_REGISTRY.resolve('motion.orbit', 1);
    expect(resolution.ok).toBe(false);
    if (resolution.ok) throw new Error('unreachable');
    expect(resolution.reason).toContain('motion.orbit@1');
    expect(resolution.reason).toContain('motion.bounded-path@1');
  });

  it('refuses a known key at an unreviewed VERSION, rather than running the old motion', () => {
    // A version bump is how a reviewed behaviour changes its parameters, so resolving version 2
    // against the version 1 implementation would run yesterday's motion on today's numbers.
    expect(BEHAVIOUR_REGISTRY.has(BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION)).toBe(true);
    expect(BEHAVIOUR_REGISTRY.has(BOUNDED_PATH_KEY, 2)).toBe(false);
    const resolution = BEHAVIOUR_REGISTRY.resolve(BOUNDED_PATH_KEY, 2);
    if (resolution.ok) throw new Error('unreachable');
    expect(resolution.reason).toContain('motion.bounded-path@2');
  });

  it('rejects a malformed catalog rather than shipping one', () => {
    const base: BehaviourDefinition = {
      behaviourKey: 'motion.bounded-path',
      behaviourVersion: 1,
      summary: 's',
      parameters: { travel_mm: { kind: 'integer', minimum: 1, maximum: 2, default: 1 } },
      controls: ['trigger', 'stop', 'reset'],
      resetIsExact: true,
    };
    expect(() => new BehaviourRegistry([base, base])).toThrow(/duplicate behaviour/);
    expect(() => new BehaviourRegistry([{
      ...base, parameters: { t: { kind: 'integer', minimum: 1, maximum: 2, default: 9 } },
    }])).toThrow(/default lies outside/);
    expect(() => new BehaviourRegistry([{
      ...base, parameters: { t: { kind: 'choice', choices: ['only'], default: 'only' } },
    }])).toThrow(/at least two distinct choices/);
    expect(() => new BehaviourRegistry([{
      ...base, parameters: { t: { kind: 'choice', choices: ['a', 'b'], default: 'c' } },
    }])).toThrow(/default is not one of its choices/);
    expect(() => new BehaviourRegistry([{ ...base, parameters: {} }])).toThrow(/no parameters/);
  });
});

describe('parameters are read against the declared descriptors', () => {
  const read = (source: unknown) =>
    BEHAVIOUR_REGISTRY.readParameters(BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION, source);

  it('fills every declared default when nothing is supplied', () => {
    const result = read({});
    if (!result.ok) throw new Error('unreachable');
    expect(result.parameters).toEqual({
      travel_mm: 1000, period_milliseconds: 4000, axis: 'x', easing: 'smooth',
    });
    expect(result.clamped).toEqual([]);
  });

  it('clamps an integer to its declared bound and names what it moved', () => {
    const result = read({ travel_mm: 99_999, period_milliseconds: 1, axis: 'z', easing: 'linear' });
    if (!result.ok) throw new Error('unreachable');
    expect(result.parameters).toEqual({
      travel_mm: 10_000, period_milliseconds: 500, axis: 'z', easing: 'linear',
    });
    expect(result.clamped).toEqual(['travel_mm', 'period_milliseconds']);
  });

  it('refuses an unknown parameter name rather than ignoring it', () => {
    // The server fails closed on an unknown parameter, and a parameter this build silently drops
    // is a parameter whose effect nobody can see.
    const result = read({ amplitude: 2 });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('unreachable');
    expect(result.reason).toContain('“amplitude” is not a parameter');
  });

  it('refuses an unknown choice rather than substituting the default', () => {
    for (const [name, value] of [['axis', 'w'], ['easing', 'bouncy']] as const) {
      const result = read({ [name]: value });
      expect(result.ok).toBe(false);
      if (result.ok) throw new Error('unreachable');
      expect(result.reason).toContain(`is not a supported ${name}`);
    }
  });

  it('refuses a wrong kind, including a float where a whole number was declared', () => {
    expect(read({ travel_mm: 1000.5 }).ok).toBe(false);
    expect(read({ travel_mm: '1000' }).ok).toBe(false);
    expect(read({ travel_mm: Number.NaN }).ok).toBe(false);
    expect(read({ axis: 3 }).ok).toBe(false);
    expect(read(null).ok).toBe(false);
    expect(read([1, 2]).ok).toBe(false);
  });

  it('refuses parameters for an unresolvable behaviour before reading any of them', () => {
    const result = BEHAVIOUR_REGISTRY.readParameters('walk', 1, { travel_mm: 1000 });
    expect(result.ok).toBe(false);
  });
});

describe('bounded reversing travel along one axis', () => {
  it('starts at zero displacement and returns to it after one period, on both easings', () => {
    for (const easing of ['linear', 'smooth'] as const) {
      expect(travelFraction(easing, 0)).toBe(0);
      expect(travelFraction(easing, 1)).toBe(0);
      expect(travelFraction(easing, 2)).toBe(0);
      // Halfway is the far end of the travel, exactly, for both.
      expect(travelFraction(easing, 0.5)).toBeCloseTo(1, 12);
    }
  });

  it('never leaves the bound in either direction, and never goes negative', () => {
    for (const easing of ['linear', 'smooth'] as const) {
      for (let p = 0; p <= 2; p += 0.001) {
        const fraction = travelFraction(easing, p);
        expect(fraction).toBeGreaterThanOrEqual(0);
        expect(fraction).toBeLessThanOrEqual(1 + 1e-12);
      }
    }
  });

  it('travels at an even pace on linear and eases on smooth', () => {
    // A triangle is exactly half way along at a quarter phase; a raised cosine is not.
    expect(travelFraction('linear', 0.25)).toBeCloseTo(0.5, 12);
    expect(travelFraction('smooth', 0.25)).toBeCloseTo(0.5, 12);
    // They differ in between: at an eighth the triangle is at 0.25 and the cosine is below it.
    expect(travelFraction('linear', 0.125)).toBeCloseTo(0.25, 12);
    expect(travelFraction('smooth', 0.125)).toBeLessThan(0.2);
  });

  it('displaces only the axis it was given, by whole travel at the far end', () => {
    const half = motionOffsetAt(path({ axis: 'z', travelMm: 2000 }), 2000);
    expect(half[0]).toBe(0);
    expect(half[1]).toBe(0);
    expect(half[2]).toBeCloseTo(2000, 9);
  });

  it('holds still when the travel is zero or the period is not positive', () => {
    expect(motionOffsetAt(path({ travelMm: 0 }), 1700)).toBe(NO_MOTION_OFFSET);
    expect(motionOffsetAt(path({ periodMilliseconds: 0 }), 1700)).toBe(NO_MOTION_OFFSET);
    expect(motionOffsetAt(path(), Number.NaN)).toBe(NO_MOTION_OFFSET);
    expect(motionOffsetAt(path(), 0)).toBe(NO_MOTION_OFFSET);
  });

  it('reads a validated parameter bag into the path it runs on', () => {
    const read = BEHAVIOUR_REGISTRY.readParameters(BOUNDED_PATH_KEY, BOUNDED_PATH_VERSION, {
      travel_mm: 2500, period_milliseconds: 8000, axis: 'y', easing: 'linear',
    });
    if (!read.ok) throw new Error('unreachable');
    expect(boundedPathOf(read.parameters)).toEqual({
      travelMm: 2500, periodMilliseconds: 8000, axis: 'y', easing: 'linear',
    });
  });
});

describe('trigger, stop and reset', () => {
  it('does not move until it is triggered', () => {
    const motion = new BoundedMotion(path());
    motion.advance(1000);
    expect(motion.state).toBe('at-rest');
    expect(motion.offset).toBe(NO_MOTION_OFFSET);
  });

  it('moves after trigger, holds its phase on stop, and resumes on the next trigger', () => {
    const motion = new BoundedMotion(path({ axis: 'y', travelMm: 1000, periodMilliseconds: 4000 }));
    motion.trigger();
    motion.advance(2000);
    expect(motion.state).toBe('running');
    expect(motion.offset[1]).toBeCloseTo(1000, 9);

    motion.stop();
    expect(motion.state).toBe('held');
    const held = motion.offset;
    motion.advance(1000);
    expect(motion.offset).toEqual(held);
    expect(motion.elapsedMilliseconds).toBe(2000);

    motion.trigger();
    motion.advance(1000);
    expect(motion.elapsedMilliseconds).toBe(3000);
  });

  it('ignores a non-finite, zero or negative frame delta', () => {
    const motion = new BoundedMotion(path());
    motion.trigger();
    for (const dt of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1]) motion.advance(dt);
    expect(motion.elapsedMilliseconds).toBe(0);
    expect(motion.offset).toBe(NO_MOTION_OFFSET);
  });

  it('keeps the phase inside one period however long it runs', () => {
    const motion = new BoundedMotion(path({ periodMilliseconds: 4000 }));
    motion.trigger();
    for (let i = 0; i < 10_000; i += 1) motion.advance(500);
    expect(motion.elapsedMilliseconds).toBeGreaterThanOrEqual(0);
    expect(motion.elapsedMilliseconds).toBeLessThan(4000);
  });

  it('restores the authored millimetres EXACTLY on reset, by returning the authored triple', () => {
    const motion = new BoundedMotion(path({ axis: 'y', travelMm: 1500, periodMilliseconds: 3000 }));
    motion.trigger();
    for (const dt of [370, 110, 900, 250, 1400]) motion.advance(dt);
    const moved = motionTransform(AUTHORED, motion.offset);
    expect(moved).not.toBe(AUTHORED);
    expect(moved[1]).not.toBe(AUTHORED[1]);

    motion.reset();
    expect(motion.state).toBe('at-rest');
    expect(motion.elapsedMilliseconds).toBe(0);
    const restored = motionTransform(AUTHORED, motion.offset);
    // Identity, not equality: no arithmetic touched the authored numbers.
    expect(restored).toBe(AUTHORED);
    for (let i = 0; i < 3; i += 1) expect(Object.is(restored[i], AUTHORED[i])).toBe(true);
  });

  it('preserves a negative zero, which adding zero would not', () => {
    expect(Object.is(AUTHORED[1], -0)).toBe(true);
    expect(Object.is(motionTransform(AUTHORED, NO_MOTION_OFFSET)[1], -0)).toBe(true);
    expect(Object.is(AUTHORED[1] + 0, -0)).toBe(false);
  });

  it('resets exactly from every reachable state, including one never triggered', () => {
    for (const script of [
      () => undefined,
      (m: BoundedMotion) => { m.trigger(); },
      (m: BoundedMotion) => { m.trigger(); m.advance(700); },
      (m: BoundedMotion) => { m.trigger(); m.advance(700); m.stop(); },
      (m: BoundedMotion) => { m.trigger(); m.advance(700); m.stop(); m.trigger(); m.advance(300); },
      (m: BoundedMotion) => { m.reset(); m.trigger(); m.advance(2200); m.reset(); m.trigger(); },
    ]) {
      const motion = new BoundedMotion(path());
      script(motion);
      motion.reset();
      expect(motionTransform(AUTHORED, motion.offset)).toBe(AUTHORED);
    }
  });

  it('stays at rest when stop arrives before the phase has advanced', () => {
    const motion = new BoundedMotion(path());
    motion.trigger();
    motion.stop();
    expect(motion.state).toBe('at-rest');
    expect(motionTransform(AUTHORED, motion.offset)).toBe(AUTHORED);
  });

  it('displaces only the translation, in millimetres', () => {
    const moved = motionTransform(AUTHORED, [0, 250, 0]);
    expect(moved).toEqual([1200, 250, -450]);
  });
});
